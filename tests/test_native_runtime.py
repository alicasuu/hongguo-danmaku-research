"""Mock transport tests, not claims of successful live Hongguo collection."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import requests
from hongguo.native import collect_native,parse_native_page,request_spec
from hongguo.native_runtime import fetch_native_response
from hongguo.browser import is_generated_review_overlay
from hongguo.storage import Store
from test_native import fixture,SID,EID


def response(payload,status=200,headers=None):
    res=Mock();res.status_code=status;res.headers=headers or {}
    res.iter_content.return_value=[json.dumps(payload).encode()]
    res.__enter__=Mock(return_value=res);res.__exit__=Mock(return_value=False)
    return res


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'db.sqlite'
        with Store(self.path) as db:
            db.upsert_drama({'drama_id':SID,'title':'SYNTHETIC TEST'})
            db.upsert_episode({'drama_id':SID,'episode_id':EID,'episode_number':1})

    def run_scan(self,client,**kwargs):
        return collect_native(self.path,drama_id=SID,episode_id=EID,outdir=self.root/'proof',client=client,**kwargs)

    def test_transient_retry_recovers_and_records_attempts(self):
        client=Mock();client.s.post.side_effect=[requests.Timeout('secret must not be logged'),response({},503),response(fixture())]
        sleep=Mock()
        result=fetch_native_response(client,request_spec(SID,EID),retries=2,sleep=sleep)
        self.assertEqual(len(result['attempts']),3)
        self.assertEqual(result['http_status'],200)
        self.assertEqual(sleep.call_count,2)

    def test_denials_and_business_errors_are_not_retried(self):
        for status,payload in [(401,{}),(403,{}),(429,{}),(200,{'Code':110001})]:
            client=Mock();client.s.post.return_value=response(payload,status)
            sleep=Mock();fetch_native_response(client,request_spec(SID,EID),retries=5,sleep=sleep)
            self.assertEqual(client.s.post.call_count,1);sleep.assert_not_called()

    def test_long_retry_after_stops_without_early_retry(self):
        client=Mock();client.s.post.return_value=response({},503,{'Retry-After':'120'})
        sleep=Mock();fetch_native_response(client,request_spec(SID,EID),sleep=sleep)
        sleep.assert_not_called();self.assertEqual(client.s.post.call_count,1)

    def test_exhausted_retry_does_not_leak_exception_contents(self):
        client=Mock();client.s.post.side_effect=requests.ConnectionError('private token value')
        with self.assertRaises(RuntimeError) as caught:
            fetch_native_response(client,request_spec(SID,EID),retries=1,sleep=Mock())
        self.assertNotIn('private',str(caught.exception))
        self.assertEqual(client.s.post.call_count,2)

    def test_resume_from_last_committed_page_and_fresh_incremental_scan(self):
        first=fixture();first['data']['common_list_info']={'has_more':True,'cursor':'next-page'}
        client=Mock();client.s.post.return_value=response(first)
        self.assertEqual(self.run_scan(client)['status'],'page_limit_reached')
        client=Mock();client.s.post.return_value=response(fixture(mid='second',offset=100))
        result=self.run_scan(client,resume=True)
        self.assertTrue(result['resumed']);self.assertEqual(result['inserted'],1)
        sent=client.s.post.call_args.kwargs['json']
        self.assertEqual(sent['cursor'],'next-page')
        self.assertEqual(sent['business_param']['start_offset_time'],0)
        client=Mock()
        self.assertEqual(self.run_scan(client,resume=True)['status'],'already_scanned_partial')
        client.s.post.assert_not_called()
        # Default fresh scans rescan old playback positions for late arrivals.
        client=Mock();client.s.post.return_value=response(fixture(mid='late',offset=0))
        self.assertEqual(self.run_scan(client)['inserted'],1)
        self.assertEqual(client.s.post.call_args.kwargs['json']['cursor'],'')

    def test_resume_after_failed_next_request_retries_uncommitted_page(self):
        page=fixture();page['data']['extra']={'next_query_danmaku_list_time':30000}
        page['data']['common_list_info']['has_more']=True
        client=Mock();client.s.post.side_effect=[response(page),response({},503)]
        result=self.run_scan(client,max_pages=2,retries=0)
        self.assertEqual(result['status'],'partial_failed')
        client=Mock();client.s.post.return_value=response(fixture(mid='later',offset=31000))
        self.run_scan(client,resume=True)
        self.assertEqual(client.s.post.call_args.kwargs['json']['business_param']['start_offset_time'],30000)

    def test_tampered_checkpoint_refused_without_network(self):
        page=fixture();page['data']['extra']={'next_query_danmaku_list_time':30000}
        page['data']['common_list_info']['has_more']=True
        client=Mock();client.s.post.return_value=response(page)
        self.run_scan(client)
        evidence=next((self.root/'proof').glob('*page_1.json'));evidence.write_text('{}')
        client=Mock();result=self.run_scan(client,resume=True)
        self.assertEqual(result['status'],'blocked');client.s.post.assert_not_called()

    def test_failed_fresh_scan_does_not_resume_an_older_terminal_page(self):
        client=Mock();client.s.post.return_value=response(fixture())
        self.assertEqual(self.run_scan(client)['status'],'scan_finished_partial')
        client=Mock();client.s.post.return_value=response({},503)
        self.assertEqual(self.run_scan(client,retries=0)['status'],'blocked')
        client=Mock();client.s.post.return_value=response(fixture(mid='late'))
        self.assertEqual(self.run_scan(client,resume=True)['inserted'],1)
        self.assertEqual(client.s.post.call_args.kwargs['json']['cursor'],'')

    def test_generated_review_overlays_never_become_native(self):
        self.assertTrue(is_generated_review_overlay({'render_id':'dm-init-0','native_ms':1000}))
        self.assertTrue(is_generated_review_overlay({'message_id':'dm-init-3'}))
        self.assertFalse(is_generated_review_overlay({'message_id':'123456789'}))
        with self.assertRaisesRegex(ValueError,'generated review'):
            parse_native_page(fixture(mid='dm-init-0'),request_spec(SID,EID),SID,EID)
