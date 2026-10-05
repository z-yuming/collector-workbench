from __future__ import annotations

import re
import time
from xml.etree import ElementTree
from urllib.parse import parse_qs, urlparse

import uiautomator2 as u2
from rich.console import Console


console = Console()


class DouyinDevice:
    def __init__(self, serial: str | None, package_name: str) -> None:
        self.serial = serial
        self.package_name = package_name
        self.d = u2.connect(serial) if serial else u2.connect()

    def prepare(self) -> None:
        self.d.screen_on()
        self.d.app_start(self.package_name)
        try:
            self.d.app_wait(self.package_name, front=True, timeout=20)
        except Exception:
            pass
        self.wait_for_visible_app()

    def wait_for_visible_app(self, timeout: float = 18) -> None:
        deadline = time.time() + timeout
        last_package = ""
        while time.time() < deadline:
            try:
                info = self.d.info
                last_package = info.get("currentPackageName", "")
                xml = self.d.dump_hierarchy()
            except Exception:
                time.sleep(1)
                continue
            if last_package == self.package_name and self._looks_like_douyin_page(xml):
                return
            time.sleep(1)
        console.print(f"[yellow]Douyin did not expose a stable content UI before timeout; last package={last_package}[/yellow]")

    def search(self, keyword: str) -> None:
        self._tap_search_entry()
        time.sleep(1)
        self._type_keyword(keyword)
        time.sleep(1)
        self._tap_search_button()

    def open_url(self, url: str, wait: float = 6) -> None:
        target_url = self._normalize_douyin_url(url)
        self.d.shell(
            [
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                target_url,
                "-p",
                self.package_name,
            ]
        )
        time.sleep(wait)
        self.wait_for_visible_app(timeout=12)

    @staticmethod
    def _normalize_douyin_url(url: str) -> str:
        parsed = urlparse(url)
        if "douyin.com" in parsed.netloc:
            modal_id = parse_qs(parsed.query).get("modal_id", [""])[0]
            if modal_id:
                return f"snssdk1128://aweme/detail/{modal_id}"
        return url

    def swipe_pages(self, pages: int, wait_after_swipe: float) -> None:
        for page in range(max(pages, 1)):
            console.print(f"[cyan]Triggering page {page + 1}/{pages}[/cyan]")
            time.sleep(wait_after_swipe)
            self.d.swipe_ext("up", scale=0.78)

    def tap_product_tab(self) -> None:
        self.tap_search_tab("商品")

    def tap_search_tab(self, label: str) -> bool:
        selectors = [
            self.d(text=label),
            self.d(textContains=label),
            self.d(descriptionContains=label),
        ]
        for selector in selectors:
            if selector.exists(timeout=2):
                selector.click()
                time.sleep(2)
                return True
        return False

    def tap_point(self, x: int, y: int, wait: float = 2) -> None:
        self.d.click(x, y)
        time.sleep(wait)

    def tap_comment_button(self) -> bool:
        if self._tap_visible_label_button("评论"):
            time.sleep(2)
            return True
        selectors = [
            self.d(descriptionContains="评论"),
            self.d(textContains="评论"),
        ]
        for selector in selectors:
            if selector.exists(timeout=2):
                selector.click()
                time.sleep(2)
                return True
        width, height = self.d.window_size()
        self.d.click(width * 0.95, height * 0.45)
        time.sleep(2)
        return True

    def swipe_comment_panel(self) -> None:
        width, height = self.d.window_size()
        self.d.swipe(width * 0.5, height * 0.82, width * 0.5, height * 0.45, 0.25)
        time.sleep(1.2)

    def close_overlay(self) -> None:
        self.d.press("back")
        time.sleep(1)

    @staticmethod
    def _looks_like_douyin_page(xml: str) -> bool:
        markers = ("首页", "朋友", "消息", "我", "搜索", "推荐", "关注", "商城", "评论", "点赞", "分享")
        if "火山引擎提供云和 AI 服务" in xml:
            return False
        return any(marker in xml for marker in markers)

    def _tap_visible_label_button(self, keyword: str) -> bool:
        try:
            xml = self.d.dump_hierarchy()
            root = ElementTree.fromstring(xml)
        except Exception:
            return False

        candidates: list[tuple[int, int, int, int]] = []
        for node in root.iter("node"):
            label = f"{node.get('text') or ''} {node.get('content-desc') or ''}".strip()
            if keyword not in label or "按钮" not in label:
                continue
            if "发弹幕" in label or "写评论" in label:
                continue
            bounds = self._parse_bounds(node.get("bounds") or "")
            if bounds == (0, 0, 0, 0):
                continue
            candidates.append(bounds)

        if not candidates:
            return False

        bounds = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        x = (bounds[0] + bounds[2]) / 2
        y = (bounds[1] + bounds[3]) / 2
        self.d.click(x, y)
        return True

    @staticmethod
    def _parse_bounds(value: str) -> tuple[int, int, int, int]:
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value)
        if not match:
            return (0, 0, 0, 0)
        return tuple(int(item) for item in match.groups())

    def _tap_search_entry(self) -> None:
        selectors = [
            self.d(descriptionContains="搜索"),
            self.d(textContains="搜索"),
            self.d(resourceIdMatches=".*search.*"),
        ]
        for selector in selectors:
            if selector.exists(timeout=2):
                selector.click()
                return
        width, _ = self.d.window_size()
        self.d.click(width * 0.93, 140)

    def _type_keyword(self, keyword: str) -> None:
        edit = self.d(className="android.widget.EditText")
        if edit.exists(timeout=3):
            edit.click()
            time.sleep(0.3)
            try:
                edit.clear_text()
            except Exception:
                self.d.shell(["input", "keyevent", "123"])
                for _ in range(30):
                    self.d.shell(["input", "keyevent", "67"])
            edit.set_text(keyword)
            return
        escaped = keyword.replace(" ", "%s")
        self.d.shell(["input", "text", escaped])

    def _tap_search_button(self) -> None:
        selectors = [
            self.d(text="搜索"),
            self.d(textContains="搜索"),
            self.d(descriptionContains="搜索"),
        ]
        for selector in selectors:
            if selector.exists(timeout=2):
                selector.click()
                return
        self.d.press("enter")
