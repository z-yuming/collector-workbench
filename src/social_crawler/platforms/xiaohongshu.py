"""
Xiaohongshu (小红书) public search collector.

XHS public web search URL: https://www.xiaohongshu.com/search_result?keyword={query}

Because XHS pages are rendered client-side, direct HTTP fetch will get minimal content.
Use the "save HTML from browser" workflow for best results:
  1. Open https://www.xiaohongshu.com/search_result?keyword=xxx in Chrome
  2. Let the page fully load
  3. Save as Webpage Complete (Ctrl+S)
  4. Paste the .html file path into the query field

Alternatively, we attempt to fetch the page directly (may return limited data).
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from social_crawler.models import (
    CollectionResult,
    CollectionTask,
    RunStat,
    SocialContent,
)
from social_crawler.platforms.base import PlatformCollector


LIKE_RE = re.compile(r"(?:赞|喜欢|like)\s*[:：]?\s*(\d+(?:\.\d+)?[万wWkK]?)", re.IGNORECASE)
FAV_RE = re.compile(r"(?:收藏|favorite)\s*[:：]?\s*(\d+(?:\.\d+)?[万wWkK]?)", re.IGNORECASE)
COMMENT_RE = re.compile(r"(?:评论|comment)\s*[:：]?\s*(\d+(?:\.\d+)?[万wWkK]?)", re.IGNORECASE)


def _parse_number(value: str) -> str:
    value = value.strip().rstrip("+")
    multiplier = 1.0
    if "万" in value or "w" in value.lower():
        multiplier = 10000
        value = value.replace("万", "").replace("w", "").replace("W", "")
    try:
        return str(int(float(value) * multiplier))
    except ValueError:
        return value


def _extract_metrics(texts: list[str]) -> dict[str, str]:
    joined = " ".join(texts)
    metrics: dict[str, str] = {}
    if m := LIKE_RE.search(joined):
        metrics["like_count"] = _parse_number(m.group(1))
    if m := FAV_RE.search(joined):
        metrics["favorite_count"] = _parse_number(m.group(1))
    if m := COMMENT_RE.search(joined):
        metrics["comment_count"] = _parse_number(m.group(1))
    return metrics


class XHSNoteParser(HTMLParser):
    """Walk XHS search result HTML and extract note cards."""

    _CARD_TOKENS = frozenset(
        {"note-item", "note", "feed-item", "card", "search-result", "note-card"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.notes: list[dict[str, str]] = []
        self._current_tag = ""
        self._current_attrs: dict[str, str] = {}
        self._in_card = False
        self._card_depth = 0
        self._card_text: list[str] = []
        self._card_cover = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        self._current_attrs = {k.lower(): v or "" for k, v in attrs}

        cls_id = (
            self._current_attrs.get("class", "")
            + " "
            + self._current_attrs.get("id", "")
        ).lower()

        if not self._in_card:
            if any(tok in cls_id for tok in self._CARD_TOKENS) and tag in {"div", "li", "a", "section", "article"}:
                self._in_card = True
                self._card_depth = 1
                self._card_text = []
                self._card_cover = ""
                return

        if self._in_card:
            self._card_depth += 1
            if tag == "img" and not self._card_cover:
                src = self._current_attrs.get("data-src") or self._current_attrs.get("src") or ""
                if src and "avatar" not in src.lower():
                    self._card_cover = src

    def handle_endtag(self, tag: str) -> None:
        if self._in_card:
            self._card_depth -= 1
            if self._card_depth <= 0:
                self._in_card = False
                self._flush_note()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_card and self._current_tag not in {"script", "style", "noscript"}:
            self._card_text.append(text)

    def _flush_note(self) -> None:
        text = " ".join(self._card_text).strip()
        if len(text) < 5:
            return
        metrics = _extract_metrics(self._card_text)
        note = {
            "title": text[:120],
            "product_image_url": self._card_cover or "",
            "platform": "xiaohongshu",
            **metrics,
        }
        self.notes.append(note)


class XiaohongshuCollector(PlatformCollector):
    """Collect public search results from Xiaohongshu."""

    def collect(self, task: CollectionTask) -> CollectionResult:
        html, source = _read_html(task.query)
        parser = XHSNoteParser()
        parser.feed(html)

        result = CollectionResult(task=task)
        for item in parser.notes[: task.limit]:
            content = SocialContent(
                platform="xiaohongshu",
                keyword=task.query,
                source_url=source,
                content_id=source,
                title=item.get("title", ""),
                author_name=item.get("author_name", ""),
                like_count=item.get("like_count", ""),
                favorite_count=item.get("favorite_count", ""),
                comment_count=item.get("comment_count", ""),
                product_image_url=item.get("product_image_url", ""),
                capture_method="xhs_public",
            )
            result.contents.append(content)

        result.run_stats.extend(
            [
                RunStat(scope="xiaohongshu", name="html_bytes", value=str(len(html.encode("utf-8")))),
                RunStat(scope="xiaohongshu", name="notes_found", value=str(len(parser.notes))),
                RunStat(scope="xiaohongshu", name="items_collected", value=str(len(result.contents))),
            ]
        )
        return result


def _read_html(query: str) -> tuple[str, str]:
    if query.startswith(("http://", "https://")):
        req = Request(
            query,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        with urlopen(req, timeout=20) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace"), query

    path = Path(query)
    if not path.exists():
        raise FileNotFoundError(f"HTML source not found: {query}")
    return path.read_text(encoding="utf-8"), str(path)