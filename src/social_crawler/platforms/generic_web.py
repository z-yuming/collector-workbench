from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from social_crawler.models import CollectionResult, CollectionTask, RunStat, SocialComment, SocialContent
from social_crawler.platforms.base import PlatformCollector


COUNT_RE = re.compile(r"(?P<count>\d+(?:\.\d+)?\s*[万wWkK]?)")
METRIC_PATTERNS = {
    "like_count": ("likes", "like", "点赞", "赞"),
    "comment_count": ("comments", "comment", "评论"),
    "favorite_count": ("favorites", "favorite", "收藏"),
    "share_count": ("shares", "share", "分享", "转发"),
    "play_count": ("views", "view", "plays", "play", "播放", "观看"),
}


class GenericWebCollector(PlatformCollector):
    def collect(self, task: CollectionTask) -> CollectionResult:
        html, source_url = read_public_html(task.query)
        parsed = PublicHtmlParser()
        parsed.feed(html)

        result = CollectionResult(task=task)
        metrics = extract_metrics(parsed.visible_text)
        content = SocialContent(
            platform=task.platform,
            keyword=task.query,
            source_url=source_url,
            content_id=source_url,
            author_name=parsed.meta.get("author", ""),
            title=parsed.title(),
            description=parsed.description(),
            like_count=metrics.get("like_count", ""),
            comment_count=metrics.get("comment_count", ""),
            favorite_count=metrics.get("favorite_count", ""),
            share_count=metrics.get("share_count", ""),
            play_count=metrics.get("play_count", ""),
            product_image_url=parsed.meta.get("og:image", ""),
            capture_method="generic_web_public",
        )
        result.contents.append(content)

        if task.collect_comments:
            for index, item in enumerate(parsed.comments[: task.max_comments_per_item], start=1):
                result.comments.append(
                    SocialComment(
                        platform=task.platform,
                        content_id=content.content_id,
                        source_url=source_url,
                        comment_id=f"web-comment-{index}",
                        comment_author=item.get("author", ""),
                        comment_text=item.get("text", ""),
                        comment_likes=item.get("likes", ""),
                    )
                )

        result.run_stats.extend(
            [
                RunStat(scope="generic_web", name="html_bytes", value=str(len(html.encode("utf-8")))),
                RunStat(scope="generic_web", name="visible_text_items", value=str(len(parsed.visible_text))),
                RunStat(scope="generic_web", name="comments_found", value=str(len(parsed.comments))),
            ]
        )
        return result


class PublicHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.visible_text: list[str] = []
        self._current_tag = ""
        self._current_attrs: dict[str, str] = {}
        self._capture_title = False
        self._title_parts: list[str] = []
        self._comment_depth = 0
        self._comment_parts: list[str] = []
        self.comments: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        self._current_attrs = {key.lower(): value or "" for key, value in attrs}
        if self._current_tag == "title":
            self._capture_title = True
        if self._current_tag == "meta":
            name = self._current_attrs.get("name") or self._current_attrs.get("property")
            content = self._current_attrs.get("content", "")
            if name and content:
                self.meta[name.lower()] = content.strip()
        if self._looks_like_comment_container():
            self._comment_depth += 1
            self._comment_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._capture_title = False
        if self._comment_depth:
            self._comment_depth -= 1
            if self._comment_depth == 0:
                parsed = parse_comment_text(" ".join(self._comment_parts))
                if parsed and parsed.get("text"):
                    self.comments.append(parsed)
                self._comment_parts = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_title:
            self._title_parts.append(text)
        if self._current_tag not in {"script", "style", "noscript"}:
            self.visible_text.append(text)
        if self._comment_depth:
            self._comment_parts.append(text)

    def title(self) -> str:
        return self.meta.get("og:title") or self.meta.get("twitter:title") or " ".join(self._title_parts).strip()

    def description(self) -> str:
        return self.meta.get("description") or self.meta.get("og:description") or ""

    def _looks_like_comment_container(self) -> bool:
        value = " ".join(
            item
            for item in (
                self._current_attrs.get("class", ""),
                self._current_attrs.get("id", ""),
                self._current_attrs.get("data-role", ""),
            )
            if item
        ).lower()
        return self._current_tag in {"div", "li", "article"} and any(
            token in value.split() or value == token for token in ("comment", "reply", "评论")
        )


def read_public_html(query: str) -> tuple[str, str]:
    if query.startswith(("http://", "https://")):
        request = Request(query, headers={"User-Agent": "Mozilla/5.0 public-social-data-crawler"})
        with urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace"), query

    path = Path(query)
    if not path.exists():
        raise FileNotFoundError(f"HTML source not found: {query}")
    return path.read_text(encoding="utf-8"), str(path)


def extract_metrics(texts: list[str]) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for text in texts:
        compact = text.strip()
        for field, aliases in METRIC_PATTERNS.items():
            if field in metrics:
                continue
            if any(alias.lower() in compact.lower() for alias in aliases):
                match = COUNT_RE.search(compact)
                if match:
                    metrics[field] = match.group("count")
    return metrics


def parse_comment_text(value: str) -> dict[str, str]:
    clean = " ".join(value.split())
    if not clean:
        return {}
    likes = ""
    match = re.search(r"(?:likes?|点赞|赞)\s*[:：]?\s*(\d+(?:\.\d+)?\s*[万wWkK]?)", clean, re.IGNORECASE)
    if match:
        likes = match.group(1)
        clean = (clean[: match.start()] + clean[match.end() :]).strip()
    author = ""
    author_match = re.search(
        r"(?:author|user|用户|作者)\s*[:：]\s*(.+?)(?=\s+(?:text|content|评论)\s*[:：]|$)",
        clean,
        re.IGNORECASE,
    )
    if author_match:
        author = author_match.group(1).strip()
        clean = (clean[: author_match.start()] + clean[author_match.end() :]).strip()
    text_match = re.search(r"(?:text|content|评论)\s*[:：]\s*(.+)", clean, re.IGNORECASE)
    text = text_match.group(1).strip() if text_match else clean.strip(" |")
    return {"author": author, "text": text, "likes": likes}
