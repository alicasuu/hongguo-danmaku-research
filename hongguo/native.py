"""Experimental native Hongguo danmaku adapter, without app signature emulation.

Wire fields were identified in a public third-party implementation, not official
API documentation. Live acceptance must be established separately. A comment
list is accepted ONLY with matching native danmaku request context and offsets.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
import requests
from .storage import Store
from .util import utcnow, stable_hash, file_sha256, json_str
from .native_runtime import fetch_native_response, request_after_page, resume_request

HOST = 'api5-normal-sinfonlinea.fqnovel.com'
HOSTS = {HOST, 'api5-normal-sinfonlineb.fqnovel.com'}
SOURCE = 'hongguo_native_comment_type_20_v1'


def integer(value, name):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError(f'{name} must be an explicit nonnegative integer')
    return int(value)


def request_spec(drama_id, episode_id, offset_ms=0, cursor='', duration_ms=0, host=HOST):
    if host not in HOSTS: raise ValueError('Unrecognized native source host')
    for value in (drama_id, episode_id):
        if not re.fullmatch(r'\d+', str(value)):
            raise ValueError('Native Hongguo IDs must be decimal strings')
    return {'url': f'https://{host}/novel/commentapi/comment/list/{episode_id}/v1/?aid=8662',
            'body': {'comment_source': 601, 'server_channel': 1000,
                     'group_id': str(episode_id), 'group_type': 30, 'comment_type': 20,
                     'sort': 1, 'business_param': {'book_id': str(drama_id),
                     'start_offset_time': integer(offset_ms, 'offset'),
                     'playlet_item_duration': integer(duration_ms, 'duration'),
                     'need_danmaku_guide_type': [1, 3, 4, 2]},
                     'count': 90, 'cursor': str(cursor), 'aid': 8662, 'compliance_status': 0}}


def parse_native_page(payload, request, drama_id, episode_id):
    """Fail the entire page on ambiguity. Never default missing offsets to zero."""
    if (not isinstance(request, dict) or not isinstance(request.get('url'), str)
            or not isinstance(request.get('body'), dict)
            or not isinstance(request['body'].get('business_param'), dict)):
        raise ValueError('Malformed native request context')
    u = urlsplit(request['url'])
    b = request['body']
    if (u.scheme != 'https' or u.hostname not in HOSTS or u.username or u.password or u.port
            or u.path != f'/novel/commentapi/comment/list/{episode_id}/v1/'
            or b.get('comment_type') != 20 or b.get('group_type') != 30
            or str(b.get('group_id')) != str(episode_id)
            or str(b.get('business_param', {}).get('book_id')) != str(drama_id)):
        raise ValueError('Not a matching Hongguo native danmaku request')
    if (not isinstance(payload, dict) or type(payload.get('code')) not in (int,str)
            or payload.get('code') not in (0,'0')):
        code=payload.get('code',payload.get('Code')) if isinstance(payload,dict) else None
        raise ValueError(f'Native API did not report success (code={code}); this is not a zero-message result')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('data_list'), list):
        raise ValueError('Missing native data.data_list; not an empty danmaku pool')
    rows = []
    for item in data['data_list']:
        if not isinstance(item, dict) or not isinstance(item.get('comment'), dict):
            raise ValueError('Malformed native message container')
        comment = item.get('comment', {})
        if (not isinstance(comment.get('common'), dict)
                or not isinstance(comment['common'].get('content'), dict)
                or not isinstance(comment.get('expand'), dict)):
            raise ValueError('Malformed native message content or timing')
        mid = comment.get('comment_id')
        if mid is not None and (isinstance(mid, bool) or not isinstance(mid, (int, str)) or not str(mid).strip()):
            raise ValueError('Native message ID invalid or imprecise')
        if str(mid).startswith('dm-init-'):
            raise ValueError('dm-init IDs identify generated review overlays, not native messages')
        text = comment.get('common', {}).get('content', {}).get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Native message text missing')
        offset_path = 'comment.expand.offset_time' if comment['expand'].get('offset_time') is not None else 'comment.offset_time'
        offset = integer(comment['expand'].get('offset_time') if offset_path.endswith('expand.offset_time') else comment.get('offset_time'), 'offset_time')
        status = comment['common'].get('status')
        if status is not None and (isinstance(status,bool) or str(status) != '1'):
            raise ValueError('Native message status is not published; page retained without normalized import')
        for container in (comment, comment.get('common', {})):
            if 'group_id' in container and str(container['group_id']) != str(episode_id):
                raise ValueError('Response episode identity mismatch')
        rows.append({'drama_id': str(drama_id), 'episode_id': str(episode_id),
                     'message_id': str(mid) if mid is not None else None, 'text': text, 'playback_time_ms': offset,
                     'timing_method': 'platform_native', 'source': SOURCE, 'coverage': 'partial',
                     'raw_item':item, 'offset_source':offset_path, 'source_url':request['url'],
                     # Raw time fields survive verbatim. No unverified unit/timezone conversion.
                     'posting_time_raw':{path:holder[key] for path,holder,key in (
                         ('comment.create_time',comment,'create_time'),
                         ('comment.common.create_time',comment['common'],'create_time'),
                         ('comment.common.posted_at',comment['common'],'posted_at')) if key in holder},
                     'identity_basis':'platform_message_id' if mid is not None else 'content_offset_raw_time_fingerprint'})
    info = data.get('common_list_info', {})
    if not isinstance(info, dict) or not isinstance(data.get('extra', {}), dict):
        raise ValueError('Malformed native pagination')
    more = info.get('has_more')
    if isinstance(more,str):
        more={'true':True,'false':False,'1':True,'0':False}.get(more.strip().lower(), 'invalid')
    if more not in (True, False, 0, 1, None):
        raise ValueError('Invalid has_more; pagination is unknown')
    next_offset = data.get('extra', {}).get('next_query_danmaku_list_time')
    if next_offset is not None:
        next_offset = integer(next_offset, 'next_query_danmaku_list_time')
    cursor = info.get('cursor', '')
    if not isinstance(cursor, (int, str)) or isinstance(cursor, bool):
        raise ValueError('Invalid native cursor')
    if isinstance(cursor,str) and cursor.lstrip().startswith('{'):
        try: cursor_data=json.loads(cursor)
        except ValueError as exc: raise ValueError('Malformed JSON pagination cursor') from exc
        for key in ('end_offset_time','next_offset_time','offset'):
            if key in cursor_data:
                candidate=integer(cursor_data[key], 'cursor.'+key)
                next_offset=max(candidate,next_offset) if next_offset is not None else candidate
                break
    if more is not None and not bool(more): next_offset=None
    if more is None and next_offset is None:
        raise ValueError('Missing has_more and next offset; pagination is unknown')
    return rows, {'has_more':bool(more) if more is not None else None, 'cursor':str(cursor), 'next_offset_ms':next_offset}


def save_page(db, run, payload, request, drama_id, episode_id, evidence, captured_at):
    rows, pagination = parse_native_page(payload, request, drama_id, episode_id)
    added = updated = 0
    # Messages and page checkpoint commit together. Replaying a page is safe.
    with db.db:
        for row in rows:
            key = stable_hash(SOURCE, episode_id, row['message_id']) if row['message_id'] is not None else stable_hash(
                SOURCE,episode_id,'missing-id',row['text'],row['playback_time_ms'],json_str(row['posting_time_raw']))
            raw=json_str(row['raw_item'])
            old = db.db.execute('SELECT text,playback_time_ms,raw_json FROM danmaku WHERE dedup_key=?', (key,)).fetchone()
            if old is None:
                db.db.execute('''INSERT INTO danmaku(dedup_key,drama_id,episode_id,message_id,text,
                    playback_time_ms,timing_method,captured_at,source,coverage,raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (key,drama_id,episode_id,row['message_id'],row['text'],row['playback_time_ms'],
                     'platform_native',captured_at,SOURCE,'partial',raw))
                added += 1
            elif (old['text'],old['playback_time_ms'],old['raw_json']) != (row['text'],row['playback_time_ms'],raw):
                db.db.execute('UPDATE danmaku SET text=?,playback_time_ms=?,raw_json=? WHERE dedup_key=?',
                              (row['text'],row['playback_time_ms'],raw,key))
                updated += 1
            db.db.execute('''UPDATE danmaku SET source_url=?,offset_source=?,posting_time_raw_json=?,
                identity_basis=?,last_seen_at=? WHERE dedup_key=?''',
                (row['source_url'],row['offset_source'],json_str(row['posting_time_raw']),row['identity_basis'],captured_at,key))
            db.db.execute('''INSERT OR IGNORE INTO native_danmaku_versions
                (version_key,dedup_key,raw_json,captured_at,evidence_path,sha256) VALUES(?,?,?,?,?,?)''',
                (stable_hash(key,raw),key,raw,captured_at,str(evidence),file_sha256(evidence)))
        db.db.execute('''INSERT INTO native_danmaku_pages(run_id,episode_id,source_url,captured_at,
            request_json,evidence_path,sha256,rows_seen,inserted,updated,next_offset_ms,next_cursor,has_more)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (run,episode_id,request['url'],captured_at,json_str(request['body']),str(evidence),
             file_sha256(evidence),len(rows),added,updated,pagination['next_offset_ms'],
             pagination['cursor'],int(pagination['has_more']) if pagination['has_more'] is not None else None))
    return {'seen':len(rows),'inserted':added,'updated':updated,**pagination}


def collect_native(dbpath, *, drama_id, episode_id, outdir, max_pages=1, duration_ms=0,
                   capture=None, access_basis='public unsigned availability probe', client=None,
                   retries=2, resume=False, host=HOST):
    """One bounded scan; repeat from zero to discover late messages at old offsets.

    capture is an authorized raw envelope with request and response objects.
    It is provenance asserted by its provider, not independent authentication.
    No highest-playback-time watermark: playback offsets are not posting times.
    """
    if not 1 <= max_pages <= 1000:
        raise ValueError('max_pages must be 1..1000')
    if not 0 <= retries <= 5:
        raise ValueError('retries must be 0..5')
    if resume and capture:
        raise ValueError('--resume applies to live scans, not capture imports')
    if capture and (not access_basis.strip() or access_basis == 'public unsigned availability probe'):
        raise ValueError('Capture import requires an explicit --access-basis describing the authorized source')
    request = request_spec(drama_id, episode_id, duration_ms=duration_ms,host=host)
    # An ordinary requests.Session cannot supply an authorized app signing flow.
    # Do not silently fall back to another unsigned probe, including on --resume.
    # A future verified integration must supply its transport explicitly; current
    # injected clients in tests are mocks and are not evidence of such access.
    if capture is None and client is None:
        return {'status':'blocked','reason_code':'authorized_native_transport_not_connected',
                'episode_id':str(episode_id),'pages':0,'seen':0,'inserted':0,'updated':0,
                'network_requests':0,'live':False,'coverage':'unverified',
                'error':'No permitted native signing/session transport is connected. '
                        'Unsigned fallback is disabled. Viewer login alone does not configure '
                        'this transport; platform-side availability remains undetermined.'}
    out = Path(outdir).resolve(); out.mkdir(parents=True, exist_ok=True)
    result = {'status':'running','episode_id':episode_id,'pages':0,'seen':0,'inserted':0,
              'updated':0,'coverage':'partial','live':capture is None,'resume':resume,
              'note':'Experimental wire adapter; no full-history or real-time guarantee.'}
    with Store(dbpath) as db:
        if not db.db.execute('SELECT 1 FROM episodes WHERE drama_id=? AND episode_id=?',
                             (drama_id,episode_id)).fetchone():
            raise ValueError('Episode does not belong to the supplied drama')
        run = db.start('native_danmaku_capture' if capture else 'native_danmaku_probe')
        result['run_id'] = run
        db.db.execute('UPDATE collection_runs SET detail_json=? WHERE run_id=?',
                      (json_str({'result':result}),run))
        db.db.commit()
        try:
            if resume:
                found,pending=resume_request(db,episode_id,duration_ms,run)
                if found and pending is None:
                    result['status']='already_scanned_partial'
                    db.finish(run,'partial',result=result)
                    (out/f'run_{run}_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                    return result
                if found:
                    request=pending
                    duration_ms=request['body']['business_param']['playlet_item_duration']
                    result['resumed']=True
            markers = set()
            for index in range(max_pages):
                marker = (request['body']['business_param']['start_offset_time'],request['body']['cursor'])
                if marker in markers:
                    raise ValueError('Repeated pagination marker; refusing loop')
                markers.add(marker)
                captured_at = utcnow()
                evidence = out / f'run_{run}_page_{index+1}.json'
                if evidence.exists():
                    raise FileExistsError('Use a separate evidence directory per database')
                if capture:
                    envelope = json.loads(Path(capture).read_text(encoding='utf-8'))
                    if not isinstance(envelope,dict):
                        raise ValueError('Capture must be a request/response envelope')
                    incoming = envelope.get('request')
                    payload = envelope['response']
                    parse_native_page(payload,incoming,drama_id,episode_id)
                    # Strip headers and query credentials; only the native request shape is needed.
                    request = {'url':request_spec(drama_id,episode_id,host=urlsplit(incoming['url']).hostname)['url'],
                               'body':request_spec(drama_id,episode_id,
                                   offset_ms=incoming['body']['business_param'].get('start_offset_time',0),
                                   duration_ms=incoming['body']['business_param'].get('playlet_item_duration',0),
                                   cursor=incoming['body'].get('cursor',''))['body']}
                    envelope = {'request':request,'response':payload,
                                'imported_at':captured_at,'access_basis':access_basis,
                                'provider_captured_at':envelope.get('captured_at')}
                else:
                    client._verify_robots(request['url'])
                    envelope={'request':request,**fetch_native_response(client,request,retries),
                              'captured_at':captured_at,'access_basis':access_basis}
                    payload=envelope['response']
                    evidence.write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
                    if envelope['http_status'] != 200:
                        raise PermissionError(f'Native endpoint HTTP {envelope["http_status"]}; see {evidence}')
                    if payload is None:
                        raise ValueError(f'Native endpoint returned non-JSON; see {evidence}')
                if capture:
                    evidence.write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
                page = save_page(db,run,payload,request,drama_id,episode_id,evidence,captured_at)
                for key in ('seen','inserted','updated'): result[key] += page[key]
                result['pages'] += 1
                if capture:
                    result['status']='capture_imported'; break
                pending=request_after_page(request,page,duration_ms)
                if pending is None:
                    result['status']='scan_finished_partial'; break
                request=pending
            else:
                result['status']='page_limit_reached'
            db.add_receipt({'drama_id':drama_id,'episode_id':episode_id,'data_kind':'danmaku',
                            'source':SOURCE,'source_url':request['url'],'coverage':'partial',
                            'rows_seen':result['seen'],'rights_basis':access_basis,
                            'evidence_file':str(evidence),'note':result['status']})
            db.finish(run,'partial',result=result)
        except (ValueError,KeyError,TypeError,PermissionError,OSError,RuntimeError,requests.RequestException) as exc:
            result['status']='blocked' if result['pages']==0 else 'partial_failed'
            if not result['pages']: result['coverage']='unavailable'
            result['error']=f'{type(exc).__name__}: {exc}'
            db.event(run,'error','native_collection_attempt_failed',result['error'],'episode',episode_id)
            db.add_receipt({'drama_id':drama_id,'episode_id':episode_id,'data_kind':'danmaku',
                            'source':SOURCE,'source_url':request['url'],'coverage':'failed',
                            'rows_seen':result['seen'],'rights_basis':access_basis,'note':result['error']})
            db.finish(run,'failed' if not result['pages'] else 'partial',result=result)
        (out/f'run_{run}_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
