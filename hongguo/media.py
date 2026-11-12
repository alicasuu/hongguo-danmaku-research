"""Rights-confirmed local or HTTPS direct-file media ingestion and verification.

No DRM decryption, private endpoint use, stream-token extraction or login bypass.
"""
from __future__ import annotations
import csv
import json
import logging
import math
import tempfile
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import requests
from .storage import Store
from .util import file_sha256,utcnow,is_truthy,validate_public_http_url

LOG=logging.getLogger(__name__)
MAX_BYTES_DEFAULT=2 * 1024 ** 3


def ffprobe(path):
    if not shutil.which('ffprobe'):
        raise RuntimeError('ffprobe not found; install ffmpeg to verify actual video duration')
    r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name',
                      '-of','json',str(path)],capture_output=True,text=True,timeout=45)
    if r.returncode:
        raise RuntimeError('ffprobe failed: '+r.stderr[:300])
    data=json.loads(r.stdout)
    streams=data.get('streams',[])
    if not any(s.get('codec_type')=='video' for s in streams):
        raise ValueError('File has no video stream')
    duration=float(data.get('format',{}).get('duration',0))
    if not math.isfinite(duration) or duration <=0: raise ValueError('File has invalid duration')
    return duration


def validate_duration(actual, expected):
    if not math.isfinite(actual) or actual <= 0:
        raise ValueError('Observed duration must be finite and positive')
    if expected is None:
        return 'reference_missing'
    if not math.isfinite(expected) or expected <= 0:
        raise ValueError('Expected duration must be finite and positive')
    # The old 3s absolute tolerance accepted a 1s preview as a complete 2s clip.
    tolerance = min(max(0.25, expected * 0.02), expected * 0.05)
    return 'matched' if abs(actual-expected) <= tolerance else 'mismatch'


def verify_decode(path):
    if not shutil.which('ffmpeg'):
        raise RuntimeError('ffmpeg required to check the entire video for decoding errors')
    result = subprocess.run(['ffmpeg','-nostdin','-hide_banner','-v','error','-xerror',
                             '-err_detect','explode','-i',str(path),'-map','0:v:0',
                             '-map','0:a?','-f','null','-'],capture_output=True,text=True,timeout=600)
    if result.returncode or result.stderr.strip():
        raise ValueError('Full video decode failed: '+result.stderr[:300])


def media_destination(root, sid, eid, suffix):
    for value in (sid, eid):
        if not value or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in value):
            raise ValueError('Unsafe drama or episode ID for media path')
    path = Path(root) / sid / (eid + suffix)
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Media destination escapes media root')
    return path


