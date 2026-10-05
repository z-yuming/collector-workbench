from __future__ import annotations

from social_crawler.task_progress import report as report_progress

import time
import subprocess
from pathlib import Path

from douyin_crawler.device import DouyinDevice
from douyin_crawler.ui_scraper import extract_visible_products
from social_crawler.checkpoint import load_checkpoint, save_checkpoint
from social_crawler.models import CollectionResult, CollectionTask, RunStat, SocialComment, SocialContent
from social_crawler.platforms.base import PlatformCollector
from social_crawler.platforms.douyin_parser import (
    extract_comments_from_xml,
    extract_public_content_from_xml,
    has_comment_panel,
)
from social_crawler.platforms.douyin_search import SearchResultCandidate, extract_video_candidates
from social_crawler.platforms.douyin_state import detect_page_state


class DouyinUiCollector(PlatformCollector):
    def collect(self, task: CollectionTask) -> CollectionResult:
        platform_settings = self.settings.platform("douyin")
        package_name = platform_settings.package_name or "com.ss.android.ugc.aweme"
        device = DouyinDevice(self._resolve_serial(task), package_name)

        result = CollectionResult(task=task)
        device.prepare()

        if task.task_type in ("content", "comments"):
            if task.query.startswith(("http://", "https://")):
                device.open_url(task.query)
            xml = device.d.dump_hierarchy()
            raw_path = self._write_raw(task, 0, xml)
            screenshot_path = self._screenshot(device, task, 0)
            content = extract_public_content_from_xml(
                xml,
                platform="douyin",
                keyword=task.query,
                source_url=task.query if task.query.startswith(("http://", "https://")) else "ui://douyin/current",
                screenshot_path=str(screenshot_path),
                raw_path=str(raw_path),
            )
            if content:
                result.contents.append(content)
            if task.collect_comments or task.task_type == "comments":
                comments = self._collect_visible_comments(
                    device,
                    task,
                    content_id=content.content_id if content else "",
                    source_url=content.source_url if content else "ui://douyin/comments",
                    initial_xml=xml,
                )
                result.comments.extend(comments)
                if not result.comments:
                    result.warnings.append(
                        "No visible public comments were parsed. Confirm the content page is open and comments are visible."
                    )
            return result

        if task.task_type not in ("keyword", "products"):
            result.warnings.append(
                f"Douyin UI collector currently supports keyword/products tasks; got {task.task_type}."
            )
            return result

        device.search(task.query)
        time.sleep(4)
        if task.task_type == "keyword" and task.collect_comments:
            return self._collect_keyword_video_comments(device, task, result)

        if task.task_type == "products":
            if not device.tap_product_tab():
                result.warnings.append("没有找到商品/商城入口，请确认当前抖音版本和页面支持商品搜索。")

        max_pages = max(1, task.max_pages)
        seen: set[str] = set()
        for page_index in range(max_pages):
            report_progress(f"正在读取第{page_index + 1}页", page_index, max_pages, {"contents": len(result.contents), "comments": len(result.comments)})
            xml = device.d.dump_hierarchy()
            raw_path = self._write_raw(task, page_index, xml)
            screenshot_path = self._screenshot(device, task, page_index)
            if task.task_type == "products" and self._looks_like_login_gate(xml):
                result.warnings.append("抖音显示登录/协议页面，请先在手机上完成正常登录或关闭弹窗后重试。")
                self._add_stat(result, "products", "login_gate_detected", 1)
                break
            page_content = extract_public_content_from_xml(
                xml,
                platform="douyin",
                keyword=task.query,
                source_url="ui://douyin/search",
                screenshot_path=str(screenshot_path),
                raw_path=str(raw_path),
                capture_method="douyin_ui_search_public",
            )
            for row in extract_visible_products(xml, task.query):
                key = row.get("row_id") or row.get("title") or row.get("product_id")
                if key in seen:
                    continue
                seen.add(key)
                result.contents.append(
                    SocialContent(
                        platform="douyin",
                        keyword=task.query,
                        source_url=row.get("source_url", "ui://douyin/search"),
                        content_id=row.get("product_id", ""),
                        title=row.get("title", ""),
                        description=row.get("title", ""),
                        like_count=row.get("like_count", ""),
                        published_at=row.get("publish_date", ""),
                        comment_count=page_content.comment_count if page_content else "",
                        favorite_count=page_content.favorite_count if page_content else "",
                        share_count=page_content.share_count if page_content else "",
                        play_count=page_content.play_count if page_content else "",
                        product_title=row.get("title", ""),
                        product_price=row.get("sale_price", ""),
                        product_original_price=row.get("original_price", ""),
                        product_pay_count=row.get("pay_count", ""),
                        product_image_url=row.get("image_url", ""),
                        product_shop_name=row.get("shop_name", ""),
                        screenshot_path=str(screenshot_path),
                        raw_path=str(raw_path),
                        capture_method=row.get("capture_method", "douyin_ui"),
                    )
                )
            if len(result.contents) >= task.limit:
                result.contents = result.contents[: task.limit]
                break
            device.d.swipe_ext("up", scale=0.78)
            time.sleep(2)

        return result

    @staticmethod
    def _looks_like_login_gate(xml: str) -> bool:
        markers = ("用户协议", "隐私政策", "手机号", "运营商服务协议", "验证码", "登录并使用")
        return any(marker in xml for marker in markers)

    def _collect_keyword_video_comments(
        self,
        device: DouyinDevice,
        task: CollectionTask,
        result: CollectionResult,
    ) -> CollectionResult:
        device.tap_search_tab("视频")
        time.sleep(3)

        seen_candidates: set[str] = set()
        checkpoint = load_checkpoint(self.settings.log_dir, task)
        if task.resume:
            seen_candidates.update(checkpoint.processed_set)
            self._add_stat(
                result,
                "keyword_video",
                "resume_loaded_candidates",
                len(seen_candidates),
                str(save_checkpoint(self.settings.log_dir, task, checkpoint)),
            )
        page_index = 0
        attempted = 0
        failed = 0
        no_comments = 0
        skipped = 0
        empty_pages = 0
        max_pages = max(1, task.max_pages)
        while len(result.contents) < task.limit and page_index < max_pages:
            report_progress(f"正在读取第{page_index + 1}页视频与评论", page_index, max_pages, {"contents": len(result.contents), "comments": len(result.comments)})
            xml = device.d.dump_hierarchy()
            self._write_raw(task, 500 + page_index, xml)
            self._screenshot(device, task, 500 + page_index)
            page_candidates = extract_video_candidates(xml)
            candidates = [
                candidate
                for candidate in page_candidates
                if candidate.row_id not in seen_candidates
            ]
            page_skipped = len(page_candidates) - len(candidates)
            skipped += page_skipped
            self._add_stat(
                result,
                "keyword_video",
                "page_candidates",
                len(candidates),
                f"page={page_index + 1}; total={len(page_candidates)}; skipped={page_skipped}",
            )
            if not candidates:
                empty_pages += 1
                if len(page_candidates) == 0:
                    result.warnings.append(f"No visible video candidates were found on search page {page_index + 1}.")
                self._add_stat(result, "keyword_video", "empty_or_skipped_page", 1, f"page={page_index + 1}")
                if page_index + 1 >= max_pages or empty_pages >= 2:
                    break
                device.d.swipe_ext("up", scale=0.78)
                time.sleep(2)
                page_index += 1
                continue
            empty_pages = 0

            for candidate in candidates:
                if len(result.contents) >= task.limit:
                    break
                seen_candidates.add(candidate.row_id)
                attempted += 1
                try:
                    content = self._collect_candidate_content(device, task, candidate, len(result.contents))
                    if content:
                        result.contents.append(content)
                        comments = self._collect_visible_comments(
                            device,
                            task,
                            content_id=content.content_id,
                            source_url=content.source_url,
                            initial_xml=device.d.dump_hierarchy(),
                            evidence_base=1000 + (attempted * 100),
                        )
                        if comments:
                            result.comments.extend(comments)
                            self._add_stat(
                                result,
                                "keyword_video",
                                "comments_collected",
                                len(comments),
                                candidate.title[:80],
                            )
                        else:
                            no_comments += 1
                            self._add_stat(result, "keyword_video", "no_visible_comments", 1, candidate.title[:80])
                        checkpoint.mark_processed(candidate.row_id)
                        save_checkpoint(self.settings.log_dir, task, checkpoint)
                except Exception as exc:
                    failed += 1
                    result.warnings.append(f"Failed to collect video candidate: {candidate.title[:60]} ({exc})")
                    self._add_stat(result, "keyword_video", "candidate_failed", 1, f"{candidate.title[:80]} | {exc}")
                if not self._return_to_search_results(device, result):
                    self._add_stat(result, "keyword_video", "return_failed", 1, candidate.title[:80])
                    result.warnings.append(f"Could not confirm return to search results after: {candidate.title[:60]}")
                    return result

            if len(result.contents) >= task.limit:
                break
            device.d.swipe_ext("up", scale=0.78)
            time.sleep(2)
            page_index += 1

        self._add_stat(result, "keyword_video", "attempted_candidates", attempted)
        self._add_stat(result, "keyword_video", "collected_contents", len(result.contents))
        self._add_stat(result, "keyword_video", "collected_comments", len(result.comments))
        self._add_stat(result, "keyword_video", "no_comment_candidates", no_comments)
        self._add_stat(result, "keyword_video", "failed_candidates", failed)
        self._add_stat(result, "keyword_video", "resume_skipped_candidates", skipped)
        self._add_stat(result, "keyword_video", "pages_visited", min(page_index + 1, max_pages))
        self._add_stat(result, "keyword_video", "max_pages", max_pages)
        self._add_stat(result, "keyword_video", "checkpoint_path", str(save_checkpoint(self.settings.log_dir, task, checkpoint)))
        return result

    def _collect_candidate_content(
        self,
        device: DouyinDevice,
        task: CollectionTask,
        candidate: SearchResultCandidate,
        item_index: int,
    ) -> SocialContent | None:
        device.tap_point(candidate.tap_x, candidate.tap_y, wait=3)
        xml = device.d.dump_hierarchy()
        raw_path = self._write_raw(task, 700 + item_index, xml)
        screenshot_path = self._screenshot(device, task, 700 + item_index)
        content = extract_public_content_from_xml(
            xml,
            platform="douyin",
            keyword=task.query,
            source_url=f"ui://douyin/search/video/{candidate.row_id}",
            screenshot_path=str(screenshot_path),
            raw_path=str(raw_path),
            capture_method="douyin_ui_search_video",
        )
        if not content:
            content = SocialContent(
                platform="douyin",
                keyword=task.query,
                source_url=f"ui://douyin/search/video/{candidate.row_id}",
                content_id=candidate.row_id,
                title=candidate.title,
                description=candidate.title,
                author_name=candidate.author_name,
                published_at=candidate.published_at,
                like_count=candidate.like_count,
                screenshot_path=str(screenshot_path),
                raw_path=str(raw_path),
                capture_method="douyin_ui_search_video_candidate",
            )
        else:
            content.content_id = content.content_id or candidate.row_id
            content.title = candidate.title or content.title
            content.description = candidate.title or content.description
            content.author_name = content.author_name or candidate.author_name
            content.published_at = content.published_at or candidate.published_at
            content.like_count = content.like_count or candidate.like_count
        return content

    def _return_to_search_results(self, device: DouyinDevice, result: CollectionResult | None = None) -> bool:
        for attempt in range(5):
            xml = device.d.dump_hierarchy()
            state = detect_page_state(xml)
            if state == "search_results":
                return True
            if result is not None:
                self._add_stat(result, "recovery", "back_pressed", attempt + 1, state)
            device.close_overlay()
        final_state = detect_page_state(device.d.dump_hierarchy())
        if result is not None:
            self._add_stat(result, "recovery", "final_state", final_state)
        return final_state == "search_results"

    @staticmethod
    def _is_search_results(xml: str) -> bool:
        return detect_page_state(xml) == "search_results"

    @staticmethod
    def _add_stat(result: CollectionResult, scope: str, name: str, value: int | str, detail: str = "") -> None:
        result.run_stats.append(RunStat(scope=scope, name=name, value=str(value), detail=detail))

    def _collect_visible_comments(
        self,
        device: DouyinDevice,
        task: CollectionTask,
        *,
        content_id: str,
        source_url: str,
        initial_xml: str,
        evidence_base: int = 100,
    ) -> list[SocialComment]:
        xml = initial_xml
        if not has_comment_panel(xml):
            device.tap_comment_button()
            xml = device.d.dump_hierarchy()

        if not has_comment_panel(xml):
            self._write_raw(task, evidence_base - 10, xml)
            self._screenshot(device, task, evidence_base - 10)
            return []

        comments: list[SocialComment] = []
        seen: set[str] = set()
        empty_rounds = 0
        max_scrolls = max(1, task.limit)

        for scroll_index in range(max_scrolls):
            raw_path = self._write_raw(task, evidence_base + scroll_index, xml)
            screenshot_path = self._screenshot(device, task, evidence_base + scroll_index)
            batch = extract_comments_from_xml(
                xml,
                platform="douyin",
                content_id=content_id,
                source_url=source_url,
                limit=task.max_comments_per_item,
            )
            new_count = 0
            for comment in batch:
                key = self._comment_key(comment)
                if not key or key in seen:
                    continue
                seen.add(key)
                comment.raw_path = str(raw_path)
                comment.screenshot_path = str(screenshot_path)
                comments.append(comment)
                new_count += 1
                if len(comments) >= task.max_comments_per_item:
                    return comments

            empty_rounds = empty_rounds + 1 if new_count == 0 else 0
            if empty_rounds >= 2:
                break
            device.swipe_comment_panel()
            xml = device.d.dump_hierarchy()

        return comments

    @staticmethod
    def _comment_key(comment: SocialComment) -> str:
        return "|".join(
            value.strip()
            for value in (comment.comment_author, comment.comment_text, comment.comment_time)
            if value.strip()
        )

    def _write_raw(self, task: CollectionTask, page_index: int, xml: str) -> Path:
        path = self.settings.raw_dir / f"{task.platform}_{self._safe_file_part(task.query)}_{page_index + 1}.xml"
        path.write_text(xml, encoding="utf-8")
        return path

    def _screenshot(self, device: DouyinDevice, task: CollectionTask, page_index: int) -> Path:
        path = self.settings.screenshot_dir / f"{task.platform}_{self._safe_file_part(task.query)}_{page_index + 1}.png"
        try:
            device.d.screenshot(str(path))
        except Exception:
            return Path("")
        return path

    @staticmethod
    def _safe_file_part(value: str) -> str:
        safe = []
        for char in value.strip()[:60]:
            safe.append(char if char.isalnum() or char in ("-", "_") else "_")
        return "".join(safe).strip("_") or "task"

    def _resolve_serial(self, task: CollectionTask) -> str | None:
        serial = task.serial or self.settings.default_serial
        if serial:
            return serial
        try:
            completed = subprocess.run(
                [str(self.settings.adb_path), "devices"],
                capture_output=True,
                text=True,
                timeout=8,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        for line in completed.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return parts[0]
        return None
