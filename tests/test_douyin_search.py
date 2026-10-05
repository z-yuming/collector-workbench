from __future__ import annotations

import unittest
from pathlib import Path

from social_crawler.platforms.douyin_search import extract_video_candidates


FIXTURE = Path(__file__).parent / "fixtures" / "douyin_search_video_results.xml"


class DouyinSearchTest(unittest.TestCase):
    def test_extracts_video_candidates_from_search_grid(self) -> None:
        xml = FIXTURE.read_text(encoding="utf-8")
        candidates = extract_video_candidates(xml)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].author_name, "浩浩然299")
        self.assertEqual(candidates[0].published_at, "06.25")
        self.assertEqual(candidates[0].like_count, "398")
        self.assertIn("Nike ACG", candidates[0].title)
        self.assertEqual(candidates[0].tap_x, 273)
        self.assertEqual(candidates[0].tap_y, 920)
        self.assertEqual(candidates[1].author_name, "葉子在跑了")
        self.assertEqual(candidates[1].like_count, "739")


if __name__ == "__main__":
    unittest.main()
