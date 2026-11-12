import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from hongguo.storage import Store
from hongguo.public_research import extract_page,import_page,collect_research


def html():
    d={'series_id':'123','series_name':'SYNTHETIC','episode_cnt':2,'vid_list':['456','457'],
       'series_intro':'Test fixture','tags':['测试'],'series_episode_info':{'series_status':1}}
    reviews={'total_count':'100','reviews':[{'content':'SYNTHETIC TEXT','create_time':'1793830101',
        'digg_count':'0','user_name':'private fixture name','user_avatar':'https://example.org/private'}]}
    data={'seriesDetail':d,'seriesSocialInfo':{'series_favorite_count':'2000','series_like_count':'3000',
        'rating':8,'hot_score_data':{'score':123456},'reviews':reviews},
        'episodeSocialInfo':{'episode_like_count':'12','reviews':reviews},
        'publicVideoSeo':{'itemId':'456','durationSeconds':60,'available':True,'posterUrl':'private'},
        'req':{'token':'do-not-retain'},'protectedPlayback':True}
    return '<script>_ROUTER_DATA = '+json.dumps({'loaderData':{'page':data}})+';</script>'


class PublicResearchTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.path=self.root/'db.sqlite';self.db=Store(self.path);self.addCleanup(self.db.close)
        self.db.upsert_drama({'drama_id':'123','title':'SYNTHETIC','episode_count':2})
        for eid,n in [('456',1),('457',2)]:self.db.upsert_episode({'drama_id':'123','episode_id':eid,'episode_number':n})

    def evidence(self,kind='player',at='2026-11-10T00:00:00+00:00'):
        url='https://hongguoduanju.com/'+('player/123' if kind=='player' else 'detail?series_id=123')
        payload=extract_page(html(),url,kind,'123')
        path=self.root/(kind+at[11:19].replace(':','')+'.json')
        path.write_text(json.dumps({'source_url':url,'page_kind':kind,'drama_id':'123','collected_at':at,
            'payload':payload,'response_bytes':100,'elapsed_seconds':1}))
        return path

    def test_public_fields_are_scoped_and_secrets_excluded(self):
        data=extract_page(html(),'https://hongguoduanju.com/player/123','player','123')
        self.assertEqual({m['metric'] for m in data['metrics']},{'likes','comments'})
        self.assertTrue(all(m['scope']=='episode' and m['episode_id']=='456' for m in data['metrics']))
        self.assertNotIn('do-not-retain',json.dumps(data));self.assertNotIn('private fixture name',json.dumps(data))
        self.assertEqual(data['media']['expected_duration_seconds'],60)
        self.assertEqual(data['views_status'],'unavailable')

    def test_missing_social_data_is_not_zero(self):
        with self.assertRaises(ValueError):extract_page(html().replace('episodeSocialInfo','unknownSocialInfo'),'', 'player','123')
        with self.assertRaises(ValueError):extract_page(html(),'', 'player','999')

    def test_actual_import_preserves_missing_ids_and_zero_likes(self):
        result=import_page(self.db,self.evidence());self.assertEqual(result['new_comments'],1)
        row=self.db.fetch('SELECT * FROM comments')[0]
        self.assertIsNone(row['comment_id']);self.assertIsNone(row['parent_id']);self.assertEqual(row['like_count'],0)
        self.assertEqual(row['record_type'],'episode_comment_preview')
        self.assertEqual(self.db.count('danmaku'),0)

    def test_replay_and_new_snapshot_preserve_history(self):
        path=self.evidence();import_page(self.db,path)
        self.assertTrue(import_page(self.db,path)['replayed'])
        result=import_page(self.db,self.evidence(at='2026-11-11T00:01:00+00:00'))
        self.assertEqual(result['new_comments'],0);self.assertEqual(result['new_metrics'],2)
        self.assertEqual(self.db.fetch('SELECT count(*) n FROM comment_observations')[0]['n'],2)

    def test_detail_reviews_and_player_comments_remain_distinct(self):
        import_page(self.db,self.evidence('detail'));import_page(self.db,self.evidence())
        self.assertEqual(self.db.count('comments'),2)
        metrics=self.db.fetch("SELECT * FROM engagement_snapshots WHERE metric='favorites'")
        self.assertEqual(len(metrics),1);self.assertEqual(metrics[0]['scope'],'drama')
        self.assertIsNone(metrics[0]['episode_id'])

    def test_zero_receipt_is_preserved(self):
        self.db.add_receipt({'drama_id':'123','data_kind':'comments','coverage':'partial','rows_seen':0,'reported_total':0})
        row=self.db.fetch('SELECT * FROM source_receipts')[0]
        self.assertEqual(row['rows_seen'],0);self.assertEqual(row['reported_total'],0)

    def test_checkpoint_resume_uses_saved_pages(self):
        client=Mock();client.get_html.side_effect=lambda url: '<a href="/detail?series_id=123">SYNTHETIC</a>' if '/rank/' in url else html()
        out=self.root/'run';result=collect_research(self.path,out,client=client)
        self.assertEqual(result['failures'],[])
        again=Mock();again.get_html.side_effect=AssertionError('Unexpected network on resume')
        result=collect_research(self.path,out,resume=True,client=again)
        self.assertEqual(result['failures'],[]);self.assertEqual(result['new_comments'],0)
        again.get_html.assert_not_called()
