"""Optional visible-DOM danmaku sampling in a permitted browser session.

Captures only text visibly rendered on the page; never intercepts private APIs,
searches encrypted streams, or makes platform-native timestamp claims without an
explicit native timestamp attribute. Some sites render canvas-only comments;
those cannot be collected with CSS text selectors.
"""
from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse
from .network import PublicClient
from .storage import Store
from .util import utcnow, validate_public_http_url

LOG=logging.getLogger(__name__)


def is_generated_review_overlay(raw):
    """Observed Hongguo web renderer generates dm-init IDs from review indexes."""
    return any(str(raw.get(key) or '').startswith('dm-init-')
               for key in ('message_id','render_id','dom_id'))


def observe_danmaku(*,dbpath,drama_id,episode_id,url,selector,seconds=60,
                    video_selector='video',id_attribute='data-id',native_ms_attribute='',
                    allowed_hosts=(),user_data_dir=None,headless=False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError('Install optional browser dependencies: pip install -r requirements-browser.txt; python -m playwright install chromium') from e
    validate_public_http_url(url,set(allowed_hosts))
    # Only observe public/authorized pages; refuse pages blocked by robots.txt.
    checker=PublicClient(set(allowed_hosts),delay=2.0)
    checker._verify_robots(url)
    if not 1<=seconds<=3600: raise ValueError('Duration must be 1..3600 seconds')
    info={'attempted_seconds':seconds,'observed_unique':0,'timing_native':0,'timing_estimated':0,
          'rejected_review_overlays':0,
          'note':'Visible-DOM sample only. Not evidence of a complete historical danmaku pool.'}
    with Store(dbpath) as db:
        ep=db.db.execute('SELECT 1 FROM episodes WHERE drama_id=? AND episode_id=?',(drama_id,episode_id)).fetchone()
        if not ep: raise ValueError('Import the drama and episode IDs first')
        run=db.start('browser_observe_danmaku')
        try:
            with sync_playwright() as pw:
                if user_data_dir:
                    context=pw.chromium.launch_persistent_context(str(Path(user_data_dir).expanduser()),headless=headless)
                    browser=None
                else:
                    browser=pw.chromium.launch(headless=headless)
                    context=browser.new_context()
                page=context.new_page()
                page.goto(url,wait_until='domcontentloaded',timeout=60000)
                deadline=time.monotonic()+seconds
                seen=set()
                while time.monotonic()<deadline:
                    # Collect only currently rendered page text and attributes.
                    data=page.locator(selector).evaluate_all('''(els, opt) => els.map(el => ({
                      text: (el.textContent || '').trim(),
                      message_id: opt.idAttr ? el.getAttribute(opt.idAttr) : null,
                      render_id: el.getAttribute('data-danmaku-id'),
                      native_ms: opt.nativeAttr ? el.getAttribute(opt.nativeAttr) : null
                    }))''',{'idAttr':id_attribute,'nativeAttr':native_ms_attribute})
                    try:
                        current_ms=page.locator(video_selector).first.evaluate('(v)=> Math.max(0,Math.floor(v.currentTime*1000))')
                    except Exception:
                        current_ms=None
                    for raw in data:
                        if is_generated_review_overlay(raw):
                            info['rejected_review_overlays']+=1
                            continue
                        text=(raw.get('text') or '').strip()
                        if not text or len(text)>1000: continue
                        message_id=(raw.get('message_id') or '').strip() or None
                        native=raw.get('native_ms')
                        try:
                            native_ms=int(native) if native is not None and str(native).strip() else None
                        except (ValueError,TypeError):
                            native_ms=None
                        ms=native_ms if native_ms is not None else current_ms
                        timing='platform_native' if native_ms is not None else ('estimated_observation' if ms is not None else 'unknown')
                        # No ID: collapse repeated DOM visibility inside 5-second playback window.
                        seen_key=(message_id,) if message_id else (text,(ms//5000) if ms is not None else 'no_time')
                        if seen_key in seen: continue
                        seen.add(seen_key)
                        db.add_danmaku({'drama_id':drama_id,'episode_id':episode_id,'message_id':message_id,
                                        'text':text,'playback_time_ms':ms,'timing_method':timing,
                                        'captured_at':utcnow(),'source':'browser_visible_dom:'+urlparse(url).hostname,
                                        'coverage':'sampled_visible'})
                        info['observed_unique']+=1
                        info['timing_native' if timing=='platform_native' else 'timing_estimated']+=1
                    time.sleep(.5)
                context.close()
                if browser:browser.close()
            db.finish(run,'complete',**info)
        except Exception as exc:
            db.event(run,'error','browser_observation_failed',str(exc))
            db.finish(run,'failed',error=str(exc),**info)
            raise
    return info


def observe_comments(*,dbpath,drama_id,url,selector,episode_id=None,scrolls=5,
                     id_attribute='data-id',parent_attribute='data-parent-id',posted_attribute='data-posted-at',
                     likes_attribute='data-likes',allowed_hosts=(),user_data_dir=None,headless=False):
    """Collect visible comments only, optionally scrolling bounded number of times.

    Reply identity, posted time and likes remain NULL unless platform DOM exposes
    verified fields. Captures are intentionally marked sampled_visible.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError('Install requirements-browser.txt and Playwright chromium') from e
    validate_public_http_url(url,set(allowed_hosts))
    PublicClient(set(allowed_hosts),delay=2)._verify_robots(url)
    if not 0<=scrolls<=100:raise ValueError('scrolls must be 0..100')
    results={'seen_elements':0,'imported':0,'sampled_visible':True,
             'note':'Not a complete comment dataset; IDs and reply structure only when exposed in DOM.'}
    with Store(dbpath) as db:
        db.ensure_drama(drama_id)
        run=db.start('browser_observe_comments')
        try:
            with sync_playwright() as pw:
                if user_data_dir:
                    context=pw.chromium.launch_persistent_context(str(Path(user_data_dir).expanduser()),headless=headless)
                    browser=None
                else:
                    browser=pw.chromium.launch(headless=headless)
                    context=browser.new_context()
                page=context.new_page()
                page.goto(url,wait_until='domcontentloaded',timeout=60000)
                seen=set()
                for index in range(scrolls+1):
                    rows=page.locator(selector).evaluate_all('''(els, p)=>els.map(e=>({
                       text:(e.textContent||'').trim(),
                       comment_id:e.getAttribute(p.id),parent_id:e.getAttribute(p.parent),
                       posted_at:e.getAttribute(p.posted),like_count:e.getAttribute(p.likes)
                    }))''',{'id':id_attribute,'parent':parent_attribute,'posted':posted_attribute,'likes':likes_attribute})
                    for item in rows:
                        results['seen_elements']+=1
                        title=(item.get('text') or '').strip()
                        if not title or len(title)>10000:continue
                        key=(item.get('comment_id') or title)
                        if key in seen:continue
                        seen.add(key)
                        db.add_comment({**item,'drama_id':drama_id,'episode_id':episode_id,
                                        'source':'browser_visible_dom:'+urlparse(url).hostname,
                                        'coverage':'sampled_visible','captured_at':utcnow()})
                        results['imported']+=1
                    if index<scrolls:
                        page.evaluate('window.scrollBy(0, window.innerHeight)')
                        time.sleep(2)
                context.close()
                if browser:browser.close()
            db.finish(run,'complete',**results)
        except Exception as e:
            db.event(run,'error','browser_comments_failed',str(e))
            db.finish(run,'failed',error=str(e),**results)
            raise
    return results
