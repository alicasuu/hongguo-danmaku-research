"""Strict research acceptance audit. Missing data remain missing; receipts are source ATTESTATIONS.

Passing a check is not proof a third-party platform actually supplied complete data:
source completeness and rights must be verified independently by the research team.
"""
from __future__ import annotations
import json
import csv
from pathlib import Path
from datetime import datetime
from .storage import Store
from .util import utcnow

CORE_METRICS=('likes','favorites','comments','rating','heat','rank')
OPTIONAL_METRICS=('views','shares')


def _time(s):
    try:
        d=datetime.fromisoformat(str(s).replace('Z','+00:00'))
        return d if d.tzinfo else None
    except (ValueError,TypeError):
        return None


def _pair24(records):
    records=sorted(records,key=lambda r:r.get('observed_at') or '')
    for i,a in enumerate(records):
        t=_time(a.get('observed_at'))
        if not t:continue
        for b in records[i+1:]:
            u=_time(b.get('observed_at'))
            if u and 20 <= (u-t).total_seconds()/3600 <= 30:
                return [a,b]
    return None


def _receipt_status(receipts,kind,episode_id=None):
    rows=[r for r in receipts if r['data_kind']==kind and r['episode_id']==episode_id]
    full=[r for r in rows if r['coverage']=='full_source_attested']
    return {'attempts':len(rows),'source_attested_full':bool(full),
            'latest_status':rows[-1]['coverage'] if rows else 'missing',
            'any_source_evidence':bool([r for r in rows if r['source_url'] or r['evidence_file']]),
            'recheck_24h':bool(_pair24(rows))}


