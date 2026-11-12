import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import Mock
from hongguo.storage import Store
from hongguo.research_report import write_research_report


class ReportTests(unittest.TestCase):
    def test_demo_exclusion_and_missing_files_do_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dbpath=root/'db.sqlite'
            with Store(dbpath) as db:
                db.upsert_drama({'drama_id':'DEMO_TEST','title':'DEMO','episode_count':9})
                db.upsert_drama({'drama_id':'123','title':'TEST','episode_count':1})
                db.upsert_episode({'drama_id':'123','episode_id':'456','episode_number':1})
                db.db.execute("UPDATE episodes SET completeness='verified_full',media_status='valid_video',media_path='/missing.mp4'")
                db.db.commit()
            result=write_research_report(dbpath,root/'out')
            self.assertEqual(result['counts']['dramas'],1)
            self.assertEqual(result['counts']['verified_complete_video_files'],0)
            data=json.loads((root/'out/quality_report.json').read_text())
            self.assertEqual(data['requirements'][2]['acceptance'],'BLOCKED')
            self.assertEqual(data['counts']['comparable_24h_metric_pairs'],0)
            self.assertTrue((root/'out/native_danmaku.csv').read_text(encoding='utf-8-sig').startswith('drama_id,'))

    def test_schedule_not_due_never_fetches_or_marks_complete(self):
        spec=importlib.util.spec_from_file_location('followup',Path(__file__).resolve().parents[1]/'scripts/followup_snapshot.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'schedule.json';original={'due_at':'2026-11-11T04:23:00+00:00'}
            path.write_text(json.dumps(original));collector=Mock()
            result=module.run_schedule(path,now=datetime(2026,11,10,tzinfo=timezone.utc),collector=collector)
            self.assertEqual(result['status'],'pending');collector.assert_not_called()
            self.assertEqual(json.loads(path.read_text()),original)

    def test_schedule_failure_attempts_are_bounded(self):
        spec=importlib.util.spec_from_file_location('followup',Path(__file__).resolve().parents[1]/'scripts/followup_snapshot.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'schedule.json'
            path.write_text(json.dumps({'due_at':'2026-01-01T00:00:00+00:00','database':str(Path(folder)/'db.sqlite'),'output':str(Path(folder)/'out')}))
            collector=Mock(side_effect=RuntimeError('TEST FAILURE'))
            for expected in ('pending_retry','pending_retry','failed','already_finished'):
                result=module.run_schedule(path,now=datetime(2026,11,10,tzinfo=timezone.utc),collector=collector)
                self.assertEqual(result['status'],expected)
            self.assertEqual(collector.call_count,3)
