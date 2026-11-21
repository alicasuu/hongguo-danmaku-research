"""One-shot authorized export ingestion; no polling or timers."""
from __future__ import annotations
import json
from pathlib import Path
from .storage import Store
from .ingest import ingest
from .util import file_sha256, utcnow

KINDS=('dramas','episodes','danmaku','comments','engagement','reviews','receipts')


def sync_inbox(dbpath,inbox):
    """Import currently present provider exports exactly once."""
    inbox=Path(inbox).resolve()
    inbox.mkdir(parents=True,exist_ok=True)
    totals={'file_attempts':0,'files_imported':0,'files_skipped':0,'files_failed':0,'rows_seen':0,'errors':[],
            'source':str(inbox),'note':'One local-provider export snapshot. Does not retrieve live platform content.'}
    for _ in range(1):
        # Process parent IDs before episodes, then child data.
        for kind in KINDS:
            folder=inbox/kind
            if not folder.is_dir():continue
            for path in sorted(folder.iterdir()):
                if not path.is_file() or path.suffix.lower() not in {'.csv','.jsonl','.json'}:continue
                size=path.stat().st_size
                if size==0:continue
                sha=file_sha256(path)
                with Store(dbpath) as db:
                    db.db.execute('''CREATE TABLE IF NOT EXISTS imported_files (
                      id INTEGER PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL,
                      bytes INTEGER NOT NULL, imported_at TEXT NOT NULL, rows_seen INTEGER NOT NULL,
                      UNIQUE(path,kind,sha256))''')
                    if db.fetch('SELECT id FROM imported_files WHERE path=? AND kind=? AND sha256=?',(str(path),kind,sha)):
                        totals['files_skipped']+=1
                        continue
                totals['file_attempts']+=1
                try:
                    # Avoid partially written files by depositing with .tmp, then atomically renaming.
                    result=ingest(path,kind,dbpath,source='authorized_inbox:'+path.name,strict=False)
                    totals['rows_seen']+=result['rows_seen']
                    if result['failed']:
                        totals['files_failed']+=1
                        totals['errors'].append({'path':str(path),'errors':result['errors'][:8]})
                    else:
                        with Store(dbpath) as db:
                            db.db.execute('''CREATE TABLE IF NOT EXISTS imported_files (
                              id INTEGER PRIMARY KEY,path TEXT NOT NULL,kind TEXT NOT NULL,sha256 TEXT NOT NULL,
                              bytes INTEGER NOT NULL,imported_at TEXT NOT NULL,rows_seen INTEGER NOT NULL,
                              UNIQUE(path,kind,sha256))''')
                            db.db.execute('''INSERT OR IGNORE INTO imported_files(path,kind,sha256,bytes,imported_at,rows_seen)
                                 VALUES(?,?,?,?,?,?)''',(str(path),kind,sha,size,utcnow(),result['rows_seen']))
                            db.db.commit()
                        totals['files_imported']+=1
                except Exception as e:
                    totals['files_failed']+=1
                    totals['errors'].append({'path':str(path),'error':str(e)})
    totals['cycles']=1
    return totals