def audit_data(db:Store,top=10,selection_file=None):
    dramas=db.fetch('SELECT * FROM dramas ORDER BY discovered_at, drama_id')
    by_id={d['drama_id']:d for d in dramas}
    info={'generated_at':utcnow(),'status':'INCOMPLETE','requested_dramas':top,
          'eligible_titles':[],'selection':{},'dramas':[], 'summary':{}, 'limitations':[
           'Availability of real downloads and platform-native danmaku is not verified by this audit',
           'A source receipt is a research-team attestation, NOT independently validated platform coverage',
           'Official worldwide Top-10 cannot be proven from 10 records alone; source candidate-universe audit is required',
           'One or two snapshots do not establish a live polling process or completeness of historical messages']}
    sel=None
    if selection_file:
        sel=json.loads(Path(selection_file).read_text(encoding='utf-8'))
        ids=sel.get('ordered_drama_ids')
        if not isinstance(ids,list) or len(ids)!=top or len(set(map(str,ids)))!=top:
            raise ValueError(f'selection requires exactly {top} unique ordered_drama_ids')
        ids=list(map(str,ids))
        for k in ('source_url','observed_at','criteria','candidate_population_size','population_scope','verified_by'):
            if not sel.get(k):raise ValueError('Selection missing required provenance field '+k)
        if sel['criteria']!='drama_level_actual_views':
            raise ValueError('Top selection criteria must be drama_level_actual_views, not heat or popularity')
    else:
        views=db.fetch('''SELECT e.drama_id,MAX(e.value) AS views FROM engagement_snapshots e
                WHERE e.metric='views' AND e.scope='drama' AND e.episode_id IS NULL
                AND e.value IS NOT NULL GROUP BY e.drama_id ORDER BY views DESC LIMIT ?''',(top,))
        ids=[x['drama_id'] for x in views]
    info['eligible_titles']=ids
    sources_ok=bool(sel and len(ids)==top and
         sel.get('candidate_population_size',0)>=top and sel.get('covers_entire_target_population') is True)
    observed_views={}
    if ids:
        placeholders=','.join('?' for _ in ids)
        v=db.fetch(f'''SELECT drama_id, source, precision, raw_value, value, observed_at FROM engagement_snapshots
            WHERE scope='drama' AND metric='views' AND episode_id IS NULL AND value IS NOT NULL
            AND drama_id IN ({placeholders}) ORDER BY observed_at DESC''',tuple(ids))
        for r in v:observed_views.setdefault(r['drama_id'],r)
    # A ranking is evidence-backed only if all 10 have actual view data and known population scope.
    view_values=[]
    for sid in ids:
        row=observed_views.get(sid)
        if row:view_values.append(row['value'])
    sorted_desc=len(view_values)==top and view_values==sorted(view_values,reverse=True)
    source_names={observed_views[sid]['source'] for sid in ids if sid in observed_views}
    same_source=len(source_names)==1 and len(view_values)==top
    observation_times=[_time(observed_views[sid]['observed_at']) for sid in ids if sid in observed_views]
    same_window=(len(observation_times)==top and all(observation_times) and
                 (max(observation_times)-min(observation_times)).total_seconds() <= 86400)
    source_evidence=bool(sources_ok and sorted_desc and same_source and same_window
                         and all(sid in by_id for sid in ids))
    info['selection']={'selection_manifest_given':bool(sel),'population_scope_attested':sources_ok,
                       'all_have_drama_level_actual_views':len(view_values)==top,
                       'sorted_by_actual_views':sorted_desc,'view_source_consistent':same_source,
                       'views_observed_within_24h':same_window,'source_attested_top10':source_evidence,
                       'source_url':sel.get('source_url') if sel else None,
                       'population_scope':sel.get('population_scope') if sel else None,
                       'candidate_population_size':sel.get('candidate_population_size') if sel else None,
                       'note':'Source-attested, not independently confirmed by the software.'}
    for sid in ids:
        if sid not in by_id:
            info['dramas'].append({'drama_id':sid,'status':'MISSING_METADATA','failures':['drama absent from database']})
            continue
        d=by_id[sid]
        eps=db.fetch('SELECT * FROM episodes WHERE drama_id=? ORDER BY episode_number',(sid,))
        metrics=db.fetch('SELECT * FROM engagement_snapshots WHERE drama_id=? ORDER BY observed_at',(sid,))
        rec=db.fetch('SELECT * FROM source_receipts WHERE drama_id=? ORDER BY observed_at',(sid,))
        reviews=db.fetch('SELECT * FROM drama_reviews WHERE drama_id=?',(sid,))
        cm=db.fetch('SELECT episode_id,COUNT(*) n, SUM(CASE WHEN parent_id IS NOT NULL AND TRIM(parent_id)<>\'\' THEN 1 ELSE 0 END) replies FROM comments WHERE drama_id=? GROUP BY episode_id',(sid,))
        comments={x['episode_id']:x for x in cm}
        dan=db.fetch('''SELECT episode_id,COUNT(*) n,
            SUM(CASE WHEN timing_method='platform_native' AND playback_time_ms IS NOT NULL THEN 1 ELSE 0 END) native_timed,
            SUM(CASE WHEN timing_method!='platform_native' OR playback_time_ms IS NULL THEN 1 ELSE 0 END) unverified
            FROM danmaku WHERE drama_id=? GROUP BY episode_id''',(sid,))
        danmaku={x['episode_id']:x for x in dan}
        expected=d['episode_count']
        numbers=[x['episode_number'] for x in eps]
        contiguous=bool(expected and len(eps)==expected and sorted(numbers)==list(range(1,expected+1)))
        failures=[]
        for f in ('title','url','genre','description','status','episode_count'):
            if not d.get(f) or d[f]=='unknown':failures.append('missing_drama_'+f)
        if not d.get('ai_classification') or d['ai_classification']=='unknown':failures.append('missing_ai_classification')
        if not contiguous:failures.append('episode_directory_not_complete')
        # Review required even when drama has an AI-labelled category; labels alone do not validate visual realism.
        if not reviews:failures.append('no_AI_live_action_voice_subtitle_human_likeness_review')
        per=[]
        for ep in eps:
            eid=ep['episode_id']; n=ep['episode_number']; faults=[]
            if not(ep['media_status']=='valid_video' and ep['completeness']=='verified_full' and ep['media_sha256']):
                faults.append('full_video_not_verified')
            if ep['duration_seconds'] is None:faults.append('reference_duration_missing')
            if ep['subtitle_status']=='missing':faults.append('subtitles_not_obtained_or_availability_unchecked')
            dmx=danmaku.get(eid,{}); dr=_receipt_status(rec,'danmaku',eid)
            native=int(dmx.get('native_timed') or 0)
            # Zero-message episodes are valid only when source metadata verifies a complete empty pool.
            if not dr['source_attested_full'] or (native==0 and not any(
                    x['data_kind']=='danmaku' and x['episode_id']==eid and x['coverage']=='full_source_attested'
                    and x['reported_total']==0 for x in rec)):
                faults.append('native_full_danmaku_pool_not_source_attested')
            if not dr['recheck_24h']:faults.append('no_danmaku_24h_recheck_receipts')
            cr=_receipt_status(rec,'comments',eid)
            rr=_receipt_status(rec,'replies',eid)
            if not cr['source_attested_full']:faults.append('episode_comments_completeness_unverified')
            if not rr['source_attested_full']:faults.append('episode_replies_completeness_unverified')
            metric_state={}
            for met in CORE_METRICS+OPTIONAL_METRICS:
                xs=[m for m in metrics if m['scope']=='episode' and m['episode_id']==eid and m['metric']==met and m['value'] is not None]
                # Do not pair different sources
                pairs=[]
                for src in {r['source'] for r in xs}:
                    p=_pair24([r for r in xs if r['source']==src])
                    if p:pairs.append({'source':src,'hours':round((_time(p[1]['observed_at'])-_time(p[0]['observed_at'])).total_seconds()/3600,2)})
                metric_state[met]={'observations':len(xs),'two_snapshots_20_30h':bool(pairs),'pairs':pairs}
                if met in CORE_METRICS and not pairs:
                    faults.append('missing_24h_episode_metric_'+met)
            # Optional metrics must be sourced when provider actually exposes them; receipt records where unavailable.
            for met in OPTIONAL_METRICS:
                if not metric_state[met]['two_snapshots_20_30h']:
                    receipt=_receipt_status(rec,'engagement',eid)
                    if receipt['latest_status']=='missing':faults.append('optional_'+met+'_availability_unknown')
            per.append({'episode_id':eid,'episode_number':n,'failures':faults,
                        'verified_video':ep['completeness']=='verified_full' and ep['media_status']=='valid_video',
                        'authentic_timed_danmaku_count':native,'danmaku_source_evidence':dr,
                        'comments_count':int(comments.get(eid,{}).get('n') or 0),
                        'replies_count':int(comments.get(eid,{}).get('replies') or 0),
                        'episode_metrics':metric_state})
        if not eps:failures.append('no_episode_rows')
        if any(x['failures'] for x in per):failures.append('one_or_more_episodes_incomplete')
        info['dramas'].append({'drama_id':sid,'title':d['title'],'expected_episodes':expected,
             'catalogue_contiguous':contiguous,'collected_episodes':len(eps),
             'total_authentic_timed_danmaku':sum(x['authentic_timed_danmaku_count'] for x in per),
             'complete_videos':sum(x['verified_video'] for x in per),'errors':failures,
             'episodes':per,'status':'SOURCE_ATTESTED_COMPLETE' if not failures else 'INCOMPLETE'})
    info['summary']={'titles_selected':len(ids),'titles_in_db':sum(x.get('title') is not None for x in info['dramas']),
                     'episodes_listed':sum(x.get('collected_episodes',0) for x in info['dramas']),
                     'videos_verified_full':sum(x.get('complete_videos',0) for x in info['dramas']),
                     'platform_native_timed_danmaku':sum(x.get('total_authentic_timed_danmaku',0) for x in info['dramas']),
                     'episodes_with_complete_attested_collection':sum(not x['failures'] for d in info['dramas'] for x in d.get('episodes',[])),
                     'titles_with_all_episode_gates':sum(x['status']=='SOURCE_ATTESTED_COMPLETE' for x in info['dramas'])}
    if source_evidence and len(info['dramas'])==top and all(x['status']=='SOURCE_ATTESTED_COMPLETE' for x in info['dramas']):
        info['status']='SOURCE_ATTESTED_COMPLETE_NOT_INDEPENDENTLY_VERIFIED'
    return info


