from __future__ import annotations

from social_crawler.platforms.adb_product import EcommerceADBCollector
from social_crawler.platforms.ali1688 import Alibaba1688Collector
from social_crawler.platforms.base import PlatformCollector
from social_crawler.platforms.dewu import DewuCollector
from social_crawler.platforms.douyin_ui import DouyinUiCollector
from social_crawler.platforms.generic_web import GenericWebCollector
from social_crawler.platforms.jd import JDCollector
from social_crawler.platforms.pinduoduo import PinduoduoCollector
from social_crawler.platforms.sample import SampleCollector
from social_crawler.platforms.taobao import TaobaoCollector
from social_crawler.platforms.xiaohongshu import XiaohongshuCollector
from social_crawler.settings import Settings

_BROWSER_PLATFORMS = frozenset({"taobao", "tmall", "jd", "jingdong",
                                 "pinduoduo", "pdd", "1688", "ali1688",
                                 "dewu", "poizon", "xiaohongshu", "xhs"})

_ADB_PLATFORMS = frozenset({"taobao", "tmall", "jd", "jingdong", "pinduoduo", "pdd"})


def get_collector(platform: str, mode: str, settings: Settings) -> PlatformCollector:
    key = platform.lower().strip()

    # ── ADB 模拟器模式（和抖音一样） ──
    if mode == "adb":
        if key in _ADB_PLATFORMS:
            return EcommerceADBCollector(settings)
        raise ValueError(f"ADB mode not supported for {platform!r}")

    # ── 浏览器自动化模式 ──
    if mode == "browser":
        if key in _BROWSER_PLATFORMS:
            try:
                from social_crawler.platforms.browser_product import BrowserProductCollector
            except ModuleNotFoundError as exc:
                if exc.name and exc.name.split(".")[0] == "playwright":
                    raise RuntimeError(
                        "浏览器采集组件未安装；可先使用手机采集或已保存的网页。"
                    ) from exc
                raise
            return BrowserProductCollector(settings, headless=True)
        raise ValueError(f"Browser mode not supported for {platform!r}")

    # ── 抖音 UI 模式（ADB 模拟器） ──
    if key == "douyin" and mode == "ui":
        return DouyinUiCollector(settings)

    # ── HTML 解析模式（手动保存网页） ──
    if key in {"taobao", "tmall", "淘宝", "天猫"}:
        return TaobaoCollector(settings)
    if key in {"jd", "jingdong", "京东"}:
        return JDCollector(settings)
    if key in {"xiaohongshu", "xhs", "小红书"}:
        return XiaohongshuCollector(settings)
    if key in {"pinduoduo", "pdd", "拼多多"}:
        return PinduoduoCollector(settings)
    if key in {"1688", "ali1688", "alibaba", "阿里巴巴"}:
        return Alibaba1688Collector(settings)
    if key in {"dewu", "poizon", "得物"}:
        return DewuCollector(settings)
    if key in {"generic_web", "web", "public_web"}:
        return GenericWebCollector(settings)
    if key in {"sample", "demo"}:
        return SampleCollector(settings)
    raise ValueError(f"Unsupported collector: platform={platform!r}, mode={mode!r}")
