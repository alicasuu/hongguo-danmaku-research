"""Live collector for permitted public pages, never app/private endpoints.

Preserves the existing selection. Only website-supplied previews are collected;
the full-comment app handoff is not followed. Sanitized page evidence excludes
request context, account/user profiles, signed poster URLs and protected media.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
from datetime import datetime,timezone
from pathlib import Path
from bs4 import BeautifulSoup
from .network import PublicClient
from .parsing import BASE,parse_embedded_objects,recursive_find,parse_detail,parse_rank
from .storage import Store
from .util import utcnow,json_str,stable_hash,file_sha256,metric_number

SOURCE='hongguo_public_ssr_v1'


def number(raw):
    if type(raw) in (int,float) or isinstance(raw,str) and re.fullmatch(r'\d+(\.\d+)?',raw):
        value=float(raw)
        if value>=0 and value<float('inf'):return value
    return None


def extract_page(html,url,kind,sid=None):
    objects=parse_embedded_objects(html)
    def find(key):
        for obj in objects:
            value=recursive_find(obj,key)
            if value is not None:return value
        return None
    if kind=='ranking':
        rows=parse_rank(html,1000)
        if not rows:raise ValueError('Public ranking schema unavailable')
        return {'rank_type':url.rsplit('/',1)[-1],'ranking_metric':'composite_heat_not_verified_views',
                'rankings':rows,'pagination_links':sorted({BASE+a['href'] for a in BeautifulSoup(html,'html.parser').select('a[href]')
                    if a['href'].startswith('/rank/') and '?page=' in a['href']})}
    detail=parse_detail(html)
    if not detail or detail['drama_id']!=sid:raise ValueError('Public page drama identity mismatch')
    raw=find('seriesDetail') or {}
    details={k:detail.get(k) for k in ('drama_id','title','url','genre','description','episode_count','episodes')}
    details['source_episode_status']=raw.get('series_episode_info')
    details['accessible_episode_count']=raw.get('accessible_episode_cnt')
    details['completion_status']='unverified'  # Numeric source enum has not been independently documented.
    soup=BeautifulSoup(html,'html.parser')
    badges=[a.get_text(' ',strip=True) for a in soup.select('a[href]')
            if a['href'].startswith('/rank/hot-') and a.get_text(strip=True)]
    details['platform_category_badges']=badges
    details['classification_basis']='platform_category_not_human_review'
    details['platform_classification']=('AI' if any('AI剧' in b for b in badges) else
        'live_action' if any('真人剧' in b for b in badges) else
        'comic' if any('漫剧' in b for b in badges) else 'unknown')
    social=find('episodeSocialInfo' if kind=='player' else 'seriesSocialInfo')
    if not isinstance(social,dict):raise ValueError('Social data schema missing; not a zero-count observation')
    episode=detail['episodes'][0]['episode_id'] if kind=='player' and detail['episodes'] else None
    seo=find('publicVideoSeo') or {}
    if kind=='player' and seo.get('itemId') and str(seo['itemId'])!=episode:
        raise ValueError('Media episode identity conflicts with directory')
    metrics=[]
    def metric(name,raw_value,scope='drama',precision='source_numeric_unspecified'):
        value=number(raw_value)
        if value is not None:metrics.append({'metric':name,'value':value,'raw_value':raw_value,'scope':scope,
            'episode_id':episode if scope=='episode' else None,'precision':precision})
    if kind=='player':
        metric('likes',social.get('episode_like_count'),'episode','source_reported_integer')
        metric('comments',(social.get('reviews') or {}).get('total_count'),'episode','source_reported_integer')
        # Series favorites are intentionally NOT copied to the episode scope.
    else:
        for name,key in [('likes','series_like_count'),('favorites','series_favorite_count'),('rating','rating')]:metric(name,social.get(key))
        metric('comments',(social.get('reviews') or {}).get('total_count'))
        metric('heat',(social.get('hot_score_data') or {}).get('score'))
        label=social.get('rank_label')
        details['source_rank_label']=label
        if isinstance(label,str) and 'AI剧' in label:details['platform_classification']='AI'
        elif isinstance(label,str) and '真人剧' in label:details['platform_classification']='live_action'
        elif isinstance(label,str) and '漫剧' in label:details['platform_classification']='comic'
    group=social.get('reviews')
    if not isinstance(group,dict) or not isinstance(group.get('reviews'),list):
        raise ValueError('Review list schema missing; not an empty pool')
    reviews=[]
    for index,r in enumerate(group['reviews']):
        if not isinstance(r,dict) or not isinstance(r.get('content'),str) or not r['content'].strip():
            raise ValueError('Invalid review row')
        # Explicit allowlist; no user/account metadata retained.
        reviews.append({k:r.get(k) for k in ('content','create_time','digg_count','rating','comment_id','parent_id') if k in r})
        reviews[-1]['source_index']=index
    return {'catalog':details,'episode_id':episode,'metrics':metrics,'reviews':reviews,
            'review_record_type':'episode_comment_preview' if episode else 'drama_review_preview',
            'reported_review_total':group.get('total_count'),'review_field_names':sorted({k for r in group['reviews'] for k in r}),
            'pagination':{'status':'unavailable','reason':'Only embedded preview; full-comment UI hands off to app',
                          'exposed_cursor_keys':[k for k in group if k not in ('reviews','total_count')]},
            'media':{'metadata_available':bool(seo.get('available')),'expected_duration_seconds':seo.get('durationSeconds'),
                     'width':seo.get('width'),'height':seo.get('height'),
                     'direct_file_url_exposed':False,'protected_playback_flag':find('protectedPlayback') is True},
            'views_status':'unavailable','native_danmaku_status':'unavailable',
            'coverage_status':'verified_partial'}


def import_page(db,evidence_path):
    path=Path(evidence_path).resolve();e=json.loads(path.read_text());digest=file_sha256(path)
    if db.fetch('SELECT 1 FROM public_page_snapshots WHERE evidence_sha256=?',(digest,)):return {'new_comments':0,'new_metrics':0,'replayed':True}
    p=e['payload'];sid=e.get('drama_id');kind=e['page_kind'];eid=p.get('episode_id');now=e['collected_at'];url=e['source_url']
    if sid:db.ensure_drama(sid)
    if eid and not db.fetch('SELECT 1 FROM episodes WHERE drama_id=? AND episode_id=?',(sid,eid)):
        raise ValueError('Episode not present in preserved catalog')
    # Store the sanitized immutable source even if later row ingestion fails.
    # Mark ingested only after all normalized writes; partial attempts can replay.
    result={'new_comments':0,'new_metrics':0,'replayed':False}
    for r in p.get('metrics',[]):
        result['new_metrics']+=int(db.add_metric({**r,'drama_id':sid,'source':SOURCE+':'+kind,
            'source_url':url,'observed_at':now,'collected_at':now,'coverage_status':'verified_partial'}))
    if kind=='ranking':
        known={r['drama_id'] for r in db.fetch("SELECT drama_id FROM dramas WHERE drama_id NOT GLOB 'DEMO_*'")}
        for d in p['rankings']:
            if d['drama_id'] not in known:continue
            # Preserve the project's selection rather than replacing it with today's chart.
            db.add_rank({**d,**{k:'' for k in ('likes_label','favorites_label','rating_label','comments_label','shares_label')}},
                        p['rank_type'],url,observed_at=now,collected_at=now)
            result['new_metrics']+=int(db.add_metric({'drama_id':d['drama_id'],'scope':'drama','metric':'rank',
                'value':d['rank'],'precision':'source_rank_position','source':SOURCE+':'+p['rank_type'],
                'source_url':url,'observed_at':now,'collected_at':now,'coverage_status':'verified_partial'}))
    with db.db:
        db.db.execute('INSERT INTO public_page_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',
            (digest,url,kind,sid,eid,now,str(path),json_str(p),e['response_bytes'],e['elapsed_seconds']))
        for r in p.get('reviews',[]):
            posted=None
            if r.get('create_time') is not None:
                raw=str(r['create_time'])
                if not re.fullmatch(r'\d+',raw):raise ValueError('Invalid source posting time')
                posted=datetime.fromtimestamp(int(raw),timezone.utc).isoformat()
            source=SOURCE+':'+p['review_record_type'];mid=r.get('comment_id');parent=r.get('parent_id')
            if mid is not None and (not isinstance(mid,str) or mid.startswith('dm-init-')):
                raise ValueError('Invalid native comment ID')
            key=stable_hash(source,eid or sid,mid) if mid else stable_hash(source,eid or sid,r['content'],posted,parent)
            likes=number(r.get('digg_count'))
            added=db.db.execute('''INSERT OR IGNORE INTO comments(dedup_key,drama_id,episode_id,comment_id,parent_id,
                text,posted_at,like_count,captured_at,source,coverage,raw_json,record_type,source_url)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(key,sid,eid,mid,parent,r['content'],posted,likes,now,
                source,'partial',json_str(r),p['review_record_type'],url)).rowcount
            result['new_comments']+=added
            db.db.execute('INSERT OR IGNORE INTO comment_observations VALUES(?,?,?,?,?,?)',
                (stable_hash(digest,r['source_index']),key,now,likes,r['source_index'],digest))
    if sid:
        db.add_receipt({'drama_id':sid,'episode_id':eid,'data_kind':'comments','source':SOURCE+':'+p['review_record_type'],
            'source_url':url,'coverage':'partial','rows_seen':len(p['reviews']),'reported_total':p['reported_review_total'],
            'observed_at':now,'rights_basis':'Public page preview requested for research','evidence_file':str(path),
            'note':'Not full history; no reply relationship inferred. IDs remain NULL when absent.'})
    return result


def collect_research(dbpath,outdir,*,drama_id=None,resume=False,delay=2,client=None):
    out=Path(outdir).resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=out/'checkpoint.json'
    if manifest.exists() and not resume:raise ValueError('Use a new output directory for a new snapshot, or --resume')
    state=json.loads(manifest.read_text()) if manifest.exists() else {'started_at':utcnow(),'pages':{},'failures':[]}
    client=client or PublicClient({'hongguoduanju.com'},delay=delay)
    with Store(dbpath) as db:
        selected=[r['drama_id'] for r in db.fetch("SELECT drama_id FROM dramas WHERE drama_id NOT GLOB 'DEMO_*' ORDER BY drama_id")]
        if drama_id:
            if drama_id not in selected:raise ValueError('Drama is not in the existing research selection')
            selected=[drama_id]
        jobs=[('ranking',None,BASE+'/rank/'+rank) for rank in ('hot-drama','hot-ai-drama','hot-real-drama','hot-comic-drama')]
        jobs += [(kind,sid,BASE+('/detail?series_id=' if kind=='detail' else '/player/')+sid) for sid in selected for kind in ('detail','player')]
        run=db.start('public_research_snapshot');result={'run_id':run,'pages_collected':0,'pages_replayed':0,'new_comments':0,'new_metrics':0,'failures':[],'status':'verified_partial'}
        for kind,sid,url in jobs:
            try:
                cached=state['pages'].get(url)
                if cached:
                    path=out/cached['file']
                    if not path.is_file() or file_sha256(path)!=cached['sha256']:raise ValueError('Checkpoint evidence missing or changed')
                    result['pages_replayed']+=1
                else:
                    started=time.monotonic();html=client.get_html(url);elapsed=time.monotonic()-started
                    payload=extract_page(html,url,kind,sid)
                    e={'source_url':url,'page_kind':kind,'drama_id':sid,'collected_at':utcnow(),'payload':payload,
                       'response_sha256':hashlib.sha256(html.encode()).hexdigest(),'response_bytes':len(html.encode()),'elapsed_seconds':round(elapsed,4)}
                    path=out/(stable_hash(url)[:20]+'.page.json')
                    path.write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n')
                    state['pages'][url]={'file':path.name,'sha256':file_sha256(path)}
                    manifest.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
                    result['pages_collected']+=1
                imported=import_page(db,path)
                for key in ('new_comments','new_metrics'):result[key]+=imported[key]
            except Exception as exc:
                failure={'url':url,'error_type':type(exc).__name__,'message':str(exc)[:300]}
                result['failures'].append(failure);state['failures'].append(failure)
                db.event(run,'error','public_research_page_failed',json_str(failure),'drama',sid or '')
            manifest.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
        result['finished_at']=utcnow()
        if result['failures']:result['status']='failed' if not result['pages_collected'] and not result['pages_replayed'] else 'verified_partial'
        db.finish(run,'failed' if result['status']=='failed' else 'partial',result=result)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
