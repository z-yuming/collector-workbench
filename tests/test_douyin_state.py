from __future__ import annotations

import unittest
from pathlib import Path

from social_crawler.platforms.douyin_state import detect_page_state


FIXTURES = Path(__file__).parent / "fixtures"


class DouyinStateTest(unittest.TestCase):
    def test_detects_search_results(self) -> None:
        xml = (FIXTURES / "douyin_search_video_results.xml").read_text(encoding="utf-8")
        self.assertEqual(detect_page_state(xml), "search_results")

    def test_detects_comment_panel(self) -> None:
        xml = (FIXTURES / "douyin_comment_panel_sequence.xml").read_text(encoding="utf-8")
        self.assertEqual(detect_page_state(xml), "comment_panel")

    def test_detects_video_detail(self) -> None:
        xml = (FIXTURES / "douyin_video_detail.xml").read_text(encoding="utf-8")
        self.assertEqual(detect_page_state(xml), "video_detail")

    def test_detects_launching(self) -> None:
        xml = (FIXTURES / "douyin_launching.xml").read_text(encoding="utf-8")
        self.assertEqual(detect_page_state(xml), "launching")


if __name__ == "__main__":
    unittest.main()
