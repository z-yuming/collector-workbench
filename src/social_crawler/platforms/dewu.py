"""
得物 (Dewu) 商品搜索采集器。

得物公开搜索页包含商品名、价格、销量、鉴定标识。
使用方式同淘宝：Chrome 打开搜索结果 → Ctrl+S 保存 → 粘贴文件路径。
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

PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
SALES_RE = re.compile(r"(?:销量|已售|付款)\s*[:：]?\s*(\d+(?:\.\d+)?[+万wW]?)", re.IGNORECASE)
VERIFIED_RE = re.compile(r"(?:鉴定|鉴别|查验)", re.IGNORECASE)


class DewuProductParser(HTMLParser):
    _CARD_TOKENS = frozenset({"product", "item", "card", "goods", "spu", "list-item", "pro-item"})

    def __init__(self) -> None:
        super().__init__()
        self.products: list[dict[str, str]] = []
        self._current_tag = ""
        self._current_attrs: dict[str, str] = {}
        self._in_card = False
        self._card_depth = 0
        self._card_text: list[str] = []
        self._card_img = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        self._current_attrs = {k.lower(): v or "" for k, v in attrs}
        cls_id = (self._current_attrs.get("class", "") + " " + self._current_attrs.get("id", "")).lower()

        if not self._in_card:
            if any(tok in cls_id for tok in self._CARD_TOKENS) and tag in {"div", "li", "a"}:
                self._in_card = True
                self._card_depth = 1
                self._card_text = []
                self._card_img = ""
                return
        if self._in_card:
            self._card_depth += 1
            if tag == "img" and not self._card_img:
                src = self._current_attrs.get("data-src") or self._current_attrs.get("src") or ""
                if src and "avatar" not in src.lower():
                    self._card_img = src

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
        if len(text) < 5:
            return
        fields: dict[str, str] = {}
        if m := PRICE_RE.search(text):
            fields["product_price"] = m.group(1)
        if m := SALES_RE.search(text):
            fields["product_pay_count"] = m.group(1)
        if VERIFIED_RE.search(text):
            fields["product_verified"] = "已鉴定"
        fields.setdefault("title", text[:120])
        fields.setdefault("product_image_url", self._card_img or "")
        fields["platform"] = "dewu"
        self.products.append(fields)


class DewuCollector(PlatformCollector):
    def collect(self, task: CollectionTask) -> CollectionResult:
        html, source = _read_html(task.query)
        parser = DewuProductParser()
        parser.feed(html)

        result = CollectionResult(task=task)
        for item in parser.products[: task.limit]:
            result.contents.append(SocialContent(
                platform="dewu", keyword=task.query,
                source_url=source, content_id=source,
                title=item.get("title", ""),
                product_title=item.get("title", ""),
                product_price=item.get("product_price", ""),
                product_pay_count=item.get("product_pay_count", ""),
                product_image_url=item.get("product_image_url", ""),
                capture_method="dewu_public",
            ))

        result.run_stats.extend([
            RunStat(scope="dewu", name="html_bytes", value=str(len(html.encode("utf-8")))),
            RunStat(scope="dewu", name="cards_found", value=str(len(parser.products))),
            RunStat(scope="dewu", name="items_collected", value=str(len(result.contents))),
        ])
        return result


def _read_html(query: str) -> tuple[str, str]:
    if query.startswith(("http://", "https://")):
        req = Request(query, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        with urlopen(req, timeout=20) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace"), query
    path = Path(query)
    if not path.exists():
        raise FileNotFoundError(f"HTML source not found: {query}")
    return path.read_text(encoding="utf-8"), str(path)