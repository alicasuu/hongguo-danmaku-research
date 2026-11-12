"""Reproducible coverage, quality flags, 24h deltas and scaling estimates."""
from __future__ import annotations
import json
import math
import statistics
from pathlib import Path
from datetime import datetime,timezone
from .storage import Store
from .util import utcnow


def report_data(db: Store):
    dramas=db.fetch('SELECT * FROM dramas ORDER BY discovered_at,drama_id')
    out={'generated_at':utcnow(),'database':str(db.path),'counts':{},'dramas':[], 'quality_flags':[], 'snapshot_changes':[], 'ranking_changes':[],
         'collection_failures':[],'interpretation':{'ranking':'Rank heat is a composite score, not verified view counts',
          'danmaku':'Ordinary comments are not danmaku; browser-visible captures are samples, not complete historical pools',
          'media':'verified_full requires human-supplied expected duration + full decode + ffprobe + full declaration; still requires checking the source export',
          'independence':'Unknown/unavailable data is not treated as zero'}}
    for t in ('dramas','episodes','danmaku','comments','ranking_snapshots','engagement_snapshots','assets','drama_reviews'):
        out['counts'][t]=db.count(t)
    for d in dramas:
        sid=d['drama_id']
        eps=db.fetch('SELECT episode_id,episode_number,media_status,completeness,subtitle_status FROM episodes WHERE drama_id=? ORDER BY episode_number',(sid,))
        dan=db.fetch('''SELECT COUNT(*) AS n,SUM(CASE WHEN playback_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS timed,
            SUM(CASE WHEN timing_method='platform_native' AND playback_time_ms IS NOT NULL THEN 1 ELSE 0 END) AS native FROM danmaku WHERE drama_id=?''',(sid,))[0]
        comment_n=db.db.execute('SELECT COUNT(*) FROM comments WHERE drama_id=?',(sid,)).fetchone()[0]
        expected=d['episode_count']
        ep_n=len(eps)
        verified=sum(e['completeness']=='verified_full' for e in eps)
        media_n=sum(e['media_status']=='valid_video' for e in eps)
        subtitles=sum(e['subtitle_status']=='available' for e in eps)
        entry={'drama_id':sid,'title':d['title'],'expected_episodes':expected,'episode_ids':ep_n,
               'episode_id_coverage':round(ep_n/expected,4) if expected else None,
               'videos_valid':media_n,'videos_full_verified':verified,'subtitle_files':subtitles,
               'danmaku_messages':dan['n'] or 0,'danmaku_timed':dan['timed'] or 0,
               'danmaku_native_timestamps':dan['native'] or 0,'comments':comment_n,
               'missing_episode_ids':max(0,expected-ep_n) if expected else None}
        out['dramas'].append(entry)
        if not expected: out['quality_flags'].append(f'{sid}: total episode count unknown')
        elif ep_n<expected: out['quality_flags'].append(f'{sid}: {ep_n}/{expected} episode IDs; incomplete directory')
        if verified<ep_n: out['quality_flags'].append(f'{sid}: {verified}/{ep_n} listed episodes have verified-full media')
        if not dan['n']: out['quality_flags'].append(f'{sid}: no authentic timed danmaku collected')
        elif not dan['native']: out['quality_flags'].append(f'{sid}: danmaku have no platform-native time evidence')
    # Latest observation versus the closest comparable observation around 24 hours earlier.
    from .engagement import latest_changes
    metric_rows=db.fetch('SELECT * FROM engagement_snapshots WHERE value IS NOT NULL')
    out['snapshot_changes']=latest_changes(metric_rows)
    rank_rows=db.fetch('SELECT drama_id,rank_type,rank,heat_value,observed_at FROM ranking_snapshots ORDER BY observed_at')
    rank_by={}
    for row in rank_rows:rank_by.setdefault((row['drama_id'],row['rank_type']),[]).append(row)
    for (sid,rank_type),xs in rank_by.items():
        paired=None
        for i,a in enumerate(xs):
            for b in xs[i+1:]:
                try:
                    start=datetime.fromisoformat(a['observed_at'].replace('Z','+00:00'))
                    end=datetime.fromisoformat(b['observed_at'].replace('Z','+00:00'))
                    diff=(end-start).total_seconds()/3600
                except (ValueError,TypeError): continue
                if 20<=diff<=30:
                    paired={'drama_id':sid,'rank_type':rank_type,'hours':round(diff,2),
                       'old_rank':a['rank'],'new_rank':b['rank'],
                       'rank_improvement':(a['rank']-b['rank']) if a['rank'] is not None and b['rank'] is not None else None,
                       'old_heat':a['heat_value'],'new_heat':b['heat_value'],
                       'heat_delta':b['heat_value']-a['heat_value'] if a['heat_value'] is not None and b['heat_value'] is not None else None}
                    break
            if paired: break
        if paired:out['ranking_changes'].append(paired)
    out['collection_failures']=db.fetch("SELECT happened_at,entity_type,entity_id,code,detail FROM collection_events WHERE level='error' ORDER BY id DESC LIMIT 50")
    out['non_demo_counts']={}
    for table in ('dramas','episodes','danmaku','comments','engagement_snapshots','assets'):
        extra=" AND source NOT LIKE '%SYNTHETIC%'" if table in ('danmaku','comments','engagement_snapshots') else ''
        out['non_demo_counts'][table]=db.db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE drama_id NOT GLOB 'DEMO_*'"+extra).fetchone()[0]
    out['demo_data_present']=any(d['drama_id'].startswith('DEMO_') for d in dramas)
    out['counts']['videos_verified_full']=sum(e['videos_full_verified'] for e in out['dramas'])
    out['counts']['videos_valid']=sum(e['videos_valid'] for e in out['dramas'])
    out['counts']['danmaku_native_timestamps']=sum(e['danmaku_native_timestamps'] for e in out['dramas'])
    return out