def download_direct_file(url,dest,*,allowed_hosts,slow_seconds=2,max_bytes=MAX_BYTES_DEFAULT):
    validate_public_http_url(url,set(allowed_hosts))
    if urlparse(url).path.lower().endswith(('.m3u8','.mpd')):
        raise ValueError('HLS/DASH playlists are not downloaded; use an authorized unencrypted full-file export')
    dest=Path(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)
    if max_bytes <= 0: raise ValueError('max_bytes must be positive')
    if dest.exists(): raise FileExistsError('Refusing to overwrite an existing video')
    handle=tempfile.NamedTemporaryFile(dir=dest.parent,suffix='.part',delete=False)
    part=Path(handle.name); handle.close()
    import time
    time.sleep(max(1,slow_seconds))
    try:
      with requests.get(url,stream=True,timeout=(15,80),allow_redirects=False,
                      headers={'User-Agent':'AcademicMicroDramaCollector/1.0'},) as r:
        if 300 <= r.status_code < 400: raise PermissionError('Redirect not followed; verify destination host and rights')
        r.raise_for_status()
        ct=r.headers.get('Content-Type','').lower()
        if not any(t in ct for t in ('video/','application/octet-stream')):
            raise ValueError('Response is not a direct video file; not downloading')
        if r.headers.get('Content-Length') and int(r.headers['Content-Length'])>max_bytes:
            raise ValueError('File exceeds --max-bytes')
        expected_bytes=int(r.headers['Content-Length']) if r.headers.get('Content-Length') else None
        size=0
        with part.open('wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                size += len(chunk)
                if size>max_bytes:
                    f.close();part.unlink(missing_ok=True)
                    raise ValueError('File exceeded maximum permitted bytes')
                f.write(chunk)
        if not size: raise ValueError('Empty video response')
        if expected_bytes is not None and not r.headers.get('Content-Encoding') and size != expected_bytes:
            raise ValueError('Incomplete video download (Content-Length mismatch)')
      ffprobe(part)
      verify_decode(part)
      part.replace(dest)
    finally:
      part.unlink(missing_ok=True)
    return dest


def import_media_manifest(manifest,dbpath,*,media_root,download_authorized=False,allowed_hosts=(),max_bytes=MAX_BYTES_DEFAULT,resume_transfers=False):
    """Manifest columns: drama_id,episode_id,local_path/direct_url,access_basis,rights_confirmed,
       is_full_episode,expected_duration_seconds,subtitle_path,source,note.

       verified_full requires a valid video, rights assertion, explicit full-episode declaration AND
       full decoding and matching an independent expected duration. This is a technical check only.
    """
    media_root=Path(media_root)
    media_root.mkdir(parents=True,exist_ok=True)
    report={'seen':0,'valid_video':0,'full_verified':0,'subtitle_imported':0,'failed':0,'errors':[]}
    with Store(dbpath) as db:
        run=db.start('import_media')
        with Path(manifest).open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                report['seen']+=1
                sid,eid=str(row.get('drama_id') or ''),str(row.get('episode_id') or '')
                try:
                    ep=db.db.execute('SELECT * FROM episodes WHERE drama_id=? AND episode_id=?',(sid,eid)).fetchone()
                    if not ep: raise ValueError('Unknown episode; import dramas/episodes before media')
                    if not is_truthy(row.get('rights_confirmed')):
                        raise PermissionError('rights_confirmed must be true: requires an authorized source')
                    source=row.get('source') or 'authorized_media_export'
                    basis=row.get('access_basis') or 'user_authorized_export'
                    path=None
                    direct_url=row.get('direct_url') or ''
                    if direct_url:
                        if not download_authorized:
                            raise PermissionError('Direct download disabled unless --download-authorized is set')
                        if not allowed_hosts:
                            raise PermissionError('Direct download requires an explicit allowlist host')
                        suffix=Path(urlparse(direct_url).path).suffix.lower()
                        if suffix not in {'.mp4','.mov','.webm','.mkv'}:
                            raise ValueError('Direct URL has an unsupported file suffix')
                        path=media_destination(media_root,sid,eid,suffix)
                        if not path.exists():
                            if resume_transfers:
                                from .transfers import download_resumable
                                download_resumable(direct_url,path,allowed_hosts=allowed_hosts,max_bytes=max_bytes)
                            else:download_direct_file(direct_url,path,allowed_hosts=allowed_hosts,max_bytes=max_bytes)
                    elif row.get('local_path'):
                        raw=Path(row['local_path']).expanduser()
                        if not raw.is_file(): raise FileNotFoundError(str(raw))
                        if raw.suffix.lower() not in {'.mp4','.mov','.webm','.mkv'}:
                            raise ValueError('Unsupported media file type')
                        path=media_destination(media_root,sid,eid,raw.suffix.lower())
                        path.parent.mkdir(parents=True,exist_ok=True)
                        if raw.resolve()!=path.resolve():
                            if path.exists() and file_sha256(path)!=file_sha256(raw):
                                raise FileExistsError('Different video already exists; choose a new media root')
                            ffprobe(raw)
                            verify_decode(raw)
                            shutil.copy2(raw,path)
                    else:
                        raise ValueError('No local_path or authorized direct_url provided')
                    actual=ffprobe(path)
                    verify_decode(path)
                    expected=float(row['expected_duration_seconds']) if str(row.get('expected_duration_seconds') or '').strip() else None
                    if expected is None and ep['duration_seconds'] is not None:
                        expected=float(ep['duration_seconds'])
                    full_declared=is_truthy(row.get('is_full_episode'))
                    validation=validate_duration(actual,expected)
                    if ep['duration_seconds'] is not None and expected is not None:
                        if validate_duration(expected,float(ep['duration_seconds']))!='matched':
                            validation='reference_conflict'
                    matched=validation=='matched'
                    verified=full_declared and matched
                    size=path.stat().st_size
                    sha=file_sha256(path)
                    db.db.execute('''INSERT INTO assets(drama_id,episode_id,kind,local_path,sha256,bytes,observed_duration_seconds,declared_full,verified_full,access_basis,captured_at,source,note)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha256,episode_id,kind) DO UPDATE SET
                      local_path=excluded.local_path,declared_full=excluded.declared_full,
                      verified_full=excluded.verified_full,access_basis=excluded.access_basis,
                      source=excluded.source,note=excluded.note''',(sid,eid,'video',str(path),sha,size,actual,int(full_declared),int(verified),basis,utcnow(),source,row.get('note') or ''))
                    db.db.execute('''UPDATE episodes SET media_duration_seconds=?,expected_duration_seconds=?,duration_validation=?,media_path=?,media_status=?,completeness=?,media_sha256=?,media_bytes=?,checked_at=? WHERE episode_id=?''',
                                  (actual,expected,validation,str(path),'valid_video','verified_full' if verified else 'unverified',sha,size,utcnow(),eid))
                    db.db.commit()
                    report['valid_video']+=1
                    report['full_verified']+=int(verified)
                    if not verified:
                        db.event(run,'warning','full_episode_unverified',f'declared={full_declared}; expected={expected}; actual={actual}', 'episode',eid)
                    subtitle=row.get('subtitle_path') or ''
                    if subtitle:
                        sp=Path(subtitle).expanduser()
                        if not sp.is_file() or sp.suffix.lower() not in {'.srt','.vtt','.txt'}:
                            raise ValueError('Subtitle not a readable SRT/VTT/TXT')
                        target=media_root / sid / f'{eid}{sp.suffix.lower()}'
                        if target.resolve()!=sp.resolve(): shutil.copy2(sp,target)
                        db.db.execute('''INSERT OR IGNORE INTO assets(drama_id,episode_id,kind,local_path,sha256,bytes,access_basis,captured_at,source)
                         VALUES(?,?,?,?,?,?,?,?,?)''',(sid,eid,'subtitles',str(target),file_sha256(target),target.stat().st_size,basis,utcnow(),source))
                        db.db.execute("UPDATE episodes SET subtitles_path=?,subtitle_status='available' WHERE episode_id=?",(str(target),eid))
                        db.db.commit()
                        report['subtitle_imported']+=1
                except Exception as e:
                    report['failed']+=1
                    msg=f'{sid}/{eid}: {e}'
                    if len(report['errors'])<40:report['errors'].append(msg)
                    db.event(run,'error','media_failed',msg,'episode',eid)
        db.finish(run,'partial' if report['failed'] else 'complete',**report)
    return report


def make_contact_sheet(video_path,output_path,*,n=4):
    """Sample frames for HUMAN AI-vs-live-action and subtitle review (ffmpeg installed)."""
    duration=ffprobe(video_path)
    output_path=Path(output_path)
    output_path.mkdir(parents=True,exist_ok=True)
    result=[]
    for i in range(1,n+1):
        at=duration*i/(n+1)
        target=output_path/f'frame_{i:02d}.jpg'
        r=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',str(at),'-i',str(video_path),'-frames:v','1','-y',str(target)],
                         capture_output=True,text=True,timeout=60)
        if r.returncode:raise RuntimeError('ffmpeg frame extraction failed: '+r.stderr[:200])
        result.append(str(target))
    return result


