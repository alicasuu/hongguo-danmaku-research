"""Import real browser DOM samples into a separate partial-coverage dataset.

The JS companion runs through the connected browser's supported evaluate API.
No browser profile or credentials are needed. Local record/observation keys are
deduplication keys, NEVER fabricated platform message IDs. A render ID identifies
a node only within a capture session; it is not stable across page loads.
"""
from __future__ import annotations
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from .storage import Store
from .util import file_sha256, json_str, stable_hash, utcnow


def timestamp(value):
    if not isinstance(value,str): raise ValueError('Observation time must be an ISO timestamp')
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('Observation timestamp requires a timezone')
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def parse_capture(data):
    if data.get('schema_version')!=1 or not isinstance(data.get('session_id'),str) or not data['session_id']:
        raise ValueError('Capture requires schema_version=1 and a local session_id')
    snapshots=data.get('snapshots')
    if not isinstance(snapshots,list) or not snapshots: raise ValueError('Capture requires snapshots')
    rows=[]; identity=None
    for snap in snapshots:
        sid,eid=snap['drama_id'],snap['episode_id']
        if not all(isinstance(x,str) and re.fullmatch(r'\d+',x) for x in (sid,eid)):
            raise ValueError('Exact drama/episode IDs required')
        if identity and identity!=(sid,eid): raise ValueError('One episode per capture session')
        identity=sid,eid
        u=urlsplit(snap['source_url'])
        if (u.scheme!='https' or u.netloc!='hongguoduanju.com' or u.query or u.fragment or
                u.path not in (f'/player/{sid}',f'/player/{sid}/{eid}')):
            raise ValueError('Unexpected source URL')
        if snap.get('coverage')!='sampled_visible': raise ValueError('Only partial visible samples supported')
        observed=timestamp(snap['observed_at'])
        video=snap.get('video') or {}
        seconds=video.get('current_time_seconds')
        if seconds is not None and (type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0):
            raise ValueError('Invalid observed player position')
        ms=round(seconds*1000,6) if seconds is not None else None
        for item in snap['messages']:
            if item.get('visible') is not True: raise ValueError('Offscreen nodes cannot be imported')
            bounds=item['visible_bounds']
            if (not all(type(bounds.get(k)) in (int,float) and math.isfinite(bounds[k]) for k in ('left','right','top','bottom'))
                    or bounds['right']<=bounds['left'] or bounds['bottom']<=bounds['top']):
                raise ValueError('Invalid visible intersection')
            if item.get('platform_message_id') is not None or item.get('platform_playback_time_ms') is not None:
                raise ValueError('This overlay mode does not assert native IDs or timing')
            text=item['text']
            if not isinstance(text,str) or not text.strip(): raise ValueError('Missing displayed text')
            dom_id=item.get('dom_render_id')
            if dom_id is not None and not isinstance(dom_id,str): raise ValueError('Invalid render ID')
            review=item.get('source_review'); raw_posted=posted=None;index=None
            kind='unverified_visible_overlay'
            if review is not None:
                index=review.get('index')
                if (type(index) is not int or index<0 or dom_id!=f'dm-init-{index}' or
                    item.get('source_match')!='renderer_index_and_exact_text' or
                    not isinstance(review.get('content'),str) or review['content'].strip()!=text):
                    raise ValueError('Review attribution requires render index AND exact text')
                kind='regular_review_overlay'
                raw=review.get('create_time')
                if raw is not None:
                    if isinstance(raw,bool) or not re.fullmatch(r'\d+',str(raw)):
                        raise ValueError('Invalid source create_time')
                    raw_posted=str(raw)
                    posted=datetime.fromtimestamp(int(raw),timezone.utc).isoformat().replace('+00:00','Z')
            record=stable_hash(data['session_id'],eid,dom_id,text)
            observation=stable_hash(record,observed)
            rows.append(dict(record_id=record,observation_id=observation,session_id=data['session_id'],
                drama_id=sid,episode_id=eid,text=text,dom_render_id=dom_id,source_kind=kind,
                source_path=snap.get('source_path'),source_review_index=index,
                source_posted_at_raw=raw_posted,source_posted_at_utc=posted,
                observed_at=observed,source_url=snap['source_url'],observed_playback_time_ms=ms,
                timing_method='observed_playback_position' if ms is not None else 'unknown',
                video_paused=video.get('paused'),partially_clipped=bool(item.get('partially_clipped')),
                visible_bounds_json=json_str(bounds)))
    return identity,rows


