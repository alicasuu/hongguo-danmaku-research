"""Select 10 most-viewed only when a source supplies ACTUAL view observations."""
from __future__ import annotations
import csv
from pathlib import Path
from .storage import Store


def select_top_by_views(dbpath,out_path,limit=10):
    with Store(dbpath) as db:
        # Latest for each drama/source, but only actual view metrics. Never rank by heat.
        data=db.fetch('''SELECT e.drama_id, d.title, e.value AS views,e.raw_value,e.source,e.precision,e.observed_at
            FROM engagement_snapshots e JOIN dramas d ON d.drama_id=e.drama_id
            WHERE e.scope='drama' AND e.metric='views' AND e.value IS NOT NULL
              AND e.episode_id IS NULL
              AND e.id=(SELECT e2.id FROM engagement_snapshots e2
                WHERE e2.drama_id=e.drama_id AND e2.scope='drama' AND e2.metric='views'
                  AND e2.source=e.source AND e2.episode_id IS NULL
                ORDER BY e2.observed_at DESC,e2.id DESC LIMIT 1)
            ORDER BY e.value DESC''')
    dedup={}
    for d in data:
        dedup.setdefault(d['drama_id'],d)
    ranked=list(dedup.values())[:limit]
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    with Path(out_path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['rank','drama_id','title','views','raw_value','source','precision','observed_at'])
        w.writeheader()
        for n,row in enumerate(ranked,1):
            w.writerow({'rank':n,**row})
    return {'available_with_actual_view_metrics':len(data),'selected':len(ranked),'requested':limit,
            'complete_target':len(ranked)==limit,'path':str(out_path),
            'warning':None if len(ranked)==limit else 'Fewer than requested have actual source-tagged drama-level view counts; do not relabel composite heat as views.'}
