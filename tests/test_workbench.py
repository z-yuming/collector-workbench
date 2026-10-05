from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from social_crawler import workbench
from social_crawler.settings import Settings


class WorkbenchTest(unittest.TestCase):
    def test_combined_history_pages_and_filters_preserve_each_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(log_dir=root / "logs")
            settings.log_dir.mkdir()
            primary = [{"id": "primary", "createdAt": "2026-10-01", "ok": True}]
            with closing(sqlite3.connect(root / "data.db")) as database:
                for table in ["scrape_history", "crawler_jobs"]:
                    database.execute(f"CREATE TABLE {table} (id INTEGER, created_at TEXT, platform TEXT, keyword TEXT, status TEXT, item_count INTEGER)")
                    database.execute(f"INSERT INTO {table} VALUES (1, '2026-10-02', 'taobao', 'local fixture', 'success', 3)")
                database.commit()
            (settings.log_dir / "workbench-video-history.jsonl").write_text(json.dumps({"id": "video", "createdAt": "2026-10-03", "source": "video"}) + "\nbroken\n", encoding="utf-8")
            with patch.object(workbench, "SCRAPER_ROOT", root), patch.object(workbench, "VIDEO_ROOT", root):
                first = workbench.combined_history(primary, settings, 0, 2)
                second = workbench.combined_history(primary, settings, 1, 2)
                videos = workbench.combined_history(primary, settings, 0, 8, "video")
            self.assertEqual(first["total"], 4)
            self.assertEqual(first["sourceCounts"], {"collect": 1, "scraper": 2, "video": 1})
            self.assertEqual(len({item["id"] for item in first["items"] + second["items"]}), 4)
            self.assertEqual(videos["total"], 1)
            self.assertEqual(videos["items"][0]["source"], "video")

    def test_existing_video_files_remain_downloadable_without_moving_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "downloads"
            downloads.mkdir()
            saved = downloads / "existing.mp4"
            saved.write_bytes(b"local media fixture")
            (downloads / "ignore.txt").write_text("local", encoding="utf-8")
            with patch.object(workbench, "VIDEO_ROOT", root), patch.object(workbench, "SCRAPER_ROOT", root):
                result = workbench.combined_history([], Settings(log_dir=root / "logs"), 0, 8, "video")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["taskType"], "saved_media")
            self.assertEqual(result["items"][0]["downloadLinks"]["existing.mp4"], "/api/workbench/video-file/existing.mp4")
            self.assertTrue(saved.exists())

    def test_video_link_validation_never_starts_invalid_commands(self):
        with patch.object(workbench.subprocess, "run") as run:
            for url in ["https://example.com/video", "https://douyin.com.example.com/video", "https://name:secret@www.douyin.com/video/1", "file:///D:/video.mp4"]:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    workbench.run_video({"action": "parse", "url": url}, Settings())
            with self.assertRaises(ValueError):
                workbench.run_video({"action": "batch", "url": "https://www.douyin.com/video/1"}, Settings())
            run.assert_not_called()

    def test_video_parse_returns_only_metadata_and_records_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python.exe"
            python.touch()
            (root / "hermes_douyin.py").touch()
            settings = Settings(log_dir=root / "logs")
            process = SimpleNamespace(returncode=0, stdout='Starting parser\n' + json.dumps({"aweme_id": "1", "desc": "Demo", "author_nickname": "Creator", "image_count": 2, "cookie": "credential must stay private"}))
            with patch.object(workbench, "VIDEO_ROOT", root), patch.object(workbench, "VIDEO_PYTHON", python), patch.object(workbench.subprocess, "run", return_value=process) as run:
                result = workbench.run_video({"action": "parse", "url": "分享 https://www.douyin.com/video/1"}, settings)
            self.assertEqual(result["metadata"], {"aweme_id": "1", "desc": "Demo", "author_nickname": "Creator", "image_count": 2})
            self.assertEqual(run.call_args.args[0][2], "meta")
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertNotIn("credential", (settings.log_dir / "workbench-video-history.jsonl").read_text(encoding="utf-8"))

    def test_video_download_requires_existing_nonempty_file_inside_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python.exe"
            python.touch()
            (root / "hermes_douyin.py").touch()
            (root / "downloads").mkdir()
            saved = root / "downloads" / "video.mp4"
            saved.write_bytes(b"local media fixture")
            settings = Settings(log_dir=root / "logs")
            with patch.object(workbench, "VIDEO_ROOT", root), patch.object(workbench, "VIDEO_PYTHON", python), patch.object(workbench.subprocess, "run") as run:
                run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps({"status": "downloaded", "path": str(saved), "meta": {"desc": "Demo"}}))
                result = workbench.run_video({"action": "download", "url": "https://www.douyin.com/video/1"}, settings)
                self.assertEqual(result["downloadLinks"]["video.mp4"], "/api/workbench/video-file/video.mp4")
                run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps({"status": "downloaded", "files": ["FAIL:remote_url"]}))
                with self.assertRaises(RuntimeError):
                    workbench.run_video({"action": "download", "url": "https://www.douyin.com/video/1"}, settings)

    def test_video_files_cannot_escape_download_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "private.txt").write_text("local", encoding="utf-8")
            with patch.object(workbench, "VIDEO_ROOT", root), self.assertRaises(ValueError):
                workbench.video_file("../private.txt")


if __name__ == "__main__":
    unittest.main()
