import csv
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from hongguo.storage import Store
from hongguo.engagement import latest_changes,write_episode_status
from hongguo.media import validate_duration,media_destination,download_direct_file,import_media_manifest


class ValidationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'db.sqlite'
        with Store(self.path) as db:
            db.upsert_drama({'drama_id':'123','title':'UNIT TEST'})
            db.upsert_episode({'drama_id':'123','episode_id':'456','episode_number':1,'duration_seconds':60})

    def metric(self,**kwargs):
        return dict(drama_id='123',episode_id='456',scope='episode',metric='likes',value=0,
                    source='test',observed_at='2026-11-09T00:00:00Z',precision='exact',**kwargs)

    def test_metrics_dedup_observation_and_reject_scope_mismatch(self):
        with Store(self.path) as db:
            row=self.metric();self.assertTrue(db.add_metric(row))
            row['collected_at']='2026-11-09T01:00:00Z';self.assertFalse(db.add_metric(row))
            row['scope']='drama'
            with self.assertRaises(ValueError):db.add_metric(row)
            row['episode_id']=None;self.assertTrue(db.add_metric(row))
            self.assertFalse(db.add_metric(row))
            row['value']=2
            with self.assertRaises(ValueError):db.add_metric(row)
            self.assertEqual(db.count('engagement_snapshots'),2)
            self.assertEqual(db.fetch('SELECT raw_value FROM engagement_snapshots')[0]['raw_value'],'0')

    def test_latest_snapshot_uses_closest_24h_same_precision_source(self):
        rows=[]
        for day,value in [(6,1),(7,5),(8,10),(9,8)]:
            row=self.metric();row.update(observed_at=f'2026-11-{day:02d}T00:00:00Z',value=value);rows.append(row)
        mixed=dict(rows[-1],source='other',value=100);rows.append(mixed)
        rounded=dict(rows[-1],precision='rounded_display',value=200);rows.append(rounded)
        changes=latest_changes(rows)
        self.assertEqual(len(changes),1)
        self.assertEqual((changes[0]['before'],changes[0]['after'],changes[0]['delta']),(10,8,-2))
        self.assertTrue(changes[0]['counter_decreased'])

    def test_unknown_episode_metrics_are_not_zero(self):
        result=write_episode_status(self.path,self.root/'status')
        self.assertEqual(result['episode_metric_observations'],0)
        with (self.root/'status/episode_status.csv').open(encoding='utf-8-sig') as f:row=next(csv.DictReader(f))
        self.assertEqual(row['views_availability'],'unknown')

    def test_invalid_metrics_and_durations_are_rejected(self):
        with Store(self.path) as db:
            for value in ('-2','NaN','Infinity'):
                row=self.metric();row['value']=value
                with self.assertRaises(ValueError):db.add_metric(row)
                with self.assertRaises(ValueError):
                    db.upsert_episode({'drama_id':'123','episode_id':'456','duration_seconds':value})

    def test_duration_rejects_short_preview_nan_and_infinite(self):
        self.assertEqual(validate_duration(1,2),'mismatch')
        self.assertEqual(validate_duration(59.5,60),'matched')
        self.assertEqual(validate_duration(60,None),'reference_missing')
        for val in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):validate_duration(60,val)
            with self.assertRaises(ValueError):validate_duration(val,60)

    def test_path_traversal_is_rejected(self):
        for value in ('../outside','/tmp/bad','a/b',''):
            with self.assertRaises(ValueError):media_destination(self.root,value,'456','.mp4')

    def test_failed_download_preserves_existing_and_removes_partial(self):
        dest=self.root/'video.mp4';dest.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):download_direct_file('https://example.org/a.mp4',dest,allowed_hosts={'example.org'})
        self.assertEqual(dest.read_bytes(),b'existing')
        response=Mock();response.status_code=200
        response.headers={'Content-Type':'video/mp4','Content-Length':'100'}
        response.iter_content.return_value=[b'truncated']
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('hongguo.media.requests.get',return_value=response),patch('time.sleep'):
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                download_direct_file('https://example.org/a.mp4',self.root/'new.mp4',allowed_hosts={'example.org'})
        self.assertFalse((self.root/'new.mp4').exists())
        self.assertEqual(list(self.root.glob('*.part')),[])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg required')
    def test_media_preserves_reference_duration_and_revalidates_asset(self):
        video=self.root/'unit.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'color=c=blue:s=128x128:r=10','-t','2','-c:v','mpeg4','-y',str(video)],check=True,timeout=15)
        manifest=self.root/'manifest.csv'
        def run(expected):
            manifest.write_text('drama_id,episode_id,local_path,rights_confirmed,is_full_episode,expected_duration_seconds\n'
                                +f'123,456,{video},true,true,{expected}\n')
            return import_media_manifest(manifest,self.path,media_root=self.root/'media')
        self.assertEqual(run(60)['full_verified'],0)
        # A manifest cannot override contradictory source metadata silently.
        self.assertEqual(run(2)['full_verified'],0)
        with Store(self.path) as db:
            self.assertEqual(db.fetch('SELECT duration_validation FROM episodes')[0]['duration_validation'],'reference_conflict')
            db.upsert_episode({'drama_id':'123','episode_id':'456','duration_seconds':2})
        self.assertEqual(run(2)['full_verified'],1)
        with Store(self.path) as db:
            ep=db.fetch('SELECT * FROM episodes')[0]
            self.assertEqual(ep['duration_seconds'],2)
            self.assertEqual(ep['media_duration_seconds'],2)
            self.assertEqual(ep['duration_validation'],'matched')
            self.assertEqual(db.fetch('SELECT verified_full FROM assets')[0]['verified_full'],1)
