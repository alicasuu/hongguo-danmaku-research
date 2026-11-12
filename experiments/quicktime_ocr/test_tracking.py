"""Synthetic tracker checks only; these fixtures are never research observations."""
import unittest
import tempfile
import json
import csv
from pathlib import Path
from types import SimpleNamespace
from collect import Tracker, export


def box(text, x, y=115, region='danmaku_candidate'):
    return dict(text=text, bbox=[x, y, 75, 18], region=region, confidence=.5)


class TrackingTests(unittest.TestCase):
    def test_stationary_text_and_subtitles_are_excluded(self):
        tracker = Tracker()
        for n in range(5):
            tracker.update([box('固定菜单文字', 100), box('这是一行字幕', 200 - n * 20, 700,
                            'outside_danmaku_region')], n * 333, 'time', f'{n}.png', 406)
        self.assertEqual(tracker.records(None, None), [])

    def test_same_text_on_two_lanes_is_two_messages(self):
        tracker = Tracker()
        for n in range(4):
            tracker.update([box('秘书真好看', 200 - n * 20), box('秘书真好看', 250 - n * 20, 145)],
                           n * 333, 'time', f'{n}.png', 406)
        rows = tracker.records(None, None)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['observations'] == 4 for r in rows))
        self.assertTrue(all(r['estimated_playback_offset_ms'] is None for r in rows))
        self.assertTrue(all(r['native_message_id'] is None for r in rows))

    def test_clipped_text_matches_without_inventing_text(self):
        tracker = Tracker()
        for n, text in enumerate(['秘书真好看', '秘书真好看', '秘书真好看呀']):
            tracker.update([box(text, 300 - n * 20)], 1000 + n * 333, 'time', f'{n}.png', 406)
        row, = tracker.records('confirmed-id', 5000)
        self.assertEqual(row['text'], '秘书真好看呀')
        self.assertEqual(row['estimated_playback_offset_ms'], 6000)
        self.assertEqual(len(row['text_variants']), 2)

    def test_reappearance_after_gap_is_not_globally_deduplicated(self):
        tracker = Tracker()
        for base in (0, 5000):
            for n in range(3):
                tracker.update([box('秘书真好看', 200 - n * 20)], base + n * 333,
                               'time', f'{base}-{n}.png', 406)
        self.assertEqual(len(tracker.records(None, None)), 2)

    def test_export_preserves_unknown_times_and_original_variants(self):
        tracker = Tracker()
        for n in range(3):
            tracker.update([box('秘书真好看', 200 - n * 20)], n * 333, 'time', f'{n}.png', 406)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            export(folder, tracker, SimpleNamespace(episode_id=None, playback_start_ms=None), {'status': 'test'})
            record = json.loads((folder / 'danmaku_live.json').read_text())['records'][0]
            self.assertIsNone(record['estimated_playback_offset_ms'])
            self.assertIsNone(record['platform_offset_time_ms'])
            self.assertEqual(record['text_variants'], ['秘书真好看'])
            with (folder / 'danmaku_live.csv').open(encoding='utf-8-sig') as f:
                row, = list(csv.DictReader(f))
                self.assertEqual(row['text'], '秘书真好看')
                self.assertEqual(row['estimated_playback_offset_ms'], '')


if __name__ == '__main__':
    unittest.main()
