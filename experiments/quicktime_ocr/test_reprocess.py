"""Synthetic invariants, separate from the manually reviewed research examples."""
import unittest
from reprocess import OfflineTracker, select_text


def obs(text, t, x, y=100, confidence=1):
    return dict(text=text, elapsed_ms=t, bbox=[x, y, len(text)*16, 20], confidence=confidence,
                region='danmaku_candidate', capture_timestamp='test', screenshot=f'{t}.png')


class ReprocessTests(unittest.TestCase):
    def test_consensus_does_not_prefer_longest_emoji_error(self):
        rows = [obs(s, i*333, 250-i*20) for i, s in enumerate(['剧情精彩','剧情精彩心','剧情精彩','剧情精彩c','剧情精彩'])]
        self.assertEqual(select_text(rows,486,20)['text'],'剧情精彩')

    def test_legitimate_han_suffix_is_preserved(self):
        for text in ['他很用心', '衣服颜色']:
            rows=[obs(text,i*333,250-i*20) for i in range(6)]
            self.assertEqual(select_text(rows,486,20)['text'],text)

    def test_background_prefix_loses_to_temporal_consensus(self):
        rows=[obs(s,i*333,250-i*20) for i,s in enumerate(['演技好','演技好','山演技好','演技好'])]
        self.assertEqual(select_text(rows,486,20)['text'],'演技好')

    def test_output_is_always_an_observed_string(self):
        rows=[obs(s,i*333,250-i*20) for i,s in enumerate(['剧情精采','剧情精彩呀','剧情精采','剧情精彩'])]
        self.assertIn(select_text(rows,486,20)['text'],[o['text'] for o in rows])

    def test_separate_simultaneous_and_later_events_survive(self):
        tracker=OfflineTracker(486,20)
        for base in [0,10000]:
            for i in range(4):
                detections=[obs('真的好看',base+i*333,100-i*18),obs('真的好看',base+i*333,300-i*18),
                            obs('真的好看',base+i*333,300-i*18,140)]
                tracker.update(dict(detections=detections,capture_elapsed_ms=base+i*333,capture_timestamp='test',screenshot=f'{base}-{i}.png'))
        tracker.stitch()
        self.assertEqual(len(tracker.accepted()),6)

    def test_split_trajectory_can_be_stitched(self):
        tracker=OfflineTracker(486,20)
        for times in [[0,333,666],[1665,1998,2331]]:
            rows=[obs('剧情精彩',t,300-t*.06) for t in times]
            tracker.tracks.append(dict(observations=rows,velocities=[-60,-60],motion_steps=2,leftward_px=40))
        tracker.stitch()
        self.assertEqual(len(tracker.accepted()),1)


if __name__=='__main__':unittest.main()
