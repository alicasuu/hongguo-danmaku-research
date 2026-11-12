import csv
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hongguo.parsing import parse_rank,parse_detail
from hongguo.util import metric_number,validate_public_http_url
from hongguo.collect import collect_public
from hongguo.storage import Store
from hongguo.ingest import ingest
from hongguo.report import report_data,scale_estimate,write_reports
from hongguo.select import select_top_by_views
from hongguo.acceptance import audit_data,write_acceptance
from hongguo.inbox import sync_inbox
from hongguo.media import import_media_manifest,import_subtitle_manifest,ffprobe

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'examples'

class ParsingTests(unittest.TestCase):
    def test_rank(self):
        rows=parse_rank((FIX/'rank.html').read_text(),10)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['rank'],1)
        self.assertIn('128万',rows[0]['heat_label'])
        self.assertEqual(rows[0]['views_label'],'')
    def test_detail(self):
        d=parse_detail((FIX/'details/DEMO_DRAMA_001.html').read_text())
        self.assertEqual(len(d['episodes']),2)
        self.assertEqual(d['episode_count'],2)
    def test_html_missing_is_not_fabricated(self):
        self.assertEqual(parse_rank('<html>Empty</html>'),[])
        self.assertIsNone(parse_detail('<html>Empty</html>'))
    def test_numeric_units(self):
        self.assertEqual(metric_number('11578万热度'),115780000)
        self.assertEqual(metric_number('评分9.5'),9.5)
        self.assertEqual(metric_number('1.2亿'),120000000)
        self.assertIsNone(metric_number('暂无'))
    def test_reject_unapproved_url(self):
        for url in ['file:///etc/passwd','http://hongguoduanju.com','https://evil.example/a','https://hongguoduanju.com:8443/path',
                    'https://alice:secret@hongguoduanju.com/a']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):validate_public_http_url(url,{'hongguoduanju.com'})
    def test_dom_fallback(self):
        html='<article aria-labelledby="rank-title-42"><span class="badge-number-a">1</span><h3 id="rank-title-42">戏剧</h3><p class="metrics-a">80万热度</p></article>'
        self.assertEqual(parse_rank(html)[0]['drama_id'],'42')

class DBTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbfile=Path(self.tmp.name)/'db.sqlite'
        self.result=collect_public(self.dbfile,top=2,local_rank_html=FIX/'rank.html',details_directory=FIX/'details')
    def test_collection_and_coverage(self):
        self.assertEqual(self.result['episode_ids_found'],3)
        with Store(self.dbfile) as s:
            self.assertEqual(s.count('dramas'),2)
            self.assertEqual(s.count('episodes'),3)
            data=report_data(s)
            self.assertEqual(data['counts']['videos_verified_full'],0)
            self.assertEqual(data['dramas'][0]['episode_id_coverage'],1)
    def test_idempotence_collection(self):
        collect_public(self.dbfile,top=2,local_rank_html=FIX/'rank.html',details_directory=FIX/'details')
        with Store(self.dbfile) as s:self.assertEqual(s.count('episodes'),3)
    def test_ingest_and_dedup(self):
        ingest(FIX/'danmaku.jsonl','danmaku',self.dbfile)
        ingest(FIX/'danmaku.jsonl','danmaku',self.dbfile)
        ingest(FIX/'comments.csv','comments',self.dbfile)
        with Store(self.dbfile) as s:
            self.assertEqual(s.count('danmaku'),2)
            self.assertEqual(s.count('comments'),2)
            self.assertEqual(s.count('assets'),0)
            self.assertTrue(s.fetch("SELECT * FROM comments WHERE parent_id='DEMO_COMMENT_01'"))
    def test_engagement_24h_delta(self):
        ingest(FIX/'engagement.jsonl','engagement',self.dbfile)
        with Store(self.dbfile) as s:
            r=report_data(s)
            self.assertEqual(len(r['snapshot_changes']),1)
            self.assertEqual(r['snapshot_changes'][0]['delta'],20)
    def test_heat_is_not_views(self):
        out=select_top_by_views(self.dbfile,Path(self.tmp.name)/'rank.csv')
        self.assertEqual(out['selected'],0)
        ingest(FIX/'engagement.jsonl','engagement',self.dbfile)
        out=select_top_by_views(self.dbfile,Path(self.tmp.name)/'rank.csv')
        self.assertEqual(out['selected'],1)
    def test_missing_episode_danmaku_rejected(self):
        with Store(self.dbfile) as s:
            with self.assertRaises(ValueError):
                s.add_danmaku({'drama_id':'DEMO_DRAMA_001','episode_id':'NOT_REAL','text':'hello'})
    def test_native_vs_estimated_timing(self):
        with Store(self.dbfile) as s:
            s.add_danmaku({'drama_id':'DEMO_DRAMA_001','episode_id':'DEMO_EP_001','text':'time estimate',
                           'playback_time_ms':5000,'timing_method':'estimated_observation'})
            r=report_data(s)
            self.assertEqual(r['dramas'][0]['danmaku_native_timestamps'],0)
            self.assertEqual(r['dramas'][0]['danmaku_timed'],1)
    def test_comment_not_danmaku(self):
        ingest(FIX/'comments.csv','comments',self.dbfile)
        with Store(self.dbfile) as s:self.assertEqual(s.count('danmaku'),0)
    def test_incremental_inbox_reimports_only_changed_authorized_files(self):
        inbox=Path(self.tmp.name)/'inbox'
        (inbox/'comments').mkdir(parents=True)
        src=inbox/'comments'/'authorized.csv'
        src.write_text((FIX/'comments.csv').read_text(encoding='utf-8'),encoding='utf-8')
        r=sync_inbox(self.dbfile,inbox)
        self.assertEqual(r['files_imported'],1)
        r2=sync_inbox(self.dbfile,inbox)
        self.assertEqual(r2['files_imported'],0)
        self.assertEqual(r2['files_skipped'],1)
        with Store(self.dbfile) as db:self.assertEqual(db.count('comments'),2)

    def test_zero_playback_timestamp_is_preserved(self):
        with Store(self.dbfile) as s:
            s.add_danmaku({'drama_id':'DEMO_DRAMA_001','episode_id':'DEMO_EP_001','text':'at start',
                           'message_id':'AT_START','playback_time_ms':0,'timing_method':'platform_native'})
            row=s.fetch("SELECT playback_time_ms,timing_method FROM danmaku WHERE message_id='AT_START'")[0]
            self.assertEqual(row['playback_time_ms'],0)

    def test_missing_required_data_fails_strict_audit(self):
        ingest(FIX/'engagement.jsonl','engagement',self.dbfile)
        with Store(self.dbfile) as s:
            result=audit_data(s,top=2)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertFalse(result['selection']['source_attested_top10'])
        self.assertLess(result['summary']['videos_verified_full'],result['summary']['episodes_listed'])

    def test_receipts_require_evidence_and_do_not_prove_full_collection(self):
        with Store(self.dbfile) as s:
            s.add_receipt({'drama_id':'DEMO_DRAMA_001','episode_id':'DEMO_EP_001',
                           'data_kind':'danmaku','source':'synthetic','coverage':'partial',
                           'observed_at':'2026-11-09T00:00:00+00:00'})
            with self.assertRaises(ValueError):
                s.add_receipt({'drama_id':'DEMO_DRAMA_001','episode_id':'DEMO_EP_001',
                               'data_kind':'danmaku','source':'synthetic','coverage':'full_source_attested',
                               'observed_at':'2026-11-09T01:00:00+00:00'})
            self.assertEqual(s.count('source_receipts'),1)
            result=audit_data(s,top=2)
            if result['dramas']:
                self.assertEqual(result['dramas'][0]['status'],'INCOMPLETE')

    def test_receipts_recheck_and_csv_export(self):
        ingest(FIX/'engagement.jsonl','engagement',self.dbfile)
        with Store(self.dbfile) as s:
            for ts in ['2026-11-09T00:00:00+00:00','2026-11-10T00:00:00+00:00']:
                s.add_receipt({'drama_id':'DEMO_DRAMA_001','episode_id':'DEMO_EP_001',
                               'data_kind':'danmaku','source':'authorized','coverage':'full_source_attested',
                               'source_url':'https://example.org/evidence','observed_at':ts,
                               'reported_total':2,'rows_seen':2})
            r=audit_data(s,top=2)
            per=r['dramas'][0]['episodes'][0]
            self.assertTrue(per['danmaku_source_evidence']['recheck_24h'])
            dest=s.export_csv(Path(self.tmp.name)/'export')
            self.assertTrue((dest/'source_receipts.csv').is_file())

    def test_review_validation(self):
        with Store(self.dbfile) as s:
            s.review({'drama_id':'DEMO_DRAMA_001','reviewer':'A','ai_or_live_action':'AI','human_likeness':4})
            self.assertEqual(s.count('drama_reviews'),1)
            with self.assertRaises(ValueError):s.review({'drama_id':'DEMO_DRAMA_001','human_likeness':6})
    def test_export_schema(self):
        with Store(self.dbfile) as s:
            out=s.export_csv(Path(self.tmp.name)/'csv')
            self.assertTrue((out/'episodes.csv').is_file())
            self.assertTrue((out/'drama_reviews.csv').is_file())
    def test_report_and_scale(self):
        data,b=write_reports(self.dbfile,Path(self.tmp.name)/'reports')
        self.assertEqual(b['estimates'][0]['dramas'],10)
        self.assertTrue((Path(self.tmp.name)/'reports/weekly_report.md').exists())
        self.assertIn('missing data',(Path(self.tmp.name)/'reports/weekly_report.md').read_text().lower())
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg/ffprobe required')
    def test_full_video_verification(self):
        vid=Path(self.tmp.name)/'test.mp4'
        p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=128x128:r=10','-t','2',
                          '-c:v','mpeg4','-y',str(vid)],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertGreater(ffprobe(vid),1.9)
        manifest=Path(self.tmp.name)/'manifest.csv'
        with manifest.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['drama_id','episode_id','local_path','rights_confirmed','access_basis',
                                           'is_full_episode','expected_duration_seconds'])
            w.writeheader()
            w.writerow({'drama_id':'DEMO_DRAMA_001','episode_id':'DEMO_EP_001','local_path':str(vid),
                        'rights_confirmed':'true','access_basis':'synthetic unit-test media',
                        'is_full_episode':'true','expected_duration_seconds':2})
        r=import_media_manifest(manifest,self.dbfile,media_root=Path(self.tmp.name)/'media')
        self.assertEqual(r['valid_video'],1)
        self.assertEqual(r['full_verified'],1)
        with Store(self.dbfile) as s:self.assertEqual(report_data(s)['counts']['videos_verified_full'],1)
    def test_subtitle_only_import(self):
        subtitle=Path(self.tmp.name)/'subtitles.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:02,000\n字幕测试\n',encoding='utf-8')
        m=Path(self.tmp.name)/'subtitles.csv'
        m.write_text('drama_id,episode_id,subtitle_path,rights_confirmed,access_basis\nDEMO_DRAMA_001,DEMO_EP_001,'+str(subtitle)+',true,synthetic unit test\n')
        r=import_subtitle_manifest(m,self.dbfile,subtitle_root=Path(self.tmp.name)/'subtitle_out')
        self.assertEqual(r['imported'],1)
        with Store(self.dbfile) as db:
            ep=db.fetch("SELECT subtitle_status FROM episodes WHERE episode_id='DEMO_EP_001'")[0]
            self.assertEqual(ep['subtitle_status'],'available')
            self.assertEqual(db.count('assets'),1)

    def test_video_denied_without_rights(self):
        path=Path(self.tmp.name)/'manifest.csv'
        path.write_text('drama_id,episode_id,local_path,rights_confirmed\nDEMO_DRAMA_001,DEMO_EP_001,/x.mp4,false\n')
        r=import_media_manifest(path,self.dbfile,media_root=Path(self.tmp.name)/'media')
        self.assertEqual(r['valid_video'],0)
        self.assertEqual(r['failed'],1)

if __name__=='__main__':unittest.main()