def import_subtitle_manifest(manifest,dbpath,*,subtitle_root):
    """Authorized subtitle-only import (does not need video access)."""
    root=Path(subtitle_root)
    root.mkdir(parents=True,exist_ok=True)
    summary={'seen':0,'imported':0,'failed':0,'errors':[]}
    with Store(dbpath) as db:
        run=db.start('subtitle_import')
        with Path(manifest).open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                summary['seen']+=1
                try:
                    sid,eid=str(row.get('drama_id') or ''),str(row.get('episode_id') or '')
                    if not db.db.execute('SELECT 1 FROM episodes WHERE episode_id=? AND drama_id=?',(eid,sid)).fetchone():
                        raise ValueError('Unknown drama/episode')
                    if not is_truthy(row.get('rights_confirmed')):
                        raise PermissionError('Subtitle copy requires permission assertion')
                    sp=Path(str(row.get('subtitle_path') or '')).expanduser()
                    if not sp.is_file() or sp.suffix.lower() not in {'.srt','.vtt','.txt'}:
                        raise ValueError('Not a readable SRT/VTT/TXT subtitle file')
                    target=root / sid / (eid+sp.suffix.lower())
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if sp.resolve()!=target.resolve():shutil.copy2(sp,target)
                    db.db.execute('''INSERT OR IGNORE INTO assets(drama_id,episode_id,kind,local_path,sha256,bytes,access_basis,captured_at,source)
                         VALUES(?,?,?,?,?,?,?,?,?)''',(sid,eid,'subtitles',str(target),file_sha256(target),target.stat().st_size,
                           row.get('access_basis') or 'authorized_subtitle_export',utcnow(),row.get('source') or 'authorized_subtitle_export'))
                    db.db.execute("UPDATE episodes SET subtitles_path=?,subtitle_status='available' WHERE episode_id=?",(str(target),eid))
                    db.db.commit()
                    summary['imported']+=1
                except Exception as exc:
                    summary['failed']+=1
                    msg=f"row {summary['seen']}: {exc}"
                    if len(summary['errors'])<30:summary['errors'].append(msg)
                    db.event(run,'error','subtitle_import_failed',msg)
        db.finish(run,'partial' if summary['failed'] else 'complete',**summary)
    return summary
