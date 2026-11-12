"""Public rank / detail collection with durable checkpoints in SQLite."""
from __future__ import annotations
import logging
from pathlib import Path
from .network import PublicClient
from .parsing import BASE, RANKS, parse_rank, parse_detail
from .storage import Store
from .util import utcnow

LOG=logging.getLogger(__name__)


def collect_public(dbpath, *, top=10, ranking='hot-drama', delay=2.0, skip_details=False,
                   local_rank_html=None, details_directory=None, user_agent=None):
    if not 1 <= top <= 1000:
        raise ValueError('--top must be between 1 and 1000')
    if ranking not in RANKS:
        raise ValueError(f'Unsupported ranking: {ranking}')
    rank_url = f'{BASE}/rank/{ranking}'
    client = PublicClient({'hongguoduanju.com'},delay=delay,**({'user_agent':user_agent} if user_agent else {}))
    report = {'rank_type':ranking, 'requested_top':top, 'found':0, 'detail_success':0,
              'episode_ids_found':0, 'errors':[], 'ranking_is_views':False,
              'verified_full_videos':0, 'danmaku':0, 'sample_limit_warning':top>20}
    with Store(dbpath) as db:
        run = db.start('crawl_public')
        try:
            if local_rank_html:
                html = Path(local_rank_html).read_text(encoding='utf-8')
                rank_url = 'offline_fixture:' + str(local_rank_html)
            else:
                html = client.get_html(rank_url)
            dramas = parse_rank(html, top)
            if not dramas:
                raise ValueError('No rank data found. Site structure or public access may have changed; no fake rows written.')
            if len(dramas)<top:
                report['errors'].append(f'Rank page has only {len(dramas)} readable entries; pagination not assumed.')
            report['found'] = len(dramas)
            for d in dramas:
                d['rank_source']=ranking
                if ranking=='hot-ai-drama': d['ai_classification']='ai_category'
                db.upsert_drama(d, 'public_rank')
                db.add_rank(d,ranking,rank_url)
                if skip_details:
                    continue
                sid = d['drama_id']
                try:
                    if details_directory:
                        path = Path(details_directory) / (sid+'.html')
                        if not path.exists():
                            db.event(run, 'warning','detail_fixture_not_found',str(path),'drama',sid)
                            report['errors'].append(f'{sid}: no offline detail fixture')
                            continue
                        detail_html=path.read_text(encoding='utf-8')
                    elif local_rank_html:
                        # Offline collection never unexpectedly calls network.
                        report['errors'].append(f'{sid}: details omitted in offline mode; pass --details-dir')
                        continue
                    else:
                        detail_html=client.get_html(d['url'])
                    detail = parse_detail(detail_html)
                    if not detail:
                        raise ValueError('Could not find verified seriesDetail fields')
                    for key in ('genre','description','episode_count','creator','status'):
                        if not detail.get(key): detail[key]=d.get(key)
                    detail['rank_source']=ranking
                    db.upsert_drama(detail,'public_detail')
                    for ep in detail['episodes']:
                        ep['drama_id']=sid
                        db.upsert_episode(ep)
                        report['episode_ids_found'] += 1
                    if detail.get('episode_count') and len(detail['episodes']) < int(detail['episode_count']):
                        db.event(run,'warning','partial_episode_directory',
                                 f"Exposed {len(detail['episodes'])}/{detail['episode_count']} episode IDs",'drama',sid)
                    report['detail_success'] += 1
                except Exception as e:
                    report['errors'].append(f'{sid}: {e}')
                    db.event(run,'error','detail_collection_failed',repr(e),'drama',sid)
                    LOG.warning('%s details unavailable: %s',sid,e)
            db.finish(run,'partial' if report['errors'] else 'complete',**report)
        except Exception as e:
            db.event(run,'error','crawl_failed',repr(e))
            db.finish(run,'failed',error=str(e))
            raise
    return report
