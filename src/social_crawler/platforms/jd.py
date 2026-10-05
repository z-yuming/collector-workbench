"""
JD.com public product search collector.

Same workflow as Taobao: keyword search HTML or saved page file.
JD search URL pattern: https://search.jd.com/Search?keyword={query}&page={page}
"""

from __future__ import annotations

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

# Re-use the same extraction helpers
PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
SALES_RE = re.compile(r"(?:评价|评论|销量)\s*[:：]?\s*(\d+(?:\.\d+)?[+万wW]?)", re.IGNORECASE)
SHOP_RE = re.compile(r"(?:店铺|自营|京东)\s*[:：]?\s*(.+?)(?:\s|$)", re.IGNORECASE)
PLUS_PRICE_RE = re.compile(r"(?:PLUS|plus|会员).*?[¥￥]\s*(\d+(?:\.\d{1,2})?)", re.IGNORECASE)


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


def _extract_product_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    if m := PRICE_RE.search(text):
        fields["product_price"] = m.group(1)
    if m := PLUS_PRICE_RE.search(text):
        fields["product_original_price"] = m.group(1)
    if m := SALES_RE.search(text):
        fields["product_comment_count"] = _parse_number(m.group(1))
    if m := SHOP_RE.search(text):
        fields["product_shop_name"] = m.group(1).strip()
    return fields


class JDProductParser(HTMLParser):
    """Walk a JD search results page and extract product cards."""

    _CARD_TOKENS = frozenset(
        {"gl-item", "goods", "item", "product", "card", "J_", "sku", "gl-i-wrap"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.products: list[dict[str, str]] = []
        self._current_tag = ""
        self._current_attrs: dict[str, str] = {}
        self._in_card = False
        self._card_depth = 0
        self._card_text: list[str] = []
        self._card_img = ""
        self._card_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        self._current_attrs = {k.lower(): v or "" for k, v in attrs}

        cls_id = (
            self._current_attrs.get("class", "")
            + " "
            + self._current_attrs.get("id", "")
        ).lower()

        if not self._in_card:
            if any(tok in cls_id for tok in self._CARD_TOKENS) and tag in {"li", "div", "a"}:
                self._in_card = True
                self._card_depth = 1
                self._card_text = []
                self._card_img = self._current_attrs.get("data-src") or self._current_attrs.get("src") or ""
                self._card_url = self._current_attrs.get("href") or ""
                return

        if self._in_card:
            self._card_depth += 1
            if tag == "img" and not self._card_img:
                src = self._current_attrs.get("data-src") or self._current_attrs.get("src") or ""
                if src and "avatar" not in src.lower():
                    self._card_img = src
            if tag == "a" and not self._card_url:
                self._card_url = self._current_attrs.get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if self._in_card:
            self._card_depth -= 1
            if self._card_depth <= 0:
                self._in_card = False
                self._flush_card()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_card and self._current_tag not in {"script", "style", "noscript"}:
            self._card_text.append(text)

    def _flush_card(self) -> None:
        text = " ".join(self._card_text).strip()
        if len(text) < 6:
            return
        fields = _extract_product_fields(text)
        fields.setdefault("title", text[:120])
        fields.setdefault("source_url", self._card_url or "")
        fields.setdefault("product_image_url", self._card_img or "")
        fields["platform"] = "jd"
        self.products.append(fields)


class JDCollector(PlatformCollector):
    """Collect public product listings from JD.com."""

    def collect(self, task: CollectionTask) -> CollectionResult:
        html, source = _read_html(task.query)
        parser = JDProductParser()
        parser.feed(html)

        result = CollectionResult(task=task)
        for item in parser.products[: task.limit]:
            content = SocialContent(
                platform="jd",
                keyword=task.query,
                source_url=item.get("source_url", source),
                content_id=item.get("source_url", source),
                title=item.get("title", ""),
                product_title=item.get("title", ""),
                product_price=item.get("product_price", ""),
                product_original_price=item.get("product_original_price", ""),
                product_shop_name=item.get("product_shop_name", ""),
                product_image_url=item.get("product_image_url", ""),
                capture_method="jd_public",
            )
            result.contents.append(content)

        result.run_stats.extend(
            [
                RunStat(scope="jd", name="html_bytes", value=str(len(html.encode("utf-8")))),
                RunStat(scope="jd", name="cards_found", value=str(len(parser.products))),
                RunStat(scope="jd", name="items_collected", value=str(len(result.contents))),
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