def scale_estimate(db,targets=(10,100,1000),assumed_episodes_per_drama=80,
                   assumed_mb_per_episode=30,available_mbps=20):
    files=db.fetch("SELECT bytes,observed_duration_seconds FROM assets WHERE kind='video' AND bytes>0")
    eps=db.fetch('SELECT episode_count FROM dramas WHERE episode_count IS NOT NULL AND episode_count>0')
    if db.db.execute("SELECT COUNT(*) FROM dramas WHERE drama_id NOT GLOB 'DEMO_*'").fetchone()[0]:
        files=db.fetch("SELECT bytes,observed_duration_seconds FROM assets WHERE kind='video' AND bytes>0 AND drama_id NOT GLOB 'DEMO_*'")
        eps=db.fetch("SELECT episode_count FROM dramas WHERE episode_count>0 AND drama_id NOT GLOB 'DEMO_*'")
    median_episodes=statistics.median([x['episode_count'] for x in eps]) if eps else assumed_episodes_per_drama
    median_bytes=statistics.median([x['bytes'] for x in files]) if files else assumed_mb_per_episode*1_000_000
    durations=[v['observed_duration_seconds'] for v in files if v.get('observed_duration_seconds')]
    median_duration=statistics.median(durations) if durations else 90.0
    estimates=[]
    for dramas in targets:
        num_episodes=int(math.ceil(dramas*median_episodes))
        total_bytes=num_episodes*median_bytes
        gb=total_bytes/1e9
        hours=(total_bytes*8)/(available_mbps*1e6)/3600 if available_mbps>0 else None
        estimates.append({'dramas':dramas,'estimated_episodes':num_episodes,'storage_GB_decimal':round(gb,2),
                          'minimum_transfer_hours_at_assumed_Mbps':round(hours,2) if hours is not None else None,
                          'assumed_transcription_compute_hours_at_0_5x_realtime':round(num_episodes*median_duration/3600*0.5,2),
                          'assumed_ocr_compute_hours_at_1x_realtime':round(num_episodes*median_duration/3600,2)})
    return {'data_source_episode_count':'pilot_median' if eps else 'assumption',
            'data_source_video_size':'pilot_median' if files else 'assumption',
            'median_episodes_per_drama':median_episodes,'median_video_MB':round(median_bytes/1e6,2),
            'median_episode_duration_seconds':median_duration,'compute_ratios_assumed':{'transcription':0.5,'OCR':1.0},
            'assumed_network_Mbps':available_mbps,'note':'Optimistic lower bound excluding retries, transcription, crawler delay, comments, storage redundancy and permission limits.',
            'estimates':estimates}


