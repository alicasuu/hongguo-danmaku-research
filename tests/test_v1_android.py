import csv
import io
import tempfile
import unittest
from pathlib import Path

from hongguo.v1_android import chinese_number, load_frozen, parse_ui, node_bounds, matched_node, append_rows, audit
from hongguo.v1_ocr import EpisodeOCRTracker, group_tesseract_tsv


class V1InitialTests(unittest.TestCase):
    def test_frozen_exactly_ten_and_999(self):
        series, episodes = load_frozen()
        self.assertEqual((len(series), len(episodes)), (10, 999))
        self.assertEqual(episodes[0]["episode_no"], "1")

    def test_xml_clickable_label(self):
        xml = '<hierarchy><node text="减肥系男神，减一斤一个亿" bounds="[10,20][90,80]" /></hierarchy>'
        self.assertEqual(node_bounds(matched_node(parse_ui(xml), "减肥系男神，减一斤一个亿")), (10, 20, 90, 80))

    def test_duplicates_same_time_window(self):
        tracker = EpisodeOCRTracker()
        row = {"text":"太精彩了！", "confidence":94, "bbox":(4,5,6,7)}
        self.assertEqual(len(tracker.ingest(700, [row], "a.png")), 1)
        self.assertEqual(len(tracker.ingest(1500, [row], "b.png")), 0)
        self.assertEqual(len(tracker.ingest(12000, [row], "c.png")), 1)

    def test_moving_text_clipping_repairs_to_full_text(self):
        tracker = EpisodeOCRTracker()
        first = {"text":"你怀里的玩偶", "confidence":85, "bbox":(900, 300, 1070, 342)}
        second = {"text":"你怀里的玩偶也很有特色", "confidence":92, "bbox":(120, 302, 1010, 345)}
        self.assertEqual(len(tracker.ingest(500, [first], "frame_1.png")), 1)
        self.assertEqual(len(tracker.ingest(1350, [second], "frame_2.png")), 0)
        self.assertEqual(len(tracker.items), 1)
        self.assertEqual(tracker.items[0].text, second["text"])
        self.assertEqual(tracker.items[0].first_seen_ms, 500)
        self.assertEqual(tracker.items[0].screenshot, "frame_2.png")

    def test_player_controls_excluded_from_danmaku(self):
        from hongguo.v1_ocr import is_valid_danmaku_text
        self.assertFalse(is_valid_danmaku_text("第1集"))
        self.assertFalse(is_valid_danmaku_text("1.0x"))

    def test_search_result_cannot_be_echo_of_our_query(self):
        from unittest.mock import patch
        from hongguo.v1_android import search_result_ocr_candidates
        mock_rows = [
            {"text":"减肥系男神减一斤一个亿", "confidence":85, "bbox":(10, 170, 600, 220)},
            {"text":"减肥系男神减", "confidence":75, "bbox":(30, 1760, 320, 1800)},
        ]
        with patch('hongguo.v1_android.tesseract_tsv', return_value='stub'):
            with patch('hongguo.v1_android.group_tesseract_tsv', return_value=mock_rows):
                result = search_result_ocr_candidates(Path('unused.png'), '减肥系男神，减一斤一个亿')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['center'], (175,1780))

    def test_navigation_ocr_never_taps_combined_tab_row(self):
        from unittest.mock import patch
        from hongguo.v1_android import visible_navigation_ocr
        rows = [
            {"text":"首页剧场", "confidence":75, "bbox":(15,2200,900,2280)},
            {"text":"找剧", "confidence":91, "bbox":(700,90,800,145)},
        ]
        with patch('hongguo.v1_android.tesseract_tsv', return_value='tsv'):
            with patch('hongguo.v1_android.group_tesseract_tsv', return_value=rows):
                result = visible_navigation_ocr(Path('unused.png'))
        self.assertEqual(result, [{"label":"找剧", "bbox":[700,90,800,145],
                                   "center":[750,117]}])

    def test_metrics_count_scaling(self):
        self.assertEqual(chinese_number("12.5万"), "125000")
        self.assertEqual(chinese_number("隐藏"), "")

    def test_csv_audit_never_fabricates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for kind in ["episodes", "danmaku", "metrics", "comments"]:
                append_rows(path / f"{kind}.csv", kind, [])
            append_rows(path / "episodes.csv", "episodes", [{"snapshot":"V1_initial", "status":"failed", "full_video_verified":False}])
            report = audit(path, {"next_index": 1})
            self.assertEqual(report["ocr_danmaku_candidates"], 0)
            self.assertFalse(report["all_successfully_collected"])


if __name__ == "__main__":
    unittest.main()