def import_capture(db, path):
    path=Path(path).resolve();digest=file_sha256(path)
    data=json.loads(path.read_text(encoding='utf-8'))
    (sid,eid),rows=parse_capture(data)
    if not db.fetch('SELECT 1 FROM episodes WHERE episode_id=? AND drama_id=?',(eid,sid)):
        raise ValueError('Episode does not belong to the existing drama')
    # First-episode routes have no episode segment: verify the supplied mapping.
    if any(urlsplit(s['source_url']).path==f'/player/{sid}' for s in data['snapshots']):
        if not db.fetch('SELECT 1 FROM episodes WHERE episode_id=? AND episode_number=1',(eid,)):
            raise ValueError('First-episode page mapped to a different episode')
    if db.fetch('SELECT 1 FROM visible_overlay_captures WHERE capture_sha256=?',(digest,)):
        return {'status':'already_imported','records_added':0,'observations_added':0,'episode_id':eid}
    run=db.start('visible_overlay_import')
    added=observations=0
    try:
        with db.db:
            db.db.execute('''INSERT INTO visible_overlay_captures VALUES(?,?,?,?,?,?,?,?,?)''',
                (digest,run,data['session_id'],sid,eid,str(path),utcnow(),len(data['snapshots']),len(rows)))
            for row in rows:
                old=db.db.execute('SELECT * FROM visible_overlay_records WHERE record_id=?',(row['record_id'],)).fetchone()
                if old:
                    if old['source_posted_at_raw']!=row['source_posted_at_raw'] or old['source_kind']!=row['source_kind']:
                        raise ValueError('Source attribution changed within one page session; start a new session')
                    db.db.execute('UPDATE visible_overlay_records SET first_observed_at=min(first_observed_at,?), last_observed_at=max(last_observed_at,?) WHERE record_id=?',
                        (row['observed_at'],row['observed_at'],row['record_id']))
                else:
                    db.db.execute('''INSERT INTO visible_overlay_records(record_id,session_id,drama_id,episode_id,
                        text,dom_render_id,source_kind,source_path,source_review_index,source_posted_at_raw,
                        source_posted_at_utc,first_observed_at,last_observed_at,source_url,coverage)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'sampled_visible')''',
                        tuple(row[k] for k in ('record_id','session_id','drama_id','episode_id','text','dom_render_id',
                            'source_kind','source_path','source_review_index','source_posted_at_raw','source_posted_at_utc'))+
                        (row['observed_at'],row['observed_at'],row['source_url']))
                    added+=1
                observations+=db.db.execute('''INSERT OR IGNORE INTO visible_overlay_observations
                    VALUES(?,?,?,?,?,?,?,?,?)''',(row['observation_id'],row['record_id'],digest,row['observed_at'],
                    row['observed_playback_time_ms'],row['timing_method'],row['video_paused'],int(row['partially_clipped']),
                    row['visible_bounds_json'])).rowcount
        result={'status':'sampled_partial' if rows else 'no_visible_nodes_in_sample',
            'records_added':added,'observations_added':observations,'episode_id':eid,'coverage':'sampled_visible'}
        db.finish(run,'partial',result=result)
        return result
    except Exception as exc:
        db.finish(run,'failed',error=type(exc).__name__)
        raise


def export_visible(db,outdir):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    for name in ('visible_overlay_records','visible_overlay_observations','visible_overlay_captures'):
        cols=[r['name'] for r in db.db.execute(f'PRAGMA table_info({name})')]
        with (out/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
            writer.writerows(db.fetch(f'SELECT * FROM {name}'))
    # One analysis export contains text and both kinds of time.
    cur=db.db.execute('''SELECT r.*,o.observation_id,o.observed_at,o.observed_playback_time_ms,
        o.timing_method,o.video_paused,o.partially_clipped,o.capture_sha256
        FROM visible_overlay_records r JOIN visible_overlay_observations o USING(record_id)
        ORDER BY r.drama_id,r.episode_id,o.observed_at,r.record_id''')
    with (out/'visible_overlay_samples.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow([c[0] for c in cur.description]);writer.writerows(cur)
    counts=db.fetch('''SELECT drama_id,episode_id,count(*) records,count(DISTINCT text) distinct_texts,
        sum(source_posted_at_raw IS NOT NULL) with_source_posting_time
        FROM visible_overlay_records GROUP BY drama_id,episode_id ORDER BY drama_id''')
    summary={'coverage':'sampled_visible','native_messages_collected_by_this_mode':0,
        'records':sum(r['records'] for r in counts),'episodes':len(counts),
        'dramas':len({r['drama_id'] for r in counts}),
        'observations':db.db.execute('SELECT count(*) FROM visible_overlay_observations').fetchone()[0],
        'distinct_texts':db.db.execute('SELECT count(DISTINCT text) FROM visible_overlay_records').fetchone()[0],
        'per_episode':counts,'exported_at':utcnow(),
        'record_definition':'Unique render ID + text per episode/page session; not globally unique platform messages.',
        'timing':'Posting time is source create_time; playback position is observed, never a native offset.',
        'scope':'Only viewport-intersecting DOM nodes at sampled instants. Full node text may be partially clipped.'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary


def collect_visible_captures(dbpath,path,outdir):
    path=Path(path)
    paths=sorted(path.glob('*.capture.json')) if path.is_dir() else [path]
    if not paths: raise ValueError('No *.capture.json files found')
    with Store(dbpath) as db:
        runs=[import_capture(db,p) for p in paths]
        return {'imports':runs,**export_visible(db,outdir)}
