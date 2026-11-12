"""Evidence-backed report for the preserved, provisional research selection."""
import csv
import html
import json
import statistics
from collections import Counter
from pathlib import Path
from .storage import Store
from .engagement import latest_changes
from .util import utcnow


def write_csv(path,rows,fields=None):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or list(rows[0]) if rows else fields or [])
        writer.writeheader();writer.writerows(rows)


def write_research_report(dbpath,outdir):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    with Store(dbpath) as db:
        dramas=db.fetch("SELECT * FROM dramas WHERE drama_id NOT GLOB 'DEMO_*' ORDER BY drama_id")
        eps=db.fetch("SELECT * FROM episodes WHERE drama_id NOT GLOB 'DEMO_*' ORDER BY drama_id,episode_number")
        metrics=db.fetch("SELECT * FROM engagement_snapshots WHERE drama_id NOT GLOB 'DEMO_*' AND source NOT LIKE '%SYNTHETIC%' ORDER BY observed_at,id")
        comments=db.fetch("SELECT * FROM comments WHERE drama_id NOT GLOB 'DEMO_*' AND source NOT LIKE '%SYNTHETIC%'")
        native=db.fetch("SELECT * FROM danmaku WHERE drama_id NOT GLOB 'DEMO_*' AND source NOT LIKE '%SYNTHETIC%' AND timing_method='platform_native'")
        pages=db.fetch('SELECT * FROM public_page_snapshots ORDER BY collected_at')
        overlays=db.fetch('SELECT * FROM visible_overlay_records')
        sightings=db.fetch('SELECT count(*) n FROM visible_overlay_observations')[0]['n']
        events=db.fetch("SELECT * FROM collection_events WHERE level='error' ORDER BY id")
        reviews=db.fetch("SELECT * FROM drama_reviews WHERE drama_id NOT GLOB 'DEMO_*'")
        integrity=db.fetch('PRAGMA integrity_check');foreign_keys=db.fetch('PRAGMA foreign_key_check')
        assets=db.fetch("SELECT * FROM assets WHERE drama_id NOT GLOB 'DEMO_*'")
        native_attempts=db.fetch("SELECT * FROM collection_runs WHERE command='native_danmaku_probe' ORDER BY run_id")
        observation_count=db.fetch('SELECT count(*) n FROM comment_observations')[0]['n']
    latest={};expected={};latest_metrics={}
    for p in pages:
        p['payload']=json.loads(p['payload_json']);latest[(p['drama_id'],p['page_kind'])]=p
        if p['episode_id'] and p['payload'].get('media',{}).get('expected_duration_seconds'):
            expected[p['episode_id']]=(p['payload']['media']['expected_duration_seconds'],p['source_url'],p['collected_at'])
    for m in metrics:latest_metrics[(m['drama_id'],m['episode_id'],m['metric'],m['source'])]=m
    comparisons=[];episode_rows=[]
    for d in dramas:
        sid=d['drama_id'];catalog=latest.get((sid,'detail'),{}).get('payload',{}).get('catalog',{})
        stored=[e for e in eps if e['drama_id']==sid];fresh=catalog.get('episodes',[])
        ordering=[(e['episode_id'],e['episode_number']) for e in stored]
        fresh_order=[(e['episode_id'],e['episode_number']) for e in fresh]
        directory_ok=bool(catalog and ordering==fresh_order and len(stored)==catalog.get('episode_count') and
                          [e['episode_number'] for e in stored]==list(range(1,len(stored)+1)))
        first=stored[0]['episode_id'] if stored else None
        def metric(name,eid=None):
            candidates=[m for m in latest_metrics.values() if m['drama_id']==sid and m['episode_id']==eid and m['metric']==name]
            return candidates[-1]['value'] if candidates else None
        comparisons.append({'drama_id':sid,'title':d['title'],'url':d['url'],
            'synopsis':catalog.get('description',d['description']),'genre':catalog.get('genre',d['genre']),
            'platform_classification':catalog.get('platform_classification','unknown'),
            'classification_basis':'platform_category_not_human_review','completion_status':'unverified',
            'source_episode_status_json':json.dumps(catalog.get('source_episode_status'),ensure_ascii=False),
            'expected_episodes':catalog.get('episode_count',d['episode_count']),'listed_episodes':len(stored),
            'directory_status':'verified_complete' if directory_ok else 'unverified',
            'first_episode_id':first,'first_episode_expected_seconds':expected.get(first,(None,))[0],
            'first_episode_likes':metric('likes',first),'first_episode_comment_count':metric('comments',first),
            'drama_likes':metric('likes'),'drama_favorites':metric('favorites'),'drama_rating':metric('rating'),
            'drama_heat':metric('heat'),'drama_actual_views':metric('views'),
            'review_preview_rows':sum(c['drama_id']==sid and c['episode_id'] is None for c in comments),
            'episode_comment_preview_rows':sum(c['drama_id']==sid and c['episode_id'] is not None for c in comments),
            'human_review_status':'available' if any(r['drama_id']==sid for r in reviews) else 'pending',
            'model_prediction_status':'unavailable','facial_realism':'unverified','voice_quality':'unverified',
            'subtitle_language':'unverified','metadata_source':latest.get((sid,'detail'),{}).get('source_url'),
            'metadata_collected_at':latest.get((sid,'detail'),{}).get('collected_at')})
    verified=0
    for e in eps:
        exp=expected.get(e['episode_id'],(e.get('expected_duration_seconds'),e['source_url'],None))
        found=[a for a in assets if a['episode_id']==e['episode_id'] and a['kind']=='video' and a['verified_full']]
        # The report rechecks file existence, byte count and digest, never trusts a stale status alone.
        from .util import file_sha256
        valid=any(Path(a['local_path']).is_file() and Path(a['local_path']).stat().st_size==a['bytes']
                  and file_sha256(a['local_path'])==a['sha256'] for a in found)
        verified+=int(valid)
        episode_rows.append({'drama_id':e['drama_id'],'episode_id':e['episode_id'],'episode_number':e['episode_number'],
            'source_url':exp[1],'video_file_path':e['media_path'],'expected_duration_seconds':exp[0],
            'expected_duration_source_collected_at':exp[2],'actual_duration_seconds':e.get('media_duration_seconds'),
            'file_size':e['media_bytes'],'sha256':e['media_sha256'],'download_status':e['media_status'],
            'completeness_status':'verified_complete' if valid else 'unverified','collected_at':e['checked_at'],
            'subtitle_status':e['subtitle_status'],'native_records_stored':sum(n['episode_id']==e['episode_id'] for n in native)})
    changes=latest_changes(metrics)
    counts={'dramas':len(dramas),'expected_episode_count':sum(d['episode_count'] or 0 for d in dramas),
        'episode_ids':len(eps),'verified_complete_video_files':verified,'episodes_without_verified_full_video':len(eps)-verified,
        'truncated_or_preview_files':sum(e.get('duration_validation')=='mismatch' for e in eps),
        'corrupted_file_count':None,'native_danmaku_records':len(native),'native_successful_live_pages':sum(
            json.loads(r['detail_json'] or '{}').get('result',{}).get('pages',0) for r in native_attempts),
        'visible_overlay_records':len(overlays),'visible_overlay_sightings':sightings,
        'episode_comments':sum(c['episode_id'] is not None for c in comments),
        'drama_reviews':sum(c['episode_id'] is None for c in comments),
        'replies_with_source_parent_id':sum(bool(c['parent_id']) for c in comments),
        'comment_observations':observation_count,'engagement_observations':len(metrics),
        'episode_metric_observations':sum(m['scope']=='episode' for m in metrics),
        'episodes_with_metrics':len({m['episode_id'] for m in metrics if m['scope']=='episode'}),
        'episodes_with_source_duration':len(expected),'comparable_24h_metric_pairs':len(changes),
        'public_page_snapshots':len(pages),'catalogs_reconciled':sum(c['directory_status']=='verified_complete' for c in comparisons)}
    requirements=[
        (1,'Actual-view top 10','BLOCKED','unavailable','Public charts provide heat/rank, not verified drama views. Current selection remains provisional.'),
        (2,'Complete authorized videos','BLOCKED','unavailable',f'{verified}/{len(eps)} verified full videos. Normal player media download failed; no authorized direct-file export supplied.'),
        (3,'Native timed danmaku','BLOCKED','unavailable',f'{len(native)} records. Unsigned probes returned application error 110001. Repository signing/impersonation paths excluded.'),
        (4,'Episode metrics and 24h follow-up','PARTIAL','verified_partial',f"Likes/comment counts on {counts['episodes_with_metrics']} episodes; {len(changes)} comparable 24h pairs. Other episode metrics unavailable."),
        (5,'Comments, reviews, replies','PARTIAL','verified_partial',f"{counts['episode_comments']} episode comments + {counts['drama_reviews']} drama reviews; preview only, no source IDs or reply relationships. Full comments hand off to app."),
        (6,'Complete catalog','PARTIAL','verified_partial',f"{counts['catalogs_reconciled']}/{len(dramas)} directories reconcile with fresh source ordering. Completion enum and independent classification remain unverified."),
        (7,'Cross-drama analysis','PARTIAL','verified_partial','Source classifications, counts, first-episode duration and engagement compared. Human face/voice/subtitle review and native temporal analysis pending.'),
        (8,'Quality report','PASS','verified_complete','Generated from SQLite, source evidence, file checks and collection logs; missing data and legacy demo rows explicitly separated.'),
        (9,'Scaling benchmark','PARTIAL','verified_partial','Public-page timings/bytes and episode mean measured. Full-video, danmaku, GPU and monetary costs are assumptions or unmeasured.')]
    requirement_rows=[dict(zip(('requirement','name','acceptance','status','evidence'),r)) for r in requirements]
    mean_eps=len(eps)/len(dramas) if dramas else 0
    total_bytes=sum(p['response_bytes'] for p in pages);elapsed=sum(p['elapsed_seconds'] for p in pages)
    mean_comment_bytes=statistics.mean(len(json.dumps(c,ensure_ascii=False).encode()) for c in comments) if comments else None
    scale=[]
    for target in (10,100,1000):
        episodes=round(target*mean_eps);gb=episodes*.03
        scale.append({'dramas':target,'episodes_using_measured_mean':episodes,
            'assumed_video_storage_GB_at_30_MB_per_episode':gb,'assumed_transfer_hours_at_20_Mbps':round(gb*8000/20/3600,2),
            'public_preview_requests_assuming_same_scope':4+2*target,
            'all_episode_requests_hypothetical_if_authorized':4+target+episodes,
            'assumed_transcription_GPU_hours_at_90_seconds_and_half_realtime':round(episodes*90/3600*.5,2),
            'assumed_frame_analysis_CPU_hours_at_90_seconds_and_realtime':round(episodes*90/3600,2),
            'estimated_database_bytes_linear_from_pilot':round(Path(dbpath).stat().st_size*target/max(len(dramas),1)),
            'native_danmaku_bytes':None,'estimated_currency_cost':None})
    quality={'generated_at':utcnow(),'status':'verified_partial','database':str(Path(dbpath).resolve()),'counts':counts,
        'requirements':requirement_rows,'selection':'provisional_hot_ranking_not_top_actual_views',
        'classification_counts':dict(Counter(c['platform_classification'] for c in comparisons)),
        'metric_coverage':dict(Counter(m['scope']+':'+m['metric'] for m in metrics)),
        'changes_24h':changes,'failed_request_events':events,'native_probe_runs':native_attempts,
        'integrity_check':integrity,'foreign_key_violations':foreign_keys,
        'evidence':[{'path':p['evidence_path'],'sha256':p['evidence_sha256'],'source_url':p['source_url'],
                     'collected_at':p['collected_at']} for p in pages],
        'limitations':['Excludes DEMO_* and SYNTHETIC sources; original rows remain in the database.',
            'No native records collected does not establish an empty platform pool.',
            'Preview deduplication without source IDs uses text/posting time/scope; identical real comments may collapse.',
            'Public first-episode sampling does not cover all 2,826 episodes; nested player URLs are disallowed by current robots policy.',
            'Raw native posting times are preserved without assuming seconds/milliseconds or timezone.',
            'Historical native completeness and real-time delivery have not been demonstrated.',
            'Zero verified media means corruption/preview coverage is unassessed, not that all videos are healthy.']}
    benchmark={'measured':{'mean_episodes_per_drama':mean_eps,'public_pages':len(pages),'response_bytes':total_bytes,
        'summed_page_fetch_seconds_including_rate_waits':elapsed,'mean_seconds_per_page':elapsed/len(pages) if pages else None,
        'average_serialized_comment_row_bytes':mean_comment_bytes,'database_file_bytes':Path(dbpath).stat().st_size,
        'mean_video_bytes':None,'video_throughput_Mbps':None,'native_rows_per_episode':None},
        'assumptions':{'video_MB_per_episode':30,'network_Mbps':20,'episode_seconds_for_compute':90,
                       'transcription_GPU_realtime_factor':.5,'frame_analysis_CPU_realtime_factor':1},
        'cost_formula':'storage_GB * quoted_GB_month_rate + transfer_GB * quoted_egress_rate + GPU_hours * quoted_GPU_hour_rate + CPU_hours * quoted_CPU_hour_rate',
        'cost_status':'unmeasured; no provider quote or GPU pilot','estimates':scale,
        'architecture':'Keep immutable hashed evidence in object storage, idempotent workers, per-episode tasks and transactional checkpoints. SQLite suits one pilot writer; use a shared transactional database before multiple writers. Centralize per-host rate limits and honor access denials. Native scans must revisit old playback offsets for late posts.',
        'risks':['Source permission is the gating constraint; extrapolated requests do not imply authorization.',
                 'Pilot includes one rejected identity followed by a successful resume; errors and robots overhead are not included in successful-page byte averages.',
                 'Sample is selected by heat and has a 1,000-episode outlier; mean is not representative of the whole catalog.',
                 'Linear DB estimate includes legacy/demo overhead; native pool size is unknown.']}
    for name,data in [('quality_report.json',quality),('scaling.json',benchmark)]:
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    for name,rows in [('acceptance.csv',requirement_rows),('drama_comparison.csv',comparisons),('episode_inventory.csv',episode_rows),('scaling.csv',scale)]:write_csv(out/name,rows)
    write_csv(out/'real_comments.csv',comments)
    write_csv(out/'real_engagement.csv',metrics)
    write_csv(out/'native_danmaku.csv',native,fields=['drama_id','episode_id','message_id','text','playback_time_ms','posted_at','captured_at','source','coverage','raw_json','source_url','offset_source','posting_time_raw_json','identity_basis','last_seen_at','dedup_key','timing_method'])
    # Standalone local report generated by the crawler; no scripts, network or external assets.
    esc=lambda x:html.escape(str(x))
    def table(rows,fields):
        return '<table><thead><tr>'+''.join('<th>'+esc(k)+'</th>' for k in fields)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(r.get(k,''))+'</td>' for k in fields)+'</tr>' for r in rows)+'</tbody></table>'
    bars=''.join('<div class="bar"><label>'+esc(c['title'])+'</label><span style="width:'+str(c['listed_episodes']/max(len(eps),1)*100)+'%"></span><b>'+str(c['listed_episodes'])+'</b></div>' for c in comparisons)
    report='<!doctype html><meta charset="utf-8"><title>Hongguo research evidence</title><style>body{font:15px system-ui;max-width:1250px;margin:40px auto;padding:0 24px;color:#18212b;background:#fafafa}h1{font-size:32px}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{padding:10px;border:1px solid #ccd2d8;text-align:left;vertical-align:top}.bar{display:flex;gap:12px;align-items:center;height:35px}.bar label{width:350px}.bar span{background:#396b80;height:16px}.note{color:#45515e}</style>'
    report+='<h1>Hongguo research: verified partial collection</h1><p>Generated '+esc(quality['generated_at'])+'</p><p><strong>Native danmaku: '+str(len(native))+' · Verified full videos: '+str(verified)+'</strong></p><p>Comments and scrolling review overlays are separate datasets. This selection is not verified as the most-viewed top 10.</p>'
    report+=table([{'measure':k,'value':v} for k,v in counts.items()],['measure','value'])
    report+='<h2>Requirement acceptance</h2>'+table(requirement_rows,['requirement','name','acceptance','status','evidence'])
    report+='<h2>Episode catalog by drama</h2><p>Horizontal length: episode count; rows: dramas. Source: reconciled public directory snapshots, '+esc(min((p['collected_at'] for p in pages),default=''))+' to '+esc(max((p['collected_at'] for p in pages),default=''))+'.</p>'+bars
    report+='<h2>Cross-drama comparison</h2>'+table(comparisons,['title','platform_classification','listed_episodes','directory_status','first_episode_expected_seconds','first_episode_likes','drama_rating','human_review_status'])
    report+='<p class="note">Durations and likes refer only to each first episode. Classification is a platform category, not an independent face or voice assessment. Rating is drama-scoped.</p>'
    report+='<h2>Scaling scenarios — assumptions, not a media benchmark</h2>'+table(scale,list(scale[0]))
    report+='<h2>Limitations</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in quality['limitations'])+'</ul>'
    (out/'report.html').write_text(report)
    return {'status':'verified_partial','counts':counts,'output':str(out)}
