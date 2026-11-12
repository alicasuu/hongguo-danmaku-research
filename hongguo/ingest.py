"""Import permitted provider exports in CSV / JSONL / JSON formats.

Real-time danmaku and asynchronous comments are DIFFERENT types, never conflated.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from .storage import Store

KINDS={'dramas','episodes','danmaku','comments','engagement','reviews','receipts'}


def read_rows(path):
    path=Path(path)
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:
            yield from csv.DictReader(f)
    elif path.suffix.lower()=='.jsonl':
        with path.open(encoding='utf-8-sig') as f:
            for n,line in enumerate(f,1):
                if line.strip():
                    try:
                        obj=json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ValueError(f'{path} line {n} invalid JSON') from e
                    if not isinstance(obj,dict):
                        raise ValueError(f'{path} line {n} expected a JSON object')
                    yield obj
    elif path.suffix.lower()=='.json':
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(data,dict): data=data.get('records') or data.get('items') or data.get('data')
        if not isinstance(data,list): raise ValueError('JSON export must be a list or contain records/items/data list')
        for obj in data:
            if not isinstance(obj,dict): raise ValueError('JSON rows must be objects')
            yield obj
    else:
        raise ValueError('Only .csv, .jsonl, and .json are supported')


def ingest(path, kind, dbpath, *, source='authorized_export', default_coverage='partial',strict=False):
    if kind not in KINDS:
        raise ValueError(kind)
    counts={'rows_seen':0,'insert_attempted':0,'failed':0,'errors':[],'kind':kind,'source':source}
    with Store(dbpath) as db:
        run=db.start('import_'+kind)
        try:
            for row in read_rows(path):
                counts['rows_seen']+=1
                try:
                    row=dict(row)
                    if not row.get('source'): row['source']=source
                    if kind in {'danmaku','comments'} and not row.get('coverage'):
                        row['coverage']=default_coverage
                    if kind=='dramas': db.upsert_drama(row,source)
                    elif kind=='episodes': db.upsert_episode(row)
                    elif kind=='danmaku': db.add_danmaku(row)
                    elif kind=='comments': db.add_comment(row)
                    elif kind=='engagement': db.add_metric(row)
                    elif kind=='reviews': db.review(row)
                    elif kind=='receipts': db.add_receipt(row)
                    counts['insert_attempted']+=1
                except Exception as exc:
                    counts['failed']+=1
                    msg=f"row {counts['rows_seen']}: {type(exc).__name__}: {exc}"
                    if len(counts['errors'])<40: counts['errors'].append(msg)
                    db.event(run,'error','import_row_failed',msg)
                    if strict: raise
            db.finish(run,'partial' if counts['failed'] else 'complete',**counts)
        except Exception as exc:
            db.finish(run,'failed',error=str(exc),**counts)
            raise
    return counts
