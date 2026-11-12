#!/usr/bin/env python3
"""One scheduled public-page follow-up. Never claims a snapshot before its due time."""
import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hongguo.public_research import collect_research
from hongguo.research_report import write_research_report
from hongguo.storage import Store
from hongguo.util import utcnow


def run_schedule(schedule_path,now=None,collector=collect_research):
    path=Path(schedule_path).resolve();now=now or datetime.now(timezone.utc)
    with path.with_suffix('.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'already_running'}
        state=json.loads(path.read_text())
        if str(state.get('status','')).startswith('cancelled'):
            return {'status':state['status']}
        if state.get('finished_at'):return {'status':'already_finished','finished_at':state['finished_at']}
        due=datetime.fromisoformat(state['due_at'])
        if now<due:return {'status':'pending','due_at':state['due_at']}
        out=Path(state['output']);dbpath=state['database']
        state['started_at']=utcnow();state['attempts']=state.get('attempts',0)+1
        temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(state,indent=2));temporary.replace(path)
        try:
            result=collector(dbpath,out,resume=(out/'checkpoint.json').exists(),delay=2)
            with Store(dbpath) as db:db.export_csv(out/'csv')
            write_research_report(dbpath,out/'report')
        except Exception as exc:
            state['last_error_type']=type(exc).__name__
            state['status']='failed' if state['attempts']>=3 else 'pending_retry'
            if state['attempts']>=3:state['finished_at']=utcnow()
            temporary.write_text(json.dumps(state,indent=2));temporary.replace(path)
            return state
        state['result']=result;state['finished_at']=utcnow()
        state['status']='verified_partial' if not result.get('failures') else 'partial_failed'
        temporary.write_text(json.dumps(state,indent=2));temporary.replace(path)
        return state


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('schedule');args=parser.parse_args()
    result=run_schedule(args.schedule)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    # The project-owned launchd job unloads after this single follow-up.
    # Manual early checks do not change the schedule or create observations.
    if result.get('finished_at'):
        state=json.loads(Path(args.schedule).read_text())
        if state.get('job_label')=='org.hongguo.research.followup':
            subprocess.run(['launchctl','bootout',f"gui/{os.getuid()}/org.hongguo.research.followup"],
                           capture_output=True,timeout=10)