def write_acceptance(dbpath,outdir,selection_file=None,top=10):
    p=Path(outdir);p.mkdir(parents=True,exist_ok=True)
    with Store(dbpath) as db: data=audit_data(db,top=top,selection_file=selection_file)
    (p/'acceptance.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for d in data['dramas']:
        for e in d.get('episodes',[]):
            rows.append({'drama_id':d['drama_id'],'title':d.get('title',''), 'episode_id':e['episode_id'],
                         'episode_number':e['episode_number'],'full_video':e['verified_video'],
                         'native_timed_danmaku':e['authentic_timed_danmaku_count'],
                         'danmaku_full_source_attested':e['danmaku_source_evidence']['source_attested_full'],
                         'danmaku_24h_rechecked':e['danmaku_source_evidence']['recheck_24h'],
                         'comments_count':e['comments_count'],'replies_count':e['replies_count'],
                         'missing_24h_metrics':'; '.join(k for k,v in e['episode_metrics'].items() if not v['two_snapshots_20_30h']),
                         'failure_count':len(e['failures']),'failures':'; '.join(e['failures'])})
    if rows:
        with (p/'episode_acceptance.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    lines=['# Hongguo acceptance audit','',f"Status: **{data['status']}**",'',
           '## Counts','']+[f'- {k}: {v}' for k,v in data['summary'].items()]
    lines+=['','## Selection verification',f"- Top-10 actual-view source attested: {data['selection']['source_attested_top10']}",
            '- Composite heat is never used as actual views.','', '## Unmet requirements']
    if not data['dramas']:lines.append('- No dramas with actual-view evidence available.')
    for d in data['dramas']:
        lines.append(f"- **{d.get('title',d['drama_id'])}**: {', '.join(d.get('errors',d.get('failures',[]))) or 'top-level checks satisfied'}")
        for e in d.get('episodes',[]):
            if e['failures']:lines.append(f"  - Episode {e['episode_number']}: {', '.join(e['failures'])}")
    lines+=['','## Evidence limitations']+['- '+x for x in data['limitations']]
    (p/'acceptance.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'status':data['status'],'summary':data['summary'],'output_dir':str(p),'files':['acceptance.json','acceptance.md','episode_acceptance.csv' if rows else '(no episode CSV yet)']}
