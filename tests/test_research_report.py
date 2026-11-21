import json
import tempfile
import unittest
from pathlib import Path
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

