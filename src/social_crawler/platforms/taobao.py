"""
Taobao / Tmall public product search collector.

Works with either:
- A keyword → searches s.taobao.com, parses the result page
- A saved HTML file path → parses it offline
- A product detail URL → fetches and extracts product info

Because Taobao pages are heavily JS-rendered, direct HTTP fetch may return
limited data.  Use the "paste saved HTML" workflow for best results:
  1. Open the search results page in Chrome
  2. Save as "Webpage, Complete" (Ctrl+S)
  3. Paste the .html file path into the query field
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
    SocialComment,
    SocialContent,
)
from social_crawler.platforms.base import PlatformCollector


# ── E-commerce field extractors ─────────────────────────────────────

PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
MONTHLY_SALES_RE = re.compile(r"(?:月销|已售|销量|付款)\s*[:：]?\s*(\d+(?:\.\d+)?[+万wW]?)", re.IGNORECASE)
REVIEW_COUNT_RE = re.compile(r"(?:评价|评论)\s*[:：]?\s*(\d+(?:\.\d+)?[+万wW]?)", re.IGNORECASE)
SHOP_RE = re.compile(r"(?:店铺|店名|掌柜)\s*[:：]?\s*(.+?)(?:\s|$)", re.IGNORECASE)
ORIGINAL_PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)\s*.*?(?:原价|划线价|吊牌价)", re.IGNORECASE)


def _parse_number(value: str) -> str:
    """Normalise Chinese-style numbers: 1.2万 → 12000, 5000+ → 5000."""
    value = value.strip().rstrip("+")
    multiplier = 1.0
    if "万" in value or "w" in value.lower():
        multiplier = 10000
        value = value.replace("万", "").replace("w", "").replace("W", "")
    if "亿" in value:
        multiplier = 100000000
        value = value.replace("亿", "")
    try:
        return str(int(float(value) * multiplier))
    except ValueError:
        return value


def _extract_product_fields(text: str) -> dict[str, str]:
    """Pull price / sales / reviews / shop from a block of visible text."""
    fields: dict[str, str] = {}
    if m := PRICE_RE.search(text):
        fields["product_price"] = m.group(1)
    if m := ORIGINAL_PRICE_RE.search(text):
        fields["product_original_price"] = m.group(1)
    if m := MONTHLY_SALES_RE.search(text):
        fields["product_pay_count"] = _parse_number(m.group(1))
    if m := REVIEW_COUNT_RE.search(text):
        fields["product_comment_count"] = _parse_number(m.group(1))
    if m := SHOP_RE.search(text):
        fields["product_shop_name"] = m.group(1).strip()
    return fields


# ── Taobao-specific HTML parser ─────────────────────────────────────

class TaobaoProductParser(HTMLParser):
    """Walk a Taobao/Tmall results page and extract product cards."""

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

    # Heuristic: a "card" is a container whose class/id mentions
    # item, product, grid, card, J_ItemList, m-item, etc.
    _CARD_TOKENS = frozenset(
        {"item", "product", "card", "grid", "J_ItemList", "m-item", "goods",
         "ItemWrapper", "product-item", "col", "J_MouseEneterVerver",
         "ctx-box", "doubleCard", "singleCard"}
    )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        self._current_attrs = {k.lower(): v or "" for k, v in attrs}

        cls_id = (
            self._current_attrs.get("class", "")
            + " "
            + self._current_attrs.get("id", "")
        ).lower()

        if not self._in_card:
            if any(tok in cls_id for tok in self._CARD_TOKENS) and tag in {"div", "li", "a", "article"}:
                self._in_card = True
                self._card_depth = 1
                self._card_text = []
                self._card_img = self._current_attrs.get("data-src") or self._current_attrs.get("src") or ""
                self._card_url = self._current_attrs.get("href") or ""
                return

        if self._in_card:
            self._card_depth += 1
            if tag == "img":
                src = self._current_attrs.get("data-src") or self._current_attrs.get("src") or ""
                if src and "avatar" not in src.lower() and not self._card_img:
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
        if len(text) < 4:  # too short to be a real product card
            return
        fields = _extract_product_fields(text)
        fields.setdefault("title", text[:120])
        fields.setdefault("source_url", self._card_url or "")
        fields.setdefault("product_image_url", self._card_img or "")
        fields["platform"] = "taobao"
        self.products.append(fields)


# ── Collector ───────────────────────────────────────────────────────

class TaobaoCollector(PlatformCollector):
    """Collect public product listings from Taobao / Tmall."""

    def collect(self, task: CollectionTask) -> CollectionResult:
        html, source = _read_html(task.query)
        parser = TaobaoProductParser()
        parser.feed(html)

        result = CollectionResult(task=task)
        for item in parser.products[: task.limit]:
            content = SocialContent(
                platform="taobao",
                keyword=task.query,
                source_url=item.get("source_url", source),
                content_id=item.get("source_url", source),
                title=item.get("title", ""),
                product_title=item.get("title", ""),
                product_price=item.get("product_price", ""),
                product_original_price=item.get("product_original_price", ""),
                product_pay_count=item.get("product_pay_count", ""),
                product_shop_name=item.get("product_shop_name", ""),
                product_image_url=item.get("product_image_url", ""),
                capture_method="taobao_public",
            )
            result.contents.append(content)

        result.run_stats.extend(
            [
                RunStat(scope="taobao", name="html_bytes", value=str(len(html.encode("utf-8")))),
                RunStat(scope="taobao", name="cards_found", value=str(len(parser.products))),
                RunStat(scope="taobao", name="items_collected", value=str(len(result.contents))),
            ]
        )
        return result


# ── Shared HTML reader ──────────────────────────────────────────────

def _read_html(query: str) -> tuple[str, str]:
    """Return (html_string, source_identifier)."""
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