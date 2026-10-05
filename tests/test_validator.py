from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from social_crawler.exporters import export_result
from social_crawler.models import CollectionResult, CollectionTask, RunStat, SocialComment, SocialContent
from social_crawler.validator import validate_excel_export, write_validation_outputs


class ValidatorTest(unittest.TestCase):
    def test_validates_export_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw = root / "raw.xml"
            raw.write_text("<xml />", encoding="utf-8")
            result = CollectionResult(
                task=CollectionTask(platform="sample", task_type="keyword", query="nike"),
                contents=[SocialContent(platform="sample", title="content", raw_path=str(raw))],
                comments=[SocialComment(platform="sample", comment_text="comment", raw_path=str(raw))],
                run_stats=[RunStat(scope="test", name="collected_comments", value="1")],
            )
            target = root / "out.xlsx"
            export_result(result, target, ["excel"])

            report = validate_excel_export(target, require_comments=True)
            outputs = write_validation_outputs(report, target)

            self.assertTrue(report.ok)
            self.assertEqual(report.counts["contents"], 1)
            self.assertEqual(report.counts["comments"], 1)
            self.assertTrue(outputs["json"].exists())
            self.assertTrue(outputs["markdown"].exists())

    def test_fails_when_required_comments_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "out.xlsx"
            export_result(
                CollectionResult(
                    task=CollectionTask(platform="sample", task_type="keyword", query="nike"),
                    contents=[SocialContent(platform="sample", title="content")],
                    run_stats=[RunStat(scope="test", name="collected_contents", value="1")],
                ),
                target,
                ["excel"],
            )

            report = validate_excel_export(target, require_comments=True)

            self.assertFalse(report.ok)
            self.assertIn("comments sheet has 0 row(s), below minimum 1", "\n".join(report.errors))

    def test_fails_when_below_minimum_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "out.xlsx"
            export_result(
                CollectionResult(
                    task=CollectionTask(platform="sample", task_type="keyword", query="nike"),
                    contents=[SocialContent(platform="sample", title="content")],
                    comments=[SocialComment(platform="sample", comment_text="comment")],
                    run_stats=[RunStat(scope="test", name="collected_contents", value="1")],
                ),
                target,
                ["excel"],
            )

            report = validate_excel_export(target, min_contents=2, min_comments=2)

            self.assertFalse(report.ok)
            self.assertIn("contents sheet has 1 row(s), below minimum 2", "\n".join(report.errors))
            self.assertIn("comments sheet has 1 row(s), below minimum 2", "\n".join(report.errors))

    def test_warns_on_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "out.xlsx"
            export_result(
                CollectionResult(
                    task=CollectionTask(platform="sample", task_type="keyword", query="nike"),
                    contents=[SocialContent(platform="sample", title="content", raw_path=str(Path(temp_dir) / "missing.xml"))],
                    run_stats=[RunStat(scope="test", name="collected_contents", value="1")],
                ),
                target,
                ["excel"],
            )

            report = validate_excel_export(target)

            self.assertTrue(report.ok)
            self.assertEqual(len(report.evidence_missing), 1)
            self.assertTrue(report.warnings)


if __name__ == "__main__":
    unittest.main()
