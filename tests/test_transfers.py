"""Synthetic transport bytes test HTTP correctness, never live media coverage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import requests
from hongguo.transfers import download_resumable
from hongguo.util import stable_hash

URL='https://example.org/test.mp4'

def response(code,body,**headers):
    r=Mock();r.status_code=code;r.headers={'Content-Type':'video/mp4',**headers}
    r.iter_content.return_value=body
    r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
    return r


class TransferTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.dest=Path(tmp.name)/'test.mp4';self.session=Mock();self.verify=Mock()
        self.patch=patch('hongguo.transfers.validate_public_http_url');self.patch.start();self.addCleanup(self.patch.stop)

    def run_transfer(self,**kwargs):
        return download_resumable(URL,self.dest,allowed_hosts={'example.org'},max_bytes=100,
            session=self.session,sleep=Mock(),verify=self.verify,**kwargs)

    def seed(self):
        self.dest.with_suffix('.mp4.part').write_bytes(b'abc')
        self.dest.with_suffix('.mp4.transfer.json').write_text(json.dumps({'url_hash':stable_hash(URL),'validator':'"v1"','total':6}))

    def test_resume_exact_range(self):
        self.seed();self.session.get.return_value=response(206,[b'def'],**{'Content-Range':'bytes 3-5/6','Content-Length':'3','ETag':'"v1"'})
        self.run_transfer();self.assertEqual(self.dest.read_bytes(),b'abcdef')
        self.assertEqual(self.session.get.call_args.kwargs['headers']['If-Range'],'"v1"')
        self.verify.assert_called_once()

    def test_ignored_range_restarts(self):
        self.seed();self.session.get.return_value=response(200,[b'new'],**{'Content-Length':'3','ETag':'"v2"'})
        self.run_transfer();self.assertEqual(self.dest.read_bytes(),b'new')

    def test_bad_range_changed_validator_and_416_never_publish(self):
        for code,headers in [(206,{'Content-Range':'bytes 0-2/3','ETag':'"v1"'}),
                             (206,{'Content-Range':'bytes 3-5/6','ETag':'"v2"'}),(416,{})]:
            self.seed();self.session.get.return_value=response(code,[b'def'],**headers)
            with self.assertRaises(ValueError):self.run_transfer()
            self.assertFalse(self.dest.exists())

    def test_denials_are_not_retried(self):
        for code in (401,403,429,302):
            self.session.reset_mock();self.session.get.return_value=response(code,[])
            with self.assertRaises(PermissionError):self.run_transfer()
            self.assertEqual(self.session.get.call_count,1)

    def test_interruption_resumes_and_decode_failure_never_publishes(self):
        def interrupted():
            yield b'abc'
            raise requests.ConnectionError('test only')
        self.session.get.side_effect=[response(200,interrupted(),**{'Content-Length':'6','ETag':'"v1"'}),
            response(206,[b'def'],**{'Content-Range':'bytes 3-5/6','Content-Length':'3','ETag':'"v1"'})]
        self.verify.side_effect=ValueError('test decode failure')
        with self.assertRaises(ValueError):self.run_transfer()
        self.assertFalse(self.dest.exists());self.assertEqual(self.dest.with_suffix('.mp4.part').read_bytes(),b'abcdef')

    def test_existing_media_untouched(self):
        self.dest.write_bytes(b'original')
        with self.assertRaises(FileExistsError):self.run_transfer()
        self.assertEqual(self.dest.read_bytes(),b'original');self.session.get.assert_not_called()
