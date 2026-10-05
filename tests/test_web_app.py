from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from social_crawler.settings import Settings
from social_crawler.models import CollectionResult, CollectionTask, SocialComment, SocialContent
from social_crawler.web_app import (
    build_task,
    parse_adb_devices,
    parse_formats,
    preview_result,
    read_history,
    run_collection,
    split_batch_queries,
    friendly_error,
    quality_summary,
    record_failure,
    tap_device,
    video_helper_items,
    video_helper_download,
    history_pagination,
    read_history_paginated,
    history_path,
)


class WebAppTest(unittest.TestCase):
    def test_history_pages_preserve_all_valid_records(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(log_dir=Path(temp_dir))
            lines = [json.dumps({"id": index}) for index in range(19)]
            history_path(settings).write_text("\n".join(lines + ["broken record"]), encoding="utf-8")
            pages = [read_history_paginated(settings, page, 8) for page in range(3)]
            self.assertEqual([total for _, total in pages], [19, 19, 19])
            self.assertEqual([row["id"] for rows, _ in pages for row in rows], list(reversed(range(19))))

    def test_history_pagination_rejects_invalid_requests(self) -> None:
        for query in ["page=-1", "page=not-a-number", "limit=0", "limit=-2", "limit=1.5"]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                history_pagination(query)
        self.assertEqual(history_pagination("page=2&limit=999"), (2, 100))

    def test_strict_comment_failure_is_not_reported_as_success(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(project_root=root, output_dir=root / "exports", log_dir=root / "logs")
            settings.ensure_dirs()
            payload = {"platform": "sample", "mode": "sample", "taskType": "content", "query": "strict_local_check", "comments": True, "strictComments": True, "minComments": 0, "checkEvidence": False}
            with patch("social_crawler.web_app.get_collector") as get_mock:
                get_mock.return_value.collect.return_value = CollectionResult(
                    task=build_task(payload, settings),
                    contents=[SocialContent(platform="sample", title="Visible content", like_count="10")],
                    comments=[],
                )
                response = run_collection(payload, settings)
            self.assertTrue(response["validation"]["ok"])
            self.assertEqual(response["quality"]["status"], "failed")
            self.assertFalse(response["ok"])
            self.assertFalse(read_history(settings)[0]["ok"])
            self.assertIn("excel", response["downloadLinks"])

    def test_build_task_from_payload(self) -> None:
        task = build_task(
            {
                "platform": "sample",
                "mode": "sample",
                "taskType": "keyword",
                "query": "nike",
                "limit": 2,
                "comments": True,
                "maxComments": 3,
                "maxPages": 4,
                "resume": True,
            },
            Settings(),
        )

        self.assertEqual(task.platform, "sample")
        self.assertEqual(task.query, "nike")
        self.assertEqual(task.limit, 2)
        self.assertTrue(task.collect_comments)
        self.assertEqual(task.max_comments_per_item, 3)
        self.assertEqual(task.max_pages, 4)
        self.assertTrue(task.resume)

    def test_build_task_keeps_zero_max_comments(self) -> None:
        task = build_task(
            {
                "platform": "sample",
                "mode": "sample",
                "taskType": "content",
                "query": "demo",
                "comments": False,
                "maxComments": 0,
            },
            Settings(),
        )

        self.assertEqual(task.max_comments_per_item, 0)

    def test_parse_formats(self) -> None:
        self.assertEqual(parse_formats("excel,jsonl, report"), ["excel", "jsonl", "report"])

    def test_run_collection_returns_download_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                project_root=root,
                output_dir=root / "exports",
                log_dir=root / "logs",
                screenshot_dir=root / "screenshots",
                raw_dir=root / "raw",
                default_serial=None,
            )
            settings.ensure_dirs()
            response = run_collection(
                {
                    "platform": "sample",
                    "mode": "sample",
                    "taskType": "keyword",
                    "query": "ui_test",
                    "comments": True,
                    "minContents": 1,
                    "minComments": 1,
                    "formats": "excel,jsonl,report",
                },
                settings,
            )

            self.assertTrue(response["ok"])
            self.assertEqual(response["counts"]["contents"], 1)
            self.assertIn("excel", response["downloadLinks"])
            self.assertIn("validation_markdown", response["downloadLinks"])
            self.assertIn("preview", response)
            self.assertEqual(response["preview"]["contents"][0]["title"], "Sample public content for ui_test")
            self.assertEqual(len(read_history(settings)), 1)
            self.assertIn("quality", read_history(settings)[0])
            self.assertIn("payload", read_history(settings)[0])

    def test_preview_result(self) -> None:
        task = CollectionTask(platform="sample", task_type="content", query="demo")
        result = CollectionResult(
            task=task,
            contents=[
                SocialContent(
                    platform="sample",
                    title="Video title",
                    author_name="Author",
                    like_count="12",
                    comment_count="3",
                )
            ],
            comments=[SocialComment(platform="sample", comment_author="Alice", comment_text="Nice", comment_likes="2")],
        )

        preview = preview_result(result)

        self.assertEqual(preview["contents"][0]["title"], "Video title")
        self.assertEqual(preview["contents"][0]["author"], "Author")
        self.assertEqual(preview["comments"][0]["text"], "Nice")

    def test_preview_result_includes_product_fields(self) -> None:
        task = CollectionTask(platform="douyin", task_type="products", query="nike")
        result = CollectionResult(
            task=task,
            contents=[
                SocialContent(
                    platform="douyin",
                    title="Nike shoe",
                    product_title="Nike shoe",
                    product_price="199",
                    product_original_price="299",
                    product_pay_count="1万+人付款",
                    product_shop_name="Nike旗舰店",
                )
            ],
        )

        preview = preview_result(result)

        self.assertEqual(preview["contents"][0]["productTitle"], "Nike shoe")
        self.assertEqual(preview["contents"][0]["productPrice"], "199")
        self.assertEqual(preview["contents"][0]["productPayCount"], "1万+人付款")

    def test_parse_adb_devices(self) -> None:
        devices = parse_adb_devices("List of devices attached\nemulator-5554\tdevice\nabc123\toffline\n")

        self.assertEqual(devices[0], {"serial": "emulator-5554", "state": "device"})
        self.assertEqual(devices[1], {"serial": "abc123", "state": "offline"})

    def test_split_batch_queries(self) -> None:
        queries = split_batch_queries("复制分享 https://v.douyin.com/a/，\nhttps://v.douyin.com/b/\nhttps://v.douyin.com/a/")

        self.assertEqual(queries, ["https://v.douyin.com/a/", "https://v.douyin.com/b/"])

    def test_video_helper_items_normalizes_latest_capture(self) -> None:
        items = video_helper_items(
            {
                "state": {
                    "items": [
                        {
                            "url": "https://example.com/video.mp4",
                            "pageTitle": "Demo video",
                            "contentType": "video/mp4",
                            "kind": "video",
                            "contentLength": 1024,
                        }
                    ]
                }
            }
        )

        self.assertEqual(items[0]["index"], 0)
        self.assertEqual(items[0]["url"], "https://example.com/video.mp4")
        self.assertEqual(items[0]["pageTitle"], "Demo video")
        self.assertEqual(items[0]["contentLength"], 1024)

    def test_video_helper_excludes_source_files_and_api_responses(self) -> None:
        captures = [
            {"url": "http://localhost/api/projects", "contentType": "application/json", "kind": "video"},
            {"url": "https://example.com/video.mp4", "contentType": "video/mp4"},
            {"url": "http://localhost/Component.tsx", "contentType": "text/javascript", "kind": "segment"},
            {"url": "https://example.com/stream?id=1", "contentType": "application/vnd.apple.mpegurl"},
            {"url": "https://example.com/chunk?id=2", "contentType": "application/octet-stream", "kind": "segment"},
            {"url": "https://example.com/login.mp4", "contentType": "text/html"},
            {"url": "https://example.com/Component.tsx", "kind": "segment"},
            {"contentType": "video/mp4"},
        ]
        items = video_helper_items({"state": {"items": captures}})
        self.assertEqual([item["index"] for item in items], [1, 3, 4])

    def test_video_helper_download_rejects_non_media_and_invalid_selection(self) -> None:
        from unittest.mock import patch

        captures = [
            {"url": "http://localhost/api/projects", "contentType": "application/json"},
            {"url": "https://example.com/video.mp4", "contentType": "video/mp4"},
        ]
        with patch("social_crawler.web_app.is_port_open", return_value=True), \
             patch("social_crawler.web_app.read_video_helper_latest", return_value={"state": {"items": captures}}), \
             patch("social_crawler.web_app.post_video_helper") as send:
            for index in [0, -1, 99, "invalid", None]:
                with self.subTest(index=index), self.assertRaises(RuntimeError):
                    video_helper_download({"index": index})
            send.assert_not_called()

    def test_video_helper_download_preserves_capture_index_and_filters_segments(self) -> None:
        from unittest.mock import patch

        non_media = {"url": "http://localhost/api/projects", "contentType": "application/json"}
        media = {"url": "https://example.com/video.mp4", "contentType": "video/mp4", "pageTitle": "Demo"}
        with patch("social_crawler.web_app.is_port_open", return_value=True), \
             patch("social_crawler.web_app.read_video_helper_latest", return_value={"state": {"items": [non_media, media]}}), \
             patch("social_crawler.web_app.video_helper_status", return_value={}), \
             patch("social_crawler.web_app.post_video_helper", return_value={"ok": True}) as send:
            result = video_helper_download({"index": 1})
        self.assertTrue(result["ok"])
        self.assertEqual(send.call_args.args[1]["selected"], media)
        self.assertEqual(send.call_args.args[1]["items"], [media])

    def test_run_batch_collection_combines_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                project_root=root,
                output_dir=root / "exports",
                log_dir=root / "logs",
                screenshot_dir=root / "screenshots",
                raw_dir=root / "raw",
                default_serial=None,
            )
            settings.ensure_dirs()

            response = run_collection(
                {
                    "platform": "sample",
                    "mode": "sample",
                    "taskType": "content",
                    "query": "one\ntwo",
                    "comments": True,
                    "batchLinks": True,
                    "minContents": 2,
                    "minComments": 2,
                    "formats": "excel,jsonl,report",
                    "checkEvidence": False,
                },
                settings,
            )

            self.assertTrue(response["ok"])
            self.assertEqual(response["counts"]["contents"], 2)
            self.assertEqual(response["counts"]["comments"], 2)
            self.assertIn("批量链接 2 条", read_history(settings)[0]["query"])

    def test_friendly_error(self) -> None:
        self.assertIn("没有检测到", friendly_error("device offline"))

    def test_quality_summary_warns_without_failing_comments(self) -> None:
        task = CollectionTask(platform="douyin", task_type="content", query="demo")
        result = CollectionResult(
            task=task,
            contents=[SocialContent(platform="douyin", title="发布时间：3天前", like_count="10")],
        )

        quality = quality_summary(result, {"comments": True}, validation_ok=True)

        self.assertEqual(quality["status"], "warning")
        self.assertEqual(quality["label"], "需确认")
        self.assertTrue(quality["contentOk"])
        self.assertFalse(quality["commentsOk"])

    def test_quality_summary_strict_comments_fails_without_comments(self) -> None:
        task = CollectionTask(platform="douyin", task_type="content", query="demo")
        result = CollectionResult(task=task, contents=[SocialContent(platform="douyin", title="Video", like_count="10")])

        quality = quality_summary(result, {"comments": True, "strictComments": True}, validation_ok=True)

        self.assertEqual(quality["status"], "failed")
        self.assertEqual(quality["label"], "失败")

    def test_quality_summary_products_uses_product_fields(self) -> None:
        task = CollectionTask(platform="douyin", task_type="products", query="nike")
        result = CollectionResult(
            task=task,
            contents=[SocialContent(platform="douyin", product_title="Nike shoe", product_price="199")],
        )

        quality = quality_summary(result, {"taskType": "products", "comments": False}, validation_ok=True)

        self.assertEqual(quality["status"], "ok")
        self.assertEqual(quality["label"], "可用")
        self.assertTrue(quality["contentOk"])

    def test_quality_summary_products_warns_without_price(self) -> None:
        task = CollectionTask(platform="douyin", task_type="products", query="nike")
        result = CollectionResult(task=task, contents=[SocialContent(platform="douyin", title="Nike shoe")])

        quality = quality_summary(result, {"taskType": "products", "comments": False}, validation_ok=True)

        self.assertEqual(quality["status"], "warning")
        self.assertIn("商品", quality["warnings"][0])

    def test_quality_summary_products_explains_empty_result(self) -> None:
        task = CollectionTask(platform="douyin", task_type="products", query="nike")
        result = CollectionResult(task=task)

        quality = quality_summary(result, {"taskType": "products", "comments": False}, validation_ok=False)

        self.assertEqual(quality["status"], "failed")
        self.assertIn("没有采到商品数据", quality["warnings"][0])

    def test_tap_device_without_serial(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                project_root=root,
                adb_path=root / "missing-adb.exe",
                output_dir=root / "exports",
                log_dir=root / "logs",
                screenshot_dir=root / "screenshots",
                raw_dir=root / "raw",
                default_serial=None,
            )

            response = tap_device(settings, {"x": 10, "y": 20})

            self.assertFalse(response["ok"])
            self.assertIn("没有检测到", response["message"])

    def test_record_failure_writes_retry_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                project_root=root,
                output_dir=root / "exports",
                log_dir=root / "logs",
                screenshot_dir=root / "screenshots",
                raw_dir=root / "raw",
                default_serial=None,
            )
            settings.ensure_dirs()

            item = record_failure(
                settings,
                {"platform": "douyin", "mode": "ui", "taskType": "content", "query": "bad-link"},
                RuntimeError("device offline"),
            )

            self.assertFalse(item["ok"])
            self.assertEqual(item["quality"]["status"], "failed")
            self.assertEqual(read_history(settings)[0]["payload"]["query"], "bad-link")


if __name__ == "__main__":
    unittest.main()