def write_reports(dbpath,outdir,**est_kwargs):
    outdir=Path(outdir)
    outdir.mkdir(parents=True,exist_ok=True)
    with Store(dbpath) as db:
        data=report_data(db)
        budget=scale_estimate(db,**est_kwargs)
        has_demo=any('SYNTHETIC_FIXTURE' in str(x) for x in db.fetch("SELECT source FROM danmaku UNION SELECT source FROM comments"))
    (outdir/'coverage_report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (outdir/'scale_estimate.json').write_text(json.dumps(budget,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Micro-drama pilot — automated collection report',
           f"Generated (UTC): {data['generated_at']}",'',
           '**Mixed database: demo rows are preserved and appear in raw totals below.**' if data['demo_data_present'] else '',
           'Non-demo stored records: '+json.dumps(data['non_demo_counts'],ensure_ascii=False),
           'Non-demo filtering excludes labeled fixtures; it does not independently certify every source.',
           '', '## Stored items (raw database totals, including demos)',
           '| Measure | Count |','|---|---:|']
    for k,v in data['counts'].items():lines.append(f'| {k} | {v} |')
    lines += ['','## Per-drama coverage',
            '| Drama | IDs / expected | Valid videos | Verified full | Native timed danmaku | Comments |',
            '|---|---:|---:|---:|---:|---:|']
    for d in data['dramas']:
        lines.append(f"| {d['title'].replace('|','/')} | {d['episode_ids']}/{d['expected_episodes'] if d['expected_episodes'] is not None else '?'} | {d['videos_valid']} | {d['videos_full_verified']} | {d['danmaku_native_timestamps']} | {d['comments']} |")
    lines += ['', '## 20–30 hour engagement changes']
    if not data['snapshot_changes']:
        lines.append('No comparable repeat observations yet. Re-run collection/import after approximately 24 hours.')
    else:
        for v in data['snapshot_changes'][:30]:
            lines.append(f"- {v['drama_id']} / {v['episode_id'] or 'whole drama'} / {v['metric']}: {v['before']} → {v['after']} (Δ {v['delta']:+g}, {v['hours']}h)")
    if has_demo:
        lines += ['','**DEMO / SYNTHETIC DATA PRESENT — counts are not real collected Hongguo observations.**']
    lines += ['','## 20–30 hour ranking changes']
    if not data['ranking_changes']:
        lines.append('No rank pairs observed approximately 24 hours apart.')
    else:
        for x in data['ranking_changes'][:30]:
            lines.append(f"- {x['drama_id']} ({x['rank_type']}): rank {x['old_rank']} → {x['new_rank']}; heat Δ {x['heat_delta']}")
    lines += ['','## Data quality / missing data']
    lines += ['- '+flag for flag in data['quality_flags']] or ['- No flags.']
    lines += ['','## Scaling projections (assumption-based until pilot videos exist)',
              '| Dramas | Episodes | Storage (GB) | Ideal network transfer (hours) | ASR compute (hours)* | OCR compute (hours)* |',
              '|---:|---:|---:|---:|---:|---:|']
    for x in budget['estimates']:
        lines.append(f"| {x['dramas']} | {x['estimated_episodes']} | {x['storage_GB_decimal']} | {x['minimum_transfer_hours_at_assumed_Mbps']} | {x['assumed_transcription_compute_hours_at_0_5x_realtime']} | {x['assumed_ocr_compute_hours_at_1x_realtime']} |")
    lines += ['','*ASR/OCR speeds are hypothetical engineering assumptions, not benchmarked performance.*','', '## Critical interpretation rules',
              '- Ranking **heat** is a composite score, not confirmed playback count.',
              '- Text comments **must not** be counted as playback-timed danmaku.',
              '- Browser-visible danmaku is sampled/partial, not the complete historical pool.',
              '- Only rights-confirmed videos with duration checks can be technically labeled verified_full.',
              '- Estimates do not include rights/availability bottlenecks.']
    (outdir/'weekly_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return data,budget
