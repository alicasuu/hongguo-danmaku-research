"""python -m hongguo --help"""
from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
from .collect import collect_public
from .storage import Store
from .ingest import ingest
from .media import import_media_manifest, import_subtitle_manifest, make_contact_sheet
from .browser import observe_danmaku,observe_comments
from .report import write_reports
from .select import select_top_by_views


def build_parser():
    p=argparse.ArgumentParser(prog='python -m hongguo',description='Reproducible micro-drama research data collector. Public pages and authorized exports only.')
    p.add_argument('--db',default='data/hongguo.sqlite',help='Persistent SQLite location (default data/hongguo.sqlite)')
    p.add_argument('--verbose',action='store_true')
    sub=p.add_subparsers(dest='command',required=True)
    qr=sub.add_parser('research-report',help='Generate evidence-backed acceptance, comparison and scaling reports excluding demos')
    qr.add_argument('--out',default='output/research_completion/report')
    es=sub.add_parser('episode-status',help='Export non-demo episode coverage and source-consistent latest engagement')
    es.add_argument('--out',default='output/episode_status')
    pr=sub.add_parser('research-snapshot',help='Collect public metadata, review previews and scoped metrics for the preserved selection')
    pr.add_argument('--out',required=True,help='New directory per collection time')
    pr.add_argument('--drama-id')
    pr.add_argument('--resume',action='store_true')
    pr.add_argument('--delay',type=float,default=2)
    vo=sub.add_parser('visible-overlays',help='Import connected-browser visible overlay samples, separate from native danmaku')
    vo.add_argument('capture',type=Path,help='Capture JSON or directory of *.capture.json files')
    vo.add_argument('--out',default='output/visible_overlays/csv')
    n=sub.add_parser('native-danmaku',help='Native raw-response import; live collection requires a connected permitted transport (no unsigned fallback)')
    n.add_argument('--drama-id',required=True)
    n.add_argument('--episode-id',required=True)
    n.add_argument('--out',default='output/native_danmaku')
    n.add_argument('--max-pages',type=int,default=1)
    n.add_argument('--retries',type=int,default=2,help='Transient network/5xx retries only; 0..5')
    n.add_argument('--resume',action='store_true',help='Continue a live scan from the last committed page')
    n.add_argument('--duration-ms',type=int,default=0,help='Known source duration only; zero means unknown')
    n.add_argument('--capture',type=Path,help='Authorized native request/response JSON envelope; offline')
    n.add_argument('--access-basis',default='public unsigned availability probe')
    n.add_argument('--host',choices=['api5-normal-sinfonlinea.fqnovel.com','api5-normal-sinfonlineb.fqnovel.com'],default='api5-normal-sinfonlinea.fqnovel.com')
    c=sub.add_parser('crawl',help='Collect public chart / detail metadata; never equate heat with views')
    c.add_argument('--top',type=int,default=10)
    c.add_argument('--rank',default='hot-drama',choices=['hot-drama','hot-real-drama','hot-ai-drama','hot-comic-drama'])
    c.add_argument('--delay',type=float,default=2)
    c.add_argument('--skip-details',action='store_true')
    c.add_argument('--offline-rank-html',type=Path,help='Use local fixture / saved HTML without network')
    c.add_argument('--details-dir',type=Path,help='Offline detail HTML named <drama_id>.html')
    c.add_argument('--contact',default='',help='Optional email in research user-agent')
    i=sub.add_parser('import',help='Ingest authorized CSV/JSON/JSONL provider exports with provenance')
    i.add_argument('kind',choices=['dramas','episodes','danmaku','comments','engagement','reviews','receipts'])
    i.add_argument('path',type=Path)
    i.add_argument('--source',default='authorized_export')
    i.add_argument('--coverage',default='partial',choices=['partial','sampled_visible','full_claimed','unknown'])
    i.add_argument('--strict',action='store_true')
    m=sub.add_parser('media-import',help='Validate rights-confirmed full video & subtitle files')
    m.add_argument('manifest',type=Path)
    m.add_argument('--media-root',default='data/media')
    m.add_argument('--download-authorized',action='store_true',help='Only direct HTTPS files with explicit research rights')
    m.add_argument('--allowed-host',action='append',default=[],help='Required allowlist for direct file downloads; repeat flag')
    m.add_argument('--max-video-gb',type=float,default=2.0)
    m.add_argument('--resume-transfers',action='store_true',help='Retain validated HTTP Range checkpoints for authorized direct files')
    ss=sub.add_parser('subtitle-import',help='Ingest authorized subtitle-only CSV manifest, even when video is unavailable')
    ss.add_argument('manifest',type=Path)
    ss.add_argument('--out',default='data/subtitles')
    b=sub.add_parser('browser-danmaku',help='Optional time-bounded visible-DOM danmaku observation')
    b.add_argument('--url',required=True)
    b.add_argument('--drama-id',required=True)
    b.add_argument('--episode-id',required=True)
    b.add_argument('--selector',required=True,help='CSS selector for visible danmaku messages; site-specific')
    b.add_argument('--video-selector',default='video')
    b.add_argument('--message-id-attr',default='data-id')
    b.add_argument('--native-ms-attr',default='',help='Use only if verified to contain PLATFORM playback milliseconds')
    b.add_argument('--allowed-host',action='append',required=True)
    b.add_argument('--seconds',type=int,default=60)
    b.add_argument('--profile-dir',type=Path,help='Locally owned browser profile; never exported in ZIP')
    b.add_argument('--headless',action='store_true')
    bc=sub.add_parser('browser-comments',help='Optional bounded visible-DOM comment/reply sampling')
    bc.add_argument('--url',required=True)
    bc.add_argument('--drama-id',required=True)
    bc.add_argument('--episode-id')
    bc.add_argument('--selector',required=True)
    bc.add_argument('--allowed-host',action='append',required=True)
    bc.add_argument('--scrolls',type=int,default=5)
    bc.add_argument('--profile-dir',type=Path)
    bc.add_argument('--headless',action='store_true')
    f=sub.add_parser('frames',help='Sample video frames for manual AI/subtitle/completeness review')
    f.add_argument('video_path',type=Path)
    f.add_argument('--out',type=Path,default=Path('data/frame_review'))
    f.add_argument('--count',type=int,default=4)
    e=sub.add_parser('export',help='Export all normalized SQLite tables as CSV')
    e.add_argument('--out',default='output/csv')
    r=sub.add_parser('report',help='Write Markdown/JSON coverage + 24-hour changes + 10/100/1000 projections')
    r.add_argument('--out',default='output/reports')
    r.add_argument('--assumed-episodes',type=int,default=80)
    r.add_argument('--assumed-mb',type=float,default=30)
    r.add_argument('--download-mbps',type=float,default=20)
    t=sub.add_parser('select-top-views',help='Rank only dramas with actual observed drama-level view metrics')
    t.add_argument('--top',type=int,default=10)
    t.add_argument('--out',default='output/top_by_verified_views.csv')
    si=sub.add_parser('sync-inbox',help='Incrementally import authorized provider CSV/JSON exports')
    si.add_argument('--inbox',default='data/inbox')
    si.add_argument('--watch',action='store_true',help='Keep running; watches local authorized exports only')
    si.add_argument('--interval',type=int,default=300,help='Seconds between folder scans; min 30')
    a=sub.add_parser('audit',help='Strict evidence-based requirement-by-requirement readiness audit')
    a.add_argument('--selection',type=Path,help='Audited JSON file documenting actual-views top-10 selection and source population')
    a.add_argument('--out',default='output/audit')
    a.add_argument('--top',type=int,default=10)
    d=sub.add_parser('demo',help='Load labeled synthetic test fixtures; never real scraped results')
    d.add_argument('--fixtures-dir',default='examples')
    d.add_argument('--out',default='output/demo')
    return p


