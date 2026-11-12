"""Episode-level snapshots: source/precision aware, missing is never zero."""
from __future__ import annotations
import csv
import json
from datetime import datetime
from pathlib import Path
from .storage import Store
from .util import utcnow

METRICS = ('views','likes','favorites','comments','shares','rating','heat','rank')


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return dt if dt.tzinfo is not None else None
    except ValueError:
        return None


def latest_changes(rows):
    groups={}
    for row in rows:
        if row.get('value') is None or timestamp(row.get('observed_at')) is None:
            continue
        key=tuple(row.get(k) for k in ('drama_id','episode_id','scope','metric','source','precision'))
        groups.setdefault(key,[]).append(row)
    changes=[]
    for records in groups.values():
        after=max(records,key=lambda r:timestamp(r['observed_at']))
        options=[]
        for before in records:
            hours=(timestamp(after['observed_at'])-timestamp(before['observed_at'])).total_seconds()/3600
            if 20<=hours<=30: options.append((abs(hours-24),hours,before))
        if not options: continue
        _,hours,before=min(options,key=lambda x:x[0])
        delta=after['value']-before['value']
        changes.append({**{k:after.get(k) for k in ('drama_id','episode_id','scope','metric','source','precision')},
                        'before':before['value'],'after':after['value'],'before_at':before['observed_at'],
                        'after_at':after['observed_at'],'hours':round(hours,2),'delta':delta,
                        'relative_pct':round(100*delta/before['value'],2) if before['value'] else None,
                        'counter_decreased':delta<0})
    return changes


def write_episode_status(dbpath, outdir):
    """Every non-demo episode appears even when no source supplies its metrics."""
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    with Store(dbpath) as db:
        eps=db.fetch("SELECT * FROM episodes WHERE drama_id NOT GLOB 'DEMO_*' ORDER BY drama_id,episode_number")
        metrics=db.fetch("SELECT * FROM engagement_snapshots WHERE scope='episode' AND drama_id NOT GLOB 'DEMO_*' AND source NOT LIKE '%SYNTHETIC%' ORDER BY observed_at,id")
        latest={}
        for row in metrics:
            if timestamp(row['observed_at']) is None:continue
            key=(row['episode_id'],row['metric'],row['source'],row['precision'])
            if key not in latest or timestamp(row['observed_at'])>=timestamp(latest[key]['observed_at']):
                latest[key]=row
        snapshots=list(latest.values())
        changes=latest_changes(metrics)
        counts={r['episode_id']:r['n'] for r in db.fetch("SELECT episode_id,COUNT(*) n FROM danmaku WHERE timing_method='platform_native' AND playback_time_ms IS NOT NULL AND message_id IS NOT NULL AND source NOT LIKE '%SYNTHETIC%' GROUP BY episode_id")}
    rows=[]
    for ep in eps:
        present={r['metric'] for r in snapshots if r['episode_id']==ep['episode_id'] and r['value'] is not None}
        row={k:ep[k] for k in ('drama_id','episode_id','episode_number','duration_seconds','media_duration_seconds','expected_duration_seconds','duration_validation','media_status','completeness')}
        row['native_messages_stored']=counts.get(ep['episode_id'],0)
        for metric in METRICS:row[metric+'_availability']='observed' if metric in present else 'unknown'
        row['comparable_24h_metrics']=sum(c['episode_id']==ep['episode_id'] for c in changes)
        rows.append(row)
    if rows:
        with (out/'episode_status.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    result={'generated_at':utcnow(),'episodes':len(eps),'episode_metric_observations':len(metrics),
            'episodes_with_metrics':len({x['episode_id'] for x in snapshots if x['value'] is not None}),
            'latest_by_source':snapshots,'changes_24h':changes,
            'note':'Unknown means no observation; stored-message counts do not measure the platform pool.'}
    (out/'episode_engagement.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'episodes':len(eps),'episode_metric_observations':len(metrics),
            'changes_24h':len(changes),'out':str(out)}
