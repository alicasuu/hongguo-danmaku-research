"""Synthetic fixtures only; live samples are saved separately under output/."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from hongguo.storage import Store
from hongguo.visible_overlays import import_capture,parse_capture,export_visible

SID='1234567890123456789';EID='2234567890123456789'


def fixture():
    return {'schema_version':1,'session_id':'synthetic-session','snapshots':[{
        'drama_id':SID,'episode_id':EID,'source_url':f'https://hongguoduanju.com/player/{SID}',
        'coverage':'sampled_visible','observed_at':'2026-11-10T00:00:00.123Z',
        'source_path':'episodeSocialInfo.reviews.reviews',
        'video':{'current_time_seconds':0,'paused':False},
        'messages':[{'text':'SYNTHETIC TEXT','dom_render_id':'dm-init-0','visible':True,
            'visible_bounds':{'left':0,'right':20,'top':1,'bottom':15},'partially_clipped':True,
            'platform_message_id':None,'platform_playback_time_ms':None,
            'source_match':'renderer_index_and_exact_text',
            'source_review':{'index':0,'content':'SYNTHETIC TEXT','create_time':'1793830101'}}]}]}


class VisibleOverlayTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.path=self.root/'capture.json'
        self.db=Store(self.root/'db.sqlite');self.addCleanup(self.db.close)
        self.db.upsert_drama({'drama_id':SID,'title':'SYNTHETIC'})
        self.db.upsert_episode({'drama_id':SID,'episode_id':EID,'episode_number':1})

    def save(self,data):
        self.path.write_text(json.dumps(data));return import_capture(self.db,self.path)

    def test_zero_position_posting_time_and_no_native_fields(self):
        self.assertEqual(self.save(fixture())['records_added'],1)
        record=self.db.fetch('SELECT * FROM visible_overlay_records')[0]
        obs=self.db.fetch('SELECT * FROM visible_overlay_observations')[0]
        self.assertIsNone(record['platform_message_id']);self.assertIsNone(record['platform_playback_time_ms'])
        self.assertEqual(record['source_posted_at_raw'],'1793830101')
        self.assertTrue(record['source_posted_at_utc'].endswith('Z'))
        self.assertEqual(obs['observed_playback_time_ms'],0)
        self.assertEqual(obs['timing_method'],'observed_playback_position')
        self.assertEqual(self.db.count('danmaku'),0);self.assertEqual(self.db.count('comments'),0)

    def test_repeat_import_and_incremental_snapshot_are_deduplicated(self):
        data=fixture();self.save(data)
        self.assertEqual(self.save(data)['records_added'],0)
        later=copy.deepcopy(data['snapshots'][0]);later['observed_at']='2026-11-10T00:00:02.123Z'
        later['video']['current_time_seconds']=2.123456;data['snapshots'].append(later)
        result=self.save(data)
        self.assertEqual(result['records_added'],0);self.assertEqual(result['observations_added'],1)
        self.assertEqual(self.db.fetch('SELECT count(*) n FROM visible_overlay_observations')[0]['n'],2)

    def test_same_dom_index_on_reload_is_not_a_global_message_id(self):
        data=fixture();self.save(data);data['session_id']='new-page-load'
        self.assertEqual(self.save(data)['records_added'],1)

    def test_unmatched_source_does_not_invent_posting_time(self):
        data=fixture();snap=data['snapshots'][0];snap['video']=None
        snap['messages'][0]['source_review']=None
        self.save(data)
        row=self.db.fetch('SELECT * FROM visible_overlay_records')[0]
        self.assertIsNone(row['source_posted_at_raw'])
        obs=self.db.fetch('SELECT * FROM visible_overlay_observations')[0]
        self.assertIsNone(obs['observed_playback_time_ms']);self.assertEqual(obs['timing_method'],'unknown')

    def test_mismatched_review_or_fabricated_native_values_rejected(self):
        for key,value in [('platform_message_id','fake'),('platform_playback_time_ms',1000),('dom_render_id','dm-init-8')]:
            data=fixture();data['snapshots'][0]['messages'][0][key]=value
            with self.assertRaises(ValueError):self.save(data)
        self.assertEqual(self.db.fetch('SELECT count(*) n FROM visible_overlay_records')[0]['n'],0)

    def test_hidden_nodes_invalid_positions_and_url_credentials_rejected(self):
        data=fixture();data['snapshots'][0]['messages'][0]['visible']=False
        with self.assertRaises(ValueError):parse_capture(data)
        for value in [-1,float('nan'),True]:
            data=fixture();data['snapshots'][0]['video']['current_time_seconds']=value
            with self.assertRaises(ValueError):parse_capture(data)
        data=fixture();data['snapshots'][0]['source_url']+='?token=private'
        with self.assertRaises(ValueError):parse_capture(data)

    def test_late_error_rolls_back_whole_capture(self):
        data=fixture();self.save(data)
        old=copy.deepcopy(data['snapshots'][0]['messages'][0])
        data['snapshots'][0]['messages'][0]['text']='NEW SYNTHETIC'
        data['snapshots'][0]['messages'][0]['source_review']=None
        old['source_review']['create_time']='1793830102'
        data['snapshots'][0]['messages'].append(old)
        with self.assertRaises(ValueError):self.save(data)
        self.assertEqual(self.db.fetch('SELECT count(*) n FROM visible_overlay_records')[0]['n'],1)
        self.assertEqual(self.db.fetch('SELECT count(*) n FROM visible_overlay_captures')[0]['n'],1)

    def test_csv_exports_explicitly_separate_timing_and_ids(self):
        self.save(fixture());summary=export_visible(self.db,self.root/'csv')
        self.assertEqual(summary['records'],1);self.assertEqual(summary['native_messages_collected_by_this_mode'],0)
        header=(self.root/'csv/visible_overlay_records.csv').read_text(encoding='utf-8-sig').splitlines()[0]
        self.assertIn('dom_render_id',header);self.assertIn('platform_message_id',header)
        header=(self.root/'csv/visible_overlay_samples.csv').read_text(encoding='utf-8-sig').splitlines()[0]
        for field in ('text','observed_playback_time_ms','source_posted_at_raw','platform_playback_time_ms','observed_at'):
            self.assertIn(field,header)
