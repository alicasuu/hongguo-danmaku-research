"""All invented wire examples here are TEST FIXTURES, never research results."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from hongguo.storage import Store
from hongguo.native import collect_native, parse_native_page, request_spec, save_page

SID='1234567890123456789'
EID='2234567890123456789'


def fixture(mid='9007199254740993123', offset=0, text='SYNTHETIC UNIT TEST'):
    return {'code':0,'data':{'data_list':[{'comment':{'comment_id':mid,
            'common':{'content':{'text':text}},'expand':{'offset_time':offset}}}],
            'common_list_info':{'has_more':False,'cursor':''},'extra':{}}}


class NativeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'db.sqlite'
        with Store(self.path) as db:
            db.upsert_drama({'drama_id':SID,'title':'SYNTHETIC UNIT TEST'})
            db.upsert_episode({'drama_id':SID,'episode_id':EID,'episode_number':1})
        self.req=request_spec(SID,EID)

    def import_fixture(self,payload,request=None):
        path=self.root/'capture.json'
        path.write_text(json.dumps({'request':request or self.req,'response':payload}))
        return collect_native(self.path,drama_id=SID,episode_id=EID,outdir=self.root/'evidence',
                              capture=path,access_basis='SYNTHETIC UNIT TEST')

    def test_zero_offset_and_large_string_id(self):
        rows,_=parse_native_page(fixture(),self.req,SID,EID)
        self.assertEqual(rows[0]['playback_time_ms'],0)
        self.assertEqual(rows[0]['message_id'],'9007199254740993123')

    def test_no_transport_stops_before_network_database_or_evidence_write(self):
        for resume in (False,True):
            with patch('hongguo.native.fetch_native_response') as transport:
                result=collect_native(self.path,drama_id=SID,episode_id=EID,
                    outdir=self.root/'must_not_be_written',resume=resume)
                self.assertEqual(result['reason_code'],'authorized_native_transport_not_connected')
                self.assertEqual(result['network_requests'],0);transport.assert_not_called()
            self.assertFalse((self.root/'must_not_be_written').exists())
        with Store(self.path) as db:
            self.assertEqual(db.fetch('SELECT count(*) n FROM collection_runs')[0]['n'],0)

    def test_reference_success_code_string_supported_but_boolean_rejected(self):
        payload=fixture();payload['code']='0'
        self.assertEqual(len(parse_native_page(payload,self.req,SID,EID)[0]),1)
        for bad in (False,True,0.0,'00','',None):
            payload['code']=bad
            with self.assertRaises(ValueError):parse_native_page(payload,self.req,SID,EID)

    def test_comments_and_wrong_episode_are_rejected(self):
        for key,value in [('comment_type',1),('group_id','wrong')]:
            request=copy.deepcopy(self.req);request['body'][key]=value
            with self.assertRaises(ValueError):parse_native_page(fixture(),request,SID,EID)
        with self.assertRaises(ValueError):parse_native_page({'comments':[]},self.req,SID,EID)

    def test_missing_or_invalid_native_fields_are_rejected(self):
        for value in (None,'',-1,1.5,True,'nan','Infinity'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                parse_native_page(fixture(offset=value),self.req,SID,EID)
        for mid in ('',True,9007199254740992.0):
            with self.assertRaises(ValueError):parse_native_page(fixture(mid=mid),self.req,SID,EID)

    def test_access_error_is_not_zero_messages(self):
        result=self.import_fixture({'Code':110001,'Message':'unknown error'})
        self.assertEqual(result['status'],'blocked');self.assertIn('110001',result['error'])
        with Store(self.path) as db:
            self.assertEqual(db.count('danmaku'),0)
            self.assertEqual(db.fetch('SELECT coverage FROM source_receipts')[0]['coverage'],'failed')

    def test_repeat_late_arrival_and_revision(self):
        a=self.import_fixture(fixture(offset=5000))
        b=self.import_fixture(fixture(offset=5000))
        c=self.import_fixture(fixture(mid='new',offset=0))
        d=self.import_fixture(fixture(offset=5000,text='SYNTHETIC EDIT'))
        self.assertEqual((a['inserted'],b['inserted'],c['inserted'],d['updated']),(1,0,1,1))
        with Store(self.path) as db:
            self.assertEqual(db.count('danmaku'),2)
            self.assertEqual(db.db.execute('SELECT COUNT(*) FROM native_danmaku_pages').fetchone()[0],4)

    def test_malformed_page_does_not_partially_commit(self):
        payload=fixture();payload['data']['data_list'].append({'comment':{}})
        result=self.import_fixture(payload)
        self.assertEqual(result['status'],'blocked')
        with Store(self.path) as db:self.assertEqual(db.count('danmaku'),0)

    def test_checkpoint_failure_rolls_back_messages(self):
        with Store(self.path) as db:
            run=db.start('test')
            with self.assertRaises(FileNotFoundError):
                save_page(db,run,fixture(),self.req,SID,EID,self.root/'missing','2026-11-09T00:00:00Z')
            self.assertEqual(db.count('danmaku'),0)

    def test_empty_page_requires_success_and_schema(self):
        payload=fixture();payload['data']['data_list']=[]
        self.assertEqual(self.import_fixture(payload)['status'],'capture_imported')
        del payload['data']['common_list_info']['has_more']
        self.assertEqual(self.import_fixture(payload)['status'],'blocked')

    def test_live_transport_paginates_and_never_reuses_cached_windows(self):
        first=fixture();first['data']['common_list_info']={'has_more':True,'cursor':'c1'}
        second=fixture(mid='two',offset=1000)
        second['data']['common_list_info']={'has_more':True,'cursor':'c2'}
        second['data']['extra']={'next_query_danmaku_list_time':30000}
        third=fixture(mid='three',offset=31000)
        client=Mock();requests=[]
        def post(url,**kwargs):
            requests.append(copy.deepcopy(kwargs['json']))
            response=Mock();response.status_code=200
            response.iter_content.return_value=[json.dumps([first,second,third][len(requests)-1]).encode()]
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            return response
        client.s.post.side_effect=post
        result=collect_native(self.path,drama_id=SID,episode_id=EID,outdir=self.root/'live',max_pages=4,client=client)
        self.assertEqual(result['inserted'],3)
        self.assertEqual([x['business_param']['start_offset_time'] for x in requests],[0,0,30000])
        self.assertEqual([x['cursor'] for x in requests],['','c1','c2'])

    def test_raw_fields_revision_and_absent_identifiers(self):
        payload=fixture(mid=None);comment=payload['data']['data_list'][0]['comment']
        comment['common'].update({'create_time':'1793830101000','group_id':EID,'status':1})
        comment['source_identifier']='raw source';comment['stat']={'digg_count':0}
        self.assertEqual(self.import_fixture(payload)['inserted'],1)
        self.assertEqual(self.import_fixture(payload)['inserted'],0)
        comment['stat']['digg_count']=1
        self.assertEqual(self.import_fixture(payload)['updated'],1)
        with Store(self.path) as db:
            row=db.fetch('SELECT * FROM danmaku')[0]
            self.assertIsNone(row['message_id']);self.assertIsNone(row['posted_at'])
            self.assertEqual(json.loads(row['raw_json']),payload['data']['data_list'][0])
            self.assertEqual(json.loads(row['posting_time_raw_json'])['comment.common.create_time'],'1793830101000')
            self.assertEqual(db.fetch('SELECT count(*) n FROM native_danmaku_versions')[0]['n'],2)

    def test_json_cursor_and_terminal_false(self):
        from hongguo.native_runtime import request_after_page
        payload=fixture();payload['data']['common_list_info']={'has_more':'true','cursor':'{"end_offset_time":30000,"opaque":"keep"}'}
        _,page=parse_native_page(payload,self.req,SID,EID)
        request=request_after_page(self.req,page,0)
        self.assertEqual(request['body']['business_param']['start_offset_time'],30000)
        self.assertEqual(request['body']['cursor'],payload['data']['common_list_info']['cursor'])
        payload['data']['common_list_info']['has_more']='false'
        payload['data']['extra']={'next_query_danmaku_list_time':60000}
        _,page=parse_native_page(payload,self.req,SID,EID)
        self.assertIsNone(request_after_page(self.req,page,0))

    def test_unpublished_status_and_wrong_group_fail_closed(self):
        for fields in ({'status':0},{'status':True},{'group_id':'another episode'}):
            payload=fixture();payload['data']['data_list'][0]['comment']['common'].update(fields)
            self.assertEqual(self.import_fixture(payload)['status'],'blocked')

    def test_original_text_and_offset_fallback_preserved(self):
        payload=fixture(text='  SYNTHETIC\nTEXT  ');comment=payload['data']['data_list'][0]['comment']
        del comment['expand']['offset_time'];comment['offset_time']='1250'
        rows,_=parse_native_page(payload,self.req,SID,EID)
        self.assertEqual(rows[0]['text'],'  SYNTHETIC\nTEXT  ')
        self.assertEqual(rows[0]['playback_time_ms'],1250)
        self.assertEqual(rows[0]['offset_source'],'comment.offset_time')

    def test_stuck_cursor_stops_with_partial_failure(self):
        payload=fixture();payload['data']['common_list_info']['has_more']=True
        client=Mock();response=Mock();response.status_code=200
        response.iter_content.return_value=[json.dumps(payload).encode()]
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        client.s.post.return_value=response
        result=collect_native(self.path,drama_id=SID,episode_id=EID,outdir=self.root/'live',client=client)
        self.assertEqual(result['status'],'partial_failed')
        self.assertEqual(client.s.post.call_count,1)
