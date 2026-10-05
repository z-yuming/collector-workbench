from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from social_crawler.exporters import export_result
from social_crawler.models import CollectionResult, CollectionTask, RunStat, SocialComment, SocialContent


class ExportersTest(unittest.TestCase):
    def test_excel_export_includes_run_stats_sheet(self) -> None:
        result = CollectionResult(
            task=CollectionTask(platform="sample", task_type="keyword", query="nike"),
            contents=[
                SocialContent(
                    platform="sample",
                    keyword="nike",
                    title="content",
                    raw_path="data/raw/content.xml",
                    screenshot_path="data/screenshots/content.png",
                )
            ],
            comments=[SocialComment(platform="sample", comment_text="comment", raw_path="data/raw/comment.xml")],
            run_stats=[
                RunStat(scope="keyword_video", name="collected_comments", value="1"),
                RunStat(scope="keyword_video", name="failed_candidates", value="0"),
                RunStat(scope="keyword_video", name="checkpoint_path", value="data/logs/checkpoints/sample.json"),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "out.xlsx"
            export_result(result, target, ["excel", "jsonl", "report"])

            stats = pd.read_excel(target, sheet_name="run_stats")
            self.assertEqual(stats.loc[0, "scope"], "keyword_video")
            self.assertEqual(stats.loc[0, "name"], "collected_comments")

            jsonl = target.with_suffix(".jsonl").read_text(encoding="utf-8")
            self.assertIn('"type": "run_stat"', jsonl)

            report = target.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("# Collection Run Report", report)
            self.assertIn("- Contents: 1", report)
            self.assertIn("- Comments: 1", report)
            self.assertIn("- Failed candidates: 0", report)
            self.assertIn("- Checkpoint: data/logs/checkpoints/sample.json", report)
            self.assertIn("data/raw/content.xml", report)


if __name__ == "__main__":
    unittest.main()
