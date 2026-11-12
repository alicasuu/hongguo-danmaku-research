"""Resumable, rights-confirmed HTTPS full-file transfers; no stream decryption.

Only strong ETags or Last-Modified validators permit appending. A checkpoint
contains a URL hash, never a URL or credentials. Final files require decoding.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests
from .util import stable_hash,validate_public_http_url


def download_resumable(url,dest,*,allowed_hosts,max_bytes,retries=2,slow_seconds=2,
                       session=None,sleep=time.sleep,verify=None):
    validate_public_http_url(url,set(allowed_hosts))
    if urlsplit(url).scheme!='https':raise ValueError('HTTPS required')
    if urlsplit(url).path.lower().endswith(('.m3u8','.mpd')):raise ValueError('Direct files only')
    if max_bytes<=0 or not 0<=retries<=5:raise ValueError('Invalid transfer bounds')
    dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():raise FileExistsError('Refusing to overwrite existing media')
    part=dest.with_suffix(dest.suffix+'.part');checkpoint=dest.with_suffix(dest.suffix+'.transfer.json')
    identity=stable_hash(url);state={}
    if checkpoint.exists():state=json.loads(checkpoint.read_text())
    if state and state.get('url_hash')!=identity:raise ValueError('Transfer source changed; use a separate destination')
    if verify is None:
        from .media import ffprobe,verify_decode
        def verify(path):ffprobe(path);verify_decode(path)
    transport=session or requests
    for attempt in range(retries+1):
        sleep(max(1,slow_seconds,2**attempt if attempt else 0))
        done=part.stat().st_size if part.exists() else 0
        validator=state.get('validator')
        if done and not validator:done=0  # Cannot safely append an unversioned object.
        headers={'User-Agent':'AcademicMicroDramaCollector/1.0','Accept-Encoding':'identity'}
        if done:headers.update({'Range':f'bytes={done}-','If-Range':validator})
        try:
            with transport.get(url,headers=headers,stream=True,timeout=(15,80),allow_redirects=False) as response:
                code=response.status_code
                if code in (401,403,429) or 300<=code<400:
                    raise PermissionError(f'Transfer stopped on HTTP {code}; no automatic access retry')
                if code in (500,502,503,504):
                    # Leave server cooldowns to a later run rather than retrying early.
                    if response.headers.get('Retry-After') or attempt==retries:raise RuntimeError(f'Transfer unavailable: HTTP {code}')
                    continue
                if code not in (200,206):raise ValueError(f'Unexpected transfer status {code}; 416 is not proof of completion')
                ct=response.headers.get('Content-Type','').lower()
                if not any(t in ct for t in ('video/','application/octet-stream')):raise ValueError('Not a direct media response')
                if response.headers.get('Content-Encoding','identity')!='identity':raise ValueError('Encoded range response unsupported')
                length=response.headers.get('Content-Length')
                length=int(length) if length is not None else None
                if length is not None and length<0:raise ValueError('Negative Content-Length')
                etag=response.headers.get('ETag')
                current=etag if etag and not etag.startswith('W/') else response.headers.get('Last-Modified')
                if code==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match:raise ValueError('Missing or malformed Content-Range')
                    start,end,total=map(int,match.groups())
                    if start!=done or end<start or end!=total-1:raise ValueError('Range does not cover requested remainder')
                    if length is not None and length!=end-start+1:raise ValueError('Range length mismatch')
                    if done and (current!=validator or state.get('total') not in (None,total)):
                        raise ValueError('Media changed while resuming')
                    expected=total
                else:
                    done=0;expected=length  # Server ignored Range or object changed: restart, never append.
                if expected is not None and expected>max_bytes:raise ValueError('Transfer exceeds maximum size')
                state={'url_hash':identity,'validator':current,'total':expected,'status':'partial'}
                temp=checkpoint.with_suffix('.tmp');temp.write_text(json.dumps(state));temp.replace(checkpoint)
                with part.open('ab' if done else 'wb') as stream:
                    for chunk in response.iter_content(1024*1024):
                        if done+len(chunk)>max_bytes:raise ValueError('Transfer exceeded maximum size')
                        stream.write(chunk);done+=len(chunk)
                if not done or expected is not None and done!=expected:
                    raise requests.ConnectionError('Incomplete transfer')
            verify(part)
            part.replace(dest);checkpoint.unlink(missing_ok=True)
            return dest
        except (requests.Timeout,requests.ConnectionError,requests.exceptions.ChunkedEncodingError):
            if attempt==retries:raise RuntimeError('Transfer interrupted; resumable partial retained') from None
    raise RuntimeError('Transfer did not finish')