def main():
    args=build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,format='%(levelname)s %(message)s')
    dbpath=args.db
    if args.command=='research-report':
        from .research_report import write_research_report
        result=write_research_report(dbpath,args.out)
    elif args.command=='episode-status':
        from .engagement import write_episode_status
        result=write_episode_status(dbpath,args.out)
    elif args.command=='research-snapshot':
        from .public_research import collect_research
        result=collect_research(dbpath,args.out,drama_id=args.drama_id,resume=args.resume,delay=args.delay)
    elif args.command=='visible-overlays':
        from .visible_overlays import collect_visible_captures
        result=collect_visible_captures(dbpath,args.capture,args.out)
    elif args.command=='native-danmaku':
        from .native import collect_native
        result=collect_native(dbpath,drama_id=args.drama_id,episode_id=args.episode_id,
                              outdir=args.out,max_pages=args.max_pages,duration_ms=args.duration_ms,
                              capture=args.capture,access_basis=args.access_basis,retries=args.retries,resume=args.resume,host=args.host)
    elif args.command=='crawl':
        ua='AcademicMicroDramaCollector/1.0 (public-page academic research'+('; contact: '+args.contact if args.contact else '')+')'
        result=collect_public(dbpath,top=args.top,ranking=args.rank,delay=args.delay,
              skip_details=args.skip_details,local_rank_html=args.offline_rank_html,
              details_directory=args.details_dir,user_agent=ua)
    elif args.command=='import':
        result=ingest(args.path,args.kind,dbpath,source=args.source,default_coverage=args.coverage,strict=args.strict)
    elif args.command=='media-import':
        result=import_media_manifest(args.manifest,dbpath,media_root=args.media_root,
              download_authorized=args.download_authorized,allowed_hosts=args.allowed_host,
              max_bytes=int(args.max_video_gb*1e9),resume_transfers=args.resume_transfers)
    elif args.command=='subtitle-import':
        result=import_subtitle_manifest(args.manifest,dbpath,subtitle_root=args.out)
    elif args.command=='browser-danmaku':
        result=observe_danmaku(dbpath=dbpath,drama_id=args.drama_id,episode_id=args.episode_id,
              url=args.url,selector=args.selector,seconds=args.seconds,video_selector=args.video_selector,
              id_attribute=args.message_id_attr,native_ms_attribute=args.native_ms_attr,
              allowed_hosts=args.allowed_host,user_data_dir=args.profile_dir,headless=args.headless)
    elif args.command=='browser-comments':
        result=observe_comments(dbpath=dbpath,url=args.url,drama_id=args.drama_id,
              episode_id=args.episode_id,selector=args.selector,scrolls=args.scrolls,
              allowed_hosts=args.allowed_host,user_data_dir=args.profile_dir,headless=args.headless)
    elif args.command=='frames':
        if args.count<1 or args.count>20:raise ValueError('--count must be 1..20')
        result={'frames':make_contact_sheet(args.video_path,args.out,n=args.count)}
    elif args.command=='export':
        with Store(dbpath) as db:
            result={'path':str(db.export_csv(args.out)),'counts':{t:db.count(t) for t in ('dramas','episodes','danmaku','comments','assets')}}
    elif args.command=='report':
        data,budget=write_reports(dbpath,args.out,assumed_episodes_per_drama=args.assumed_episodes,
                                  assumed_mb_per_episode=args.assumed_mb,available_mbps=args.download_mbps)
        result={'report_dir':args.out,'counts':data['counts'],'quality_flags':len(data['quality_flags']),
                'non_demo_counts':data['non_demo_counts'],'demo_data_present':data['demo_data_present'],
                '24h_changes':len(data['snapshot_changes']),'estimates':budget['estimates']}
    elif args.command=='select-top-views':
        result=select_top_by_views(dbpath,args.out,limit=args.top)
    elif args.command=='sync-inbox':
        from .inbox import sync_inbox
        result=sync_inbox(dbpath,args.inbox,watch=args.watch,interval_seconds=args.interval)
    elif args.command=='audit':
        from .acceptance import write_acceptance
        result=write_acceptance(dbpath,args.out,selection_file=args.selection,top=args.top)
    elif args.command=='demo':
        path=Path(args.fixtures_dir)
        result={'crawl':collect_public(dbpath,top=2,local_rank_html=path/'rank.html',details_directory=path/'details')}
        for kind,filename in [('danmaku','danmaku.jsonl'),('comments','comments.csv'),('engagement','engagement.jsonl')]:
            result[kind]=ingest(path/filename,kind,dbpath,source='SYNTHETIC_FIXTURE',default_coverage='sampled_visible')
        data,budget=write_reports(dbpath,args.out)
        result['counts']=data['counts']
        result['warning']='DEMO USES SYNTHETIC DATA, NOT ACTUAL HONGGUO COLLECTION'
    else:
        raise ValueError(args.command)
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    if result.get('status') in {'blocked','partial_failed'}:
        raise SystemExit(2)

if __name__=='__main__':
    main()
