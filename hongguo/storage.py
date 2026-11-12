"""Auditable SQLite store; no fabricated rows for missing content."""
from __future__ import annotations
import csv
import json
import sqlite3
from pathlib import Path
from .util import json_str, stable_hash, utcnow, metric_number

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS dramas (
 drama_id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT, genre TEXT, ai_classification TEXT DEFAULT 'unknown',
 description TEXT, status TEXT DEFAULT 'unknown', episode_count INTEGER, creator TEXT, rank_source TEXT,
 discovered_at TEXT NOT NULL, last_seen TEXT NOT NULL, source TEXT, extra_json TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
 episode_id TEXT PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), episode_number INTEGER,
 duration_seconds REAL, source_url TEXT, media_path TEXT, media_status TEXT DEFAULT 'missing',
 completeness TEXT DEFAULT 'unverified', subtitles_path TEXT, subtitle_status TEXT DEFAULT 'missing',
 media_sha256 TEXT, media_bytes INTEGER, checked_at TEXT, extra_json TEXT,
 UNIQUE(drama_id,episode_number)
);
CREATE TABLE IF NOT EXISTS ranking_snapshots (
 id INTEGER PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), rank_type TEXT NOT NULL,
 rank INTEGER, observed_at TEXT NOT NULL, collected_at TEXT NOT NULL, source_url TEXT,
 heat_value REAL, heat_raw TEXT, metric_definition TEXT NOT NULL DEFAULT 'composite_heat_not_verified_views',
 UNIQUE(drama_id, rank_type, collected_at)
);
CREATE TABLE IF NOT EXISTS engagement_snapshots (
 id INTEGER PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), episode_id TEXT,
 scope TEXT NOT NULL CHECK(scope IN ('drama','episode')), metric TEXT NOT NULL,
 value REAL, raw_value TEXT, precision TEXT NOT NULL DEFAULT 'unspecified',
 observed_at TEXT, collected_at TEXT NOT NULL, source TEXT NOT NULL, source_url TEXT,
 UNIQUE(drama_id,episode_id,scope,metric,source,collected_at)
);
CREATE TABLE IF NOT EXISTS danmaku (
 dedup_key TEXT PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
 message_id TEXT, text TEXT NOT NULL, playback_time_ms INTEGER, timing_method TEXT NOT NULL,
 posted_at TEXT, captured_at TEXT NOT NULL, source TEXT NOT NULL, coverage TEXT NOT NULL DEFAULT 'unknown',
 raw_json TEXT, CHECK(playback_time_ms IS NULL OR playback_time_ms >= 0)
);
CREATE TABLE IF NOT EXISTS comments (
 dedup_key TEXT PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), episode_id TEXT,
 comment_id TEXT, parent_id TEXT, text TEXT NOT NULL, posted_at TEXT, like_count REAL,
 captured_at TEXT NOT NULL, source TEXT NOT NULL, coverage TEXT NOT NULL DEFAULT 'unknown', raw_json TEXT
);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), episode_id TEXT,
 kind TEXT NOT NULL, local_path TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
 observed_duration_seconds REAL, declared_full INTEGER NOT NULL DEFAULT 0,
 verified_full INTEGER NOT NULL DEFAULT 0, access_basis TEXT NOT NULL,
 captured_at TEXT NOT NULL, source TEXT, note TEXT, UNIQUE(sha256, episode_id, kind)
);
CREATE TABLE IF NOT EXISTS drama_reviews (
 id INTEGER PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id), reviewer TEXT NOT NULL,
 ai_or_live_action TEXT NOT NULL CHECK(ai_or_live_action IN ('AI','live_action','mixed','unknown')),
 human_likeness INTEGER, voice_language TEXT, voice_type TEXT, subtitle_language TEXT,
 burned_in_subtitles INTEGER, sampled_episode_id TEXT, frames_reviewed INTEGER,
 confidence TEXT, note TEXT, reviewed_at TEXT NOT NULL,
 CHECK(human_likeness IS NULL OR human_likeness BETWEEN 1 AND 5)
);
CREATE TABLE IF NOT EXISTS source_receipts (
 id INTEGER PRIMARY KEY, drama_id TEXT NOT NULL REFERENCES dramas(drama_id),
 episode_id TEXT REFERENCES episodes(episode_id), data_kind TEXT NOT NULL,
 source TEXT NOT NULL, source_url TEXT, coverage TEXT NOT NULL,
 reported_total INTEGER, rows_seen INTEGER, observed_at TEXT NOT NULL,
 rights_basis TEXT, evidence_file TEXT, note TEXT,
 CHECK (coverage IN ('full_source_attested','partial','sampled_visible','unavailable','failed','unknown')),
 CHECK (reported_total IS NULL OR reported_total >= 0),
 CHECK (rows_seen IS NULL OR rows_seen >= 0),
 UNIQUE(drama_id,episode_id,data_kind,source,observed_at)
);
CREATE INDEX IF NOT EXISTS idx_receipt_episode ON source_receipts(drama_id,episode_id,data_kind,observed_at);
CREATE TABLE IF NOT EXISTS collection_runs (
 run_id INTEGER PRIMARY KEY, command TEXT NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS collection_events (
 id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES collection_runs(run_id),
 happened_at TEXT NOT NULL, entity_type TEXT, entity_id TEXT, level TEXT NOT NULL,
 code TEXT NOT NULL, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_ep_drama ON episodes(drama_id);
CREATE INDEX IF NOT EXISTS idx_danmaku_episode ON danmaku(episode_id,playback_time_ms);
CREATE INDEX IF NOT EXISTS idx_comments_episode ON comments(episode_id);
CREATE INDEX IF NOT EXISTS idx_engagement_observed ON engagement_snapshots(drama_id,metric,observed_at);
"""


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)
        # Additive migrations: never rebuild or discard existing research rows.
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(episodes)')}
        for name, kind in [('media_duration_seconds', 'REAL'), ('expected_duration_seconds', 'REAL'),
                           ('duration_validation', 'TEXT')]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE episodes ADD COLUMN {name} {kind}')
        self.db.execute('''CREATE TABLE IF NOT EXISTS native_danmaku_pages (
            id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES collection_runs(run_id),
            episode_id TEXT NOT NULL REFERENCES episodes(episode_id), source_url TEXT NOT NULL,
            captured_at TEXT NOT NULL, request_json TEXT NOT NULL, evidence_path TEXT NOT NULL,
            sha256 TEXT NOT NULL, rows_seen INTEGER NOT NULL, inserted INTEGER NOT NULL,
            updated INTEGER NOT NULL, next_offset_ms INTEGER, next_cursor TEXT, has_more INTEGER)''')
        # Screen-visible overlays are observations, never native danmaku records.
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS visible_overlay_records (
            record_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            drama_id TEXT NOT NULL REFERENCES dramas(drama_id),
            episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
            text TEXT NOT NULL, dom_render_id TEXT, source_kind TEXT NOT NULL,
            source_path TEXT, source_review_index INTEGER,
            source_posted_at_raw TEXT, source_posted_at_utc TEXT,
            platform_message_id TEXT, platform_playback_time_ms REAL,
            first_observed_at TEXT NOT NULL, last_observed_at TEXT NOT NULL,
            source_url TEXT NOT NULL, coverage TEXT NOT NULL CHECK(coverage='sampled_visible'),
            CHECK(platform_message_id IS NULL AND platform_playback_time_ms IS NULL)
          );
          CREATE TABLE IF NOT EXISTS visible_overlay_captures (
            capture_sha256 TEXT PRIMARY KEY, run_id INTEGER REFERENCES collection_runs(run_id),
            session_id TEXT NOT NULL, drama_id TEXT NOT NULL, episode_id TEXT NOT NULL,
            evidence_path TEXT NOT NULL, imported_at TEXT NOT NULL,
            snapshots INTEGER NOT NULL, visible_sightings INTEGER NOT NULL
          );
          CREATE TABLE IF NOT EXISTS visible_overlay_observations (
            observation_id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL REFERENCES visible_overlay_records(record_id),
            capture_sha256 TEXT NOT NULL REFERENCES visible_overlay_captures(capture_sha256),
            observed_at TEXT NOT NULL, observed_playback_time_ms REAL,
            timing_method TEXT NOT NULL, video_paused INTEGER, partially_clipped INTEGER NOT NULL,
            visible_bounds_json TEXT NOT NULL,
            CHECK(observed_playback_time_ms IS NULL OR observed_playback_time_ms>=0)
          );
        ''')
        for table, additions in {
            'danmaku':[('source_url','TEXT'),('offset_source','TEXT'),('posting_time_raw_json','TEXT'),
                       ('identity_basis','TEXT'),('last_seen_at','TEXT')],
            'engagement_snapshots':[('coverage_status',"TEXT NOT NULL DEFAULT 'unverified'")],
            'comments':[('record_type',"TEXT NOT NULL DEFAULT 'ordinary_comment'"),('source_url','TEXT')]
        }.items():
            known={r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}
            for name,kind in additions:
                if name not in known:self.db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS native_danmaku_versions (
            version_key TEXT PRIMARY KEY, dedup_key TEXT NOT NULL REFERENCES danmaku(dedup_key),
            raw_json TEXT NOT NULL,captured_at TEXT NOT NULL,evidence_path TEXT NOT NULL,sha256 TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS public_page_snapshots (
            evidence_sha256 TEXT PRIMARY KEY, source_url TEXT NOT NULL, page_kind TEXT NOT NULL,
            drama_id TEXT, episode_id TEXT, collected_at TEXT NOT NULL, evidence_path TEXT NOT NULL,
            payload_json TEXT NOT NULL, response_bytes INTEGER NOT NULL, elapsed_seconds REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS comment_observations (
            observation_key TEXT PRIMARY KEY, comment_key TEXT NOT NULL REFERENCES comments(dedup_key),
            observed_at TEXT NOT NULL, like_count REAL, source_index INTEGER NOT NULL,
            evidence_sha256 TEXT NOT NULL REFERENCES public_page_snapshots(evidence_sha256)
          );
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def start(self, command):
        cur = self.db.execute("INSERT INTO collection_runs(command,started_at,status) VALUES(?,?,?)", (command,utcnow(),'running'))
        self.db.commit()
        return cur.lastrowid

    def finish(self, run_id, status='complete', **detail):
        self.db.execute("UPDATE collection_runs SET finished_at=?,status=?,detail_json=? WHERE run_id=?",
                        (utcnow(),status,json_str(detail),run_id))
        self.db.commit()

    def event(self, run_id, level, code, detail='', entity_type='', entity_id=''):
        self.db.execute("INSERT INTO collection_events(run_id,happened_at,entity_type,entity_id,level,code,detail) VALUES(?,?,?,?,?,?,?)",
                        (run_id, utcnow(),entity_type,entity_id,level,code,str(detail)[:4000]))
        self.db.commit()

    def upsert_drama(self, d: dict, source='public_rank'):
        sid = str(d.get('drama_id') or d.get('series_id') or '').strip()
        title = str(d.get('title') or '').strip()
        if not sid or not title:
            raise ValueError('Each drama needs a real drama_id and title')
        now = utcnow()
        fields = (sid,title,d.get('url'),d.get('genre'),d.get('ai_classification') or 'unknown',
                  d.get('description'),d.get('status') or 'unknown', int(d['episode_count']) if str(d.get('episode_count') or '').isdigit() else None,
                  d.get('creator'),d.get('rank_source'),now,now,source,json_str(d))
        self.db.execute("""INSERT INTO dramas(drama_id,title,url,genre,ai_classification,description,status,episode_count,creator,rank_source,discovered_at,last_seen,source,extra_json)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(drama_id) DO UPDATE SET
         title=excluded.title, url=COALESCE(excluded.url,dramas.url), genre=COALESCE(excluded.genre,dramas.genre),
         ai_classification=CASE WHEN excluded.ai_classification='unknown' THEN dramas.ai_classification ELSE excluded.ai_classification END,
         description=COALESCE(excluded.description,dramas.description), status=CASE WHEN excluded.status='unknown' THEN dramas.status ELSE excluded.status END,
         episode_count=COALESCE(excluded.episode_count,dramas.episode_count), creator=COALESCE(excluded.creator,dramas.creator),
         rank_source=COALESCE(excluded.rank_source,dramas.rank_source), last_seen=excluded.last_seen,source=excluded.source,extra_json=excluded.extra_json""", fields)
        self.db.commit()
        return sid

    def ensure_drama(self, drama_id):
        if not self.db.execute('SELECT 1 FROM dramas WHERE drama_id=?',(str(drama_id),)).fetchone():
            raise ValueError(f'Unknown drama_id={drama_id}. Import drama metadata first.')

    def upsert_episode(self, ep: dict):
        sid = str(ep.get('drama_id') or '').strip()
        eid = str(ep.get('episode_id') or '').strip()
        if not eid or not sid:
            raise ValueError('episode_id and drama_id are required')
        self.ensure_drama(sid)
        n = ep.get('episode_number')
        n = int(n) if str(n or '').isdigit() else None
        duration = float(ep['duration_seconds']) if str(ep.get('duration_seconds') or '').strip() else None
        import math
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            raise ValueError('Source duration must be finite and positive')
        old = self.db.execute('SELECT drama_id FROM episodes WHERE episode_id=?',(eid,)).fetchone()
        if old and old['drama_id'] != sid:
            raise ValueError('Episode ID reused for a different drama; cross-source mapping must be reviewed')
        self.db.execute('''INSERT INTO episodes(episode_id,drama_id,episode_number,duration_seconds,source_url,extra_json)
         VALUES(?,?,?,?,?,?) ON CONFLICT(episode_id) DO UPDATE SET
         episode_number=COALESCE(excluded.episode_number,episodes.episode_number),
         duration_seconds=COALESCE(excluded.duration_seconds,episodes.duration_seconds),
         source_url=COALESCE(excluded.source_url,episodes.source_url),extra_json=excluded.extra_json''',
          (eid,sid,n,duration,ep.get('source_url'),json_str(ep)))
        self.db.commit()
        return eid

    def add_rank(self, d, rank_type, source_url, observed_at=None, collected_at=None):
        now = collected_at or utcnow()
        self.db.execute('''INSERT OR IGNORE INTO ranking_snapshots(drama_id,rank_type,rank,observed_at,collected_at,source_url,heat_value,heat_raw)
          VALUES(?,?,?,?,?,?,?,?)''',(d['drama_id'], rank_type,
          int(d['rank']) if str(d.get('rank') or '').isdigit() else None, observed_at or now,now,source_url,
          metric_number(d.get('heat_label')),str(d.get('heat_label') or '')))
        for key, name in [('likes_label','likes'),('favorites_label','favorites'),('rating_label','rating'),
                          ('comments_label','comments'),('shares_label','shares')]:
            if d.get(key):
                self.add_metric({'drama_id':d['drama_id'],'scope':'drama','metric':name,
                                 'value':metric_number(d[key]),'raw_value':d[key], 'precision':'rounded_display',
                                 'source':source_url,'collected_at':now,'observed_at':observed_at or now})
        self.db.commit()

    def add_metric(self, d):
        sid = str(d.get('drama_id') or '')
        self.ensure_drama(sid)
        scope = d.get('scope') or ('episode' if d.get('episode_id') else 'drama')
        if scope not in ('drama','episode'):
            raise ValueError('scope must be drama or episode')
        eid = str(d.get('episode_id') or '') or None
        if scope=='episode' and not eid:
            raise ValueError('Episode metric must identify episode_id')
        if scope=='drama' and eid:
            raise ValueError('Drama metric must not identify an episode')
        if eid and not self.db.execute('SELECT 1 FROM episodes WHERE episode_id=? AND drama_id=?',(eid,sid)).fetchone():
            raise ValueError('Unknown episode_id for drama')
        metric = str(d.get('metric') or '').strip()
        if metric not in {'views','likes','favorites','comments','shares','rating','heat','rank','replies','other'}:
            raise ValueError(f'Unknown engagement metric: {metric}')
        raw = d.get('raw_value') or d.get('value')
        numeric = d.get('value') if d.get('value') not in ('',None) else raw
        try:
            value = float(numeric)
        except (ValueError,TypeError):
            value = metric_number(numeric)
        import math
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError('Metric must be finite and nonnegative')
        now = d.get('collected_at') or utcnow()
        observed = d.get('observed_at') or now
        source = d.get('source') or 'external_export'
        # NULL episode IDs bypass SQLite UNIQUE; dedup by observation identity.
        old = self.db.execute('''SELECT value,raw_value,precision FROM engagement_snapshots
            WHERE drama_id=? AND episode_id IS ? AND scope=? AND metric=? AND source=? AND observed_at=?''',
            (sid,eid,scope,metric,source,observed)).fetchone()
        if old:
            if old['value'] != value:
                raise ValueError('Conflicting metric values for the same source observation')
            return False
        self.db.execute('''INSERT OR IGNORE INTO engagement_snapshots(drama_id,episode_id,scope,metric,value,raw_value,precision,observed_at,collected_at,source,source_url,coverage_status)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(sid,eid,scope,metric,value,str(raw if raw is not None else ''),d.get('precision') or 'unspecified',
               observed,now,source,d.get('source_url'),d.get('coverage_status') or 'unverified'))
        self.db.commit()
        return True

    def add_danmaku(self, d):
        sid, eid = str(d.get('drama_id') or ''),str(d.get('episode_id') or '')
        text = str(d.get('text') or '').strip()
        if not sid or not eid or not text:
            raise ValueError('Danmaku requires drama_id, episode_id, and text')
        if not self.db.execute('SELECT 1 FROM episodes WHERE episode_id=? AND drama_id=?',(eid,sid)).fetchone():
            raise ValueError('Import drama and episode before danmaku')
        timing = d.get('timing_method') or 'unknown'
        if timing not in ('platform_native','estimated_observation','unknown'):
            raise ValueError('Invalid timing_method')
        t = d.get('playback_time_ms')
        t = int(float(t)) if t is not None and str(t).strip() else None
        if t is not None and t < 0:
            raise ValueError('Negative playback timestamp')
        mid = str(d.get('message_id') or '').strip() or None
        source = d.get('source') or 'external_export'
        key = stable_hash(source,eid,mid) if mid else stable_hash(source,eid,text,t,d.get('posted_at'))
        self.db.execute('''INSERT OR IGNORE INTO danmaku(dedup_key,drama_id,episode_id,message_id,text,playback_time_ms,timing_method,posted_at,captured_at,source,coverage,raw_json)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (key,sid,eid,mid,text,t,timing,d.get('posted_at'),d.get('captured_at') or utcnow(),
          source,d.get('coverage') or 'unknown',json_str(d)))
        self.db.commit()

    def add_comment(self, d):
        sid = str(d.get('drama_id') or '')
        text = str(d.get('text') or '').strip()
        if not sid or not text:
            raise ValueError('Comment requires drama_id and text')
        self.ensure_drama(sid)
        eid = str(d.get('episode_id') or '') or None
        if eid and not self.db.execute('SELECT 1 FROM episodes WHERE drama_id=? AND episode_id=?',(sid,eid)).fetchone():
            raise ValueError('Unknown episode_id')
        mid = str(d.get('comment_id') or '').strip() or None
        source = d.get('source') or 'external_export'
        key = stable_hash(source,eid or sid,mid) if mid else stable_hash(source,eid or sid,text,d.get('posted_at'),d.get('parent_id'))
        likes = metric_number(d.get('like_count'))
        self.db.execute('''INSERT OR IGNORE INTO comments(dedup_key,drama_id,episode_id,comment_id,parent_id,text,posted_at,like_count,captured_at,source,coverage,raw_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(key,sid,eid,mid,d.get('parent_id'),text,d.get('posted_at'),likes,
          d.get('captured_at') or utcnow(),source,d.get('coverage') or 'unknown',json_str(d)))
        self.db.commit()

    def review(self, d):
        sid=str(d.get('drama_id') or '')
        self.ensure_drama(sid)
        label=d.get('ai_or_live_action') or 'unknown'
        if label not in {'AI','live_action','mixed','unknown'}:
            raise ValueError('ai_or_live_action must be AI/live_action/mixed/unknown')
        h=d.get('human_likeness')
        h=int(h) if str(h or '').strip() else None
        if h is not None and not 1<=h<=5:
            raise ValueError('human_likeness must be between 1 and 5')
        frames=d.get('frames_reviewed')
        frames=int(frames) if str(frames or '').strip() else None
        self.db.execute("""INSERT INTO drama_reviews(drama_id,reviewer,ai_or_live_action,human_likeness,voice_language,voice_type,subtitle_language,burned_in_subtitles,sampled_episode_id,frames_reviewed,confidence,note,reviewed_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(sid,d.get('reviewer') or 'anonymous',label,h,d.get('voice_language'),d.get('voice_type'),d.get('subtitle_language'),
          1 if str(d.get('burned_in_subtitles') or '').lower() in {'1','true','yes'} else 0,
          d.get('sampled_episode_id'),frames,d.get('confidence') or 'unverified',d.get('note'),d.get('reviewed_at') or utcnow()))
        self.db.commit()

    def add_receipt(self, d):
        # Evidence of a collection attempt; self-reported, never proof of platform completeness.
        sid=str(d.get('drama_id') or '').strip()
        self.ensure_drama(sid)
        eid=str(d.get('episode_id') or '').strip() or None
        if eid and not self.db.execute('SELECT 1 FROM episodes WHERE episode_id=? AND drama_id=?',(eid,sid)).fetchone():
            raise ValueError('Receipt episode_id does not belong to drama')
        kind=str(d.get('data_kind') or '').strip()
        if kind not in {'danmaku','comments','replies','video','subtitles','engagement','ranking','views'}:
            raise ValueError('Invalid receipt data_kind')
        coverage=str(d.get('coverage') or 'unknown')
        if coverage not in {'full_source_attested','partial','sampled_visible','unavailable','failed','unknown'}:
            raise ValueError('Invalid receipt coverage')
        if coverage=='full_source_attested' and not str(d.get('source_url') or d.get('evidence_file') or '').strip():
            raise ValueError('Full-source attestation requires an inspectable source URL or evidence file')
        def val(k):
            x=d.get(k)
            return int(x) if x is not None and str(x).strip() else None
        observed=d.get('observed_at') or utcnow()
        self.db.execute('''INSERT OR IGNORE INTO source_receipts
            (drama_id,episode_id,data_kind,source,source_url,coverage,reported_total,rows_seen,
             observed_at,rights_basis,evidence_file,note)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (sid,eid,kind,str(d.get('source') or 'unknown'),d.get('source_url'),coverage,
             val('reported_total'),val('rows_seen'),observed,d.get('rights_basis'),
             d.get('evidence_file'),d.get('note')))
        self.db.commit()

    def fetch(self, query: str, args=()):
        return [dict(x) for x in self.db.execute(query,args).fetchall()]

    def count(self, name):
        if name not in {'dramas','episodes','ranking_snapshots','engagement_snapshots','danmaku','comments','assets','drama_reviews','collection_events','source_receipts'}:
            raise ValueError(name)
        return self.db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]

    def export_csv(self, outdir: str|Path):
        outdir = Path(outdir)
        outdir.mkdir(parents=True,exist_ok=True)
        tables = ['dramas','episodes','ranking_snapshots','engagement_snapshots','danmaku','comments','assets','drama_reviews','collection_runs','collection_events','source_receipts','native_danmaku_pages','native_danmaku_versions','visible_overlay_records','visible_overlay_observations','visible_overlay_captures','public_page_snapshots','comment_observations']
        for name in tables:
            cols = [row['name'] for row in self.db.execute(f'PRAGMA table_info({name})')]
            with (outdir/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                w = csv.DictWriter(f,fieldnames=cols)
                w.writeheader()
                for row in self.db.execute(f'SELECT * FROM {name}'):
                    w.writerow(dict(row))
        return outdir
