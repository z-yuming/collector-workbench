"""
浏览器自动化商品采集器。

用 Playwright 控制 Chromium，自动打开搜索结果页并提取商品数据。
支持：淘宝、京东、拼多多、1688、得物、小红书。

mode = "browser" 时使用，不再需要手动保存 HTML。
"""

from __future__ import annotations

import asyncio
import re
from social_crawler.task_progress import report as report_progress
from typing import Any

from playwright.async_api import async_playwright, Page

from social_crawler.models import (
    CollectionResult,
    CollectionTask,
    RunStat,
    SocialContent,
)
from social_crawler.platforms.base import PlatformCollector

# ── 各平台搜索 URL ──────────────────────────────────────────

_PLATFORM_SEARCH_URL: dict[str, str] = {
    "taobao": "https://s.taobao.com/search?q={q}",
    "jd": "https://search.jd.com/Search?keyword={q}&enc=utf-8",
    "pinduoduo": "https://mobile.yangkeduo.com/search_result.html?search_key={q}",
    "1688": "https://s.1688.com/selloffer/offer_search.htm?keywords={q}",
    "dewu": "https://www.dewu.com/search?keyword={q}",
    "xiaohongshu": "https://www.xiaohongshu.com/search_result?keyword={q}&source=web_search_result_notes",
}

# ── 价格正则 ──────────────────────────────────────────────

_PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
_SALES_RE = re.compile(r"(?:销量|已售|付款|已拼|拼成)\s*[:：]?\s*(\d+(?:\.\d+)?[+万wW]?)", re.IGNORECASE)
_SHOP_RE = re.compile(r"(?:店铺|店|供应商|厂家)\s*[:：]?\s*(.+?)(?:\s|$)", re.IGNORECASE)


def _parse_sales(raw: str) -> str:
    """解析销量字符串为纯数字."""
    raw = raw.strip().rstrip("+")
    if "万" in raw or "w" in raw.lower():
        raw = raw.replace("万", "").replace("w", "").replace("W", "")
        try:
            return str(int(float(raw) * 10000))
        except ValueError:
            return raw
    return raw


class BrowserProductCollector(PlatformCollector):
    """Playwright 驱动的商品采集器，覆盖淘宝 / 京东 / 拼多多 / 1688 / 得物 / 小红书。"""

    def __init__(self, settings: Any, headless: bool = True) -> None:
        super().__init__(settings)
        self._headless = headless

    def collect(self, task: CollectionTask) -> CollectionResult:
        return asyncio.run(self._async_collect(task))

    async def _async_collect(self, task: CollectionTask) -> CollectionResult:
        platform_key = task.platform.lower().strip()
        search_url = _PLATFORM_SEARCH_URL.get(platform_key)
        if not search_url:
            raise ValueError(f"Browser mode not supported for platform: {platform_key!r}")

        url = search_url.replace("{q}", task.query)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            page = await context.new_page()
            report_progress("正在打开浏览器搜索结果页")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待商品卡片出现
            try:
                await page.wait_for_selector(
                    "a,div,li",
                    timeout=15000,
                    state="attached",
                )
                await asyncio.sleep(2)  # 额外等待 JS 渲染
            except Exception:
                pass  # 部分平台可能已渲染完毕

            report_progress("正在提取页面中的商品数据")
            products = await _extract_products_generic(page, platform_key)
            await browser.close()

        result = CollectionResult(task=task)
        for item in products[: task.limit]:
            result.contents.append(SocialContent(
                platform=platform_key,
                keyword=task.query,
                source_url=url,
                content_id=url,
                title=item.get("title", ""),
                product_title=item.get("title", ""),
                product_price=item.get("product_price", ""),
                product_original_price=item.get("product_original_price", ""),
                product_pay_count=item.get("product_pay_count", ""),
                product_shop_name=item.get("product_shop_name", ""),
                product_image_url=item.get("product_image_url", ""),
                capture_method="browser_automation",
            ))

        result.run_stats.extend([
            RunStat(scope=platform_key, name="products_found", value=str(len(products))),
            RunStat(scope=platform_key, name="products_collected", value=str(len(result.contents))),
            RunStat(scope=platform_key, name="mode", value="browser"),
        ])
        return result


async def _extract_products_generic(page: Page, platform: str) -> list[dict[str, str]]:
    """通用 DOM 提取：遍历所有可见文本块，识别商品信息."""
    products: list[dict[str, str]] = []

    # 找所有可能包含商品的容器
    candidates = await page.evaluate("""
        () => {
            const items = [];
            const selectors = ['li', 'div[class]', 'a[class]'];
            for (const sel of selectors) {
                document.querySelectorAll(sel).forEach(el => {
                    const text = el.innerText?.trim() || '';
                    const hasPrice = /[¥￥]\\s*\\d+/.test(text);
                    if (hasPrice && text.length > 10 && text.length < 800) {
                        const imgs = el.querySelectorAll('img');
                        let imgSrc = '';
                        for (const img of imgs) {
                            const src = img.src || img.getAttribute('data-src') || '';
                            if (src && !src.includes('avatar') && !src.includes('icon')) {
                                imgSrc = src;
                                break;
                            }
                        }
                        items.push({text, img: imgSrc});
                    }
                });
            }
            return items.slice(0, 50);
        }
    """)

    seen: set[str] = set()
    for item in candidates:
        text = item["text"]
        # 去重
        key = text[:60]
        if key in seen:
            continue
        seen.add(key)

        fields: dict[str, str] = {"title": text.split("\n")[0][:120]}

        prices = _PRICE_RE.findall(text)
        if prices:
            fields["product_price"] = prices[0]
            if len(prices) > 1:
                fields["product_original_price"] = prices[1]

        if m := _SALES_RE.search(text):
            fields["product_pay_count"] = _parse_sales(m.group(1))
        if m := _SHOP_RE.search(text):
            fields["product_shop_name"] = m.group(1).strip()
        if item["img"]:
            fields["product_image_url"] = item["img"]

        products.append(fields)

    return products
