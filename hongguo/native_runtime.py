"""Bounded transport retries and resume markers for the experimental adapter.

These helpers do not attach to browsers or obtain authentication credentials.
"""
from __future__ import annotations
import copy
import json
import time
from pathlib import Path
import requests
from .util import file_sha256


def fetch_native_response(client, request, retries=2, sleep=time.sleep):
    if not 0 <= retries <= 5:
        raise ValueError('retries must be 0..5')
    attempts=[]
    for attempt in range(retries+1):
        try:
            client._rate_limit()
            with client.s.post(request['url'],json=request['body'],timeout=(10,30),
                               allow_redirects=False,stream=True,
                               headers={'comment-source':'601','server-channel':'1000'}) as response:
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>8_000_000: raise ValueError('Native response exceeds 8 MB')
                    chunks.append(chunk)
                raw=b''.join(chunks).decode('utf-8',errors='replace')
                try:payload=json.loads(raw)
                except ValueError:payload=None
                status=response.status_code
                attempts.append({'attempt':attempt+1,'http_status':status,'bytes':size})
                # Never retry auth/rate-limit denials or successful HTTP business errors.
                if status in (500,502,503,504) and attempt<retries:
                    retry_after=response.headers.get('Retry-After')
                    try:delay=float(retry_after) if retry_after else 2**(attempt+1)
                    except (TypeError,ValueError):delay=None
                    # A long/opaque server cooldown requires a later manual resumption.
                    if delay is not None and 0<=delay<=30:
                        sleep(max(1,delay));continue
                return {'response':payload,'http_status':status,'attempts':attempts,
                        **({'non_json_response':raw} if payload is None else {})}
        except (requests.Timeout,requests.ConnectionError) as exc:
            attempts.append({'attempt':attempt+1,'transport_error':type(exc).__name__})
            if attempt==retries:
                # Do not expose URL/header details from arbitrary exception strings.
                raise RuntimeError(f'Native transport failed after {attempt+1} attempts: {type(exc).__name__}') from exc
            sleep(2**(attempt+1))


def request_after_page(request, page, duration_ms):
    result=copy.deepcopy(request)
    body=result['body'];start=body['business_param']['start_offset_time']
    if page['has_more'] is False:
        return None
    next_offset=page['next_offset_ms']
    if next_offset is not None:
        if next_offset<=start: raise ValueError('Non-advancing native offset')
        if duration_ms and next_offset>=duration_ms:return None
        body['business_param']['start_offset_time']=next_offset
        body['cursor']=page['cursor']
    elif page['has_more']:
        if not page['cursor'] or page['cursor']==body['cursor']:
            raise ValueError('has_more without an advancing cursor')
        body['cursor']=page['cursor']
    else:
        return None
    return result


def resume_request(db, episode_id, duration_ms, before_run):
    """The saved page is the checkpoint, committed atomically with its messages.

    Only live probe pages qualify. Provider captures do not move a live cursor.
    Returns (found, next_request), where None means the prior scan ended.
    """
    # A fresh scan that failed before committing page 1 must not inherit an
    # older completed scan's terminal checkpoint. Run metadata is persisted
    # before network work, including when the process is interrupted.
    starts=db.fetch('''SELECT run_id FROM collection_runs
        WHERE command='native_danmaku_probe' AND run_id<?
          AND json_extract(detail_json,'$.result.episode_id')=?
          AND json_extract(detail_json,'$.result.resume')=0
        ORDER BY run_id DESC LIMIT 1''',(before_run,episode_id))
    lower_bound=starts[0]['run_id'] if starts else 0
    pages=db.fetch('''SELECT p.* FROM native_danmaku_pages p
        JOIN collection_runs r ON r.run_id=p.run_id
        WHERE p.episode_id=? AND r.command='native_danmaku_probe'
          AND p.run_id>=? AND p.run_id<?
        ORDER BY p.id DESC LIMIT 1''',(episode_id,lower_bound,before_run))
    if not pages:return False,None
    page=pages[0]
    evidence=Path(page['evidence_path'])
    if not evidence.is_file() or file_sha256(evidence)!=page['sha256']:
        raise ValueError('Resume evidence missing or changed; refusing an unverified checkpoint')
    body=json.loads(page['request_json'])
    previous_duration=body['business_param']['playlet_item_duration']
    if duration_ms and duration_ms!=previous_duration:
        raise ValueError('Resume duration differs from checkpoint; start a new scan')
    request={'url':page['source_url'],'body':body}
    # Re-parse original evidence: older checkpoints used different terminal semantics.
    from .native import parse_native_page
    envelope=json.loads(evidence.read_text())
    _,pagination=parse_native_page(envelope['response'],request,body['business_param']['book_id'],episode_id)
    return True,request_after_page(request,pagination,previous_duration)
