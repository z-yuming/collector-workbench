"""
电商平台 ADB 采集器。

和抖音 UI 模式完全一致的体验：坐标点击搜索入口 → ADBKeyboard 广播输入中文 →
回车搜索 → 提取商品。

前提条件：
  1. ADBKeyboard 已安装启用（adb shell ime set com.android.adbkeyboard/.AdbIME）
  2. 目标 APP 已登录

用 uiautomator2 控制安卓设备。
支持：淘宝/天猫、京东、拼多多。
"""
from __future__ import annotations

import re
import time
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import uiautomator2 as u2

from social_crawler.models import (
    CollectionResult,
    CollectionTask,
    RunStat,
    SocialContent,
)
from social_crawler.platforms.base import PlatformCollector
from social_crawler.settings import Settings
from social_crawler.task_progress import report as report_progress


# ── 各电商平台 APP 配置 ──────────────────────────────────

_PLATFORM_CONFIG = {
    "taobao": {
        "package": "com.taobao.taobao",
        "name": "淘宝",
        "search_coords": (0.5, 0.12),
    },
    "jd": {
        "package": "com.jingdong.app.mall",
        "name": "京东",
        "search_coords": (0.5, 0.12),
    },
    "pinduoduo": {
        "package": "com.xunmeng.pinduoduo",
        "name": "拼多多",
        "search_coords": (0.5, 0.12),
    },
}

# ── 正则 ──────────────

_PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
_BIG_PRICE_RE = re.compile(r"(\d{3,}(?:\.\d{1,2})?)\s*元")


def _extract_price(text: str) -> str:
    m = _PRICE_RE.search(text)
    if m:
        return m.group(1)
    m = _BIG_PRICE_RE.search(text)
    if m:
        return m.group(1)
    return ""


def _looks_like_price(text: str) -> bool:
    return bool(_PRICE_RE.search(text)) or bool(_BIG_PRICE_RE.search(text))


# 销量：前向 (数字+关键词) 和后向 (关键词+数字) 都支持
_SALES_RE = re.compile(
    r"(\d+(?:\.\d+)?[+万wW人件]?)\s*(?:人付款|人看过|人收货|人已买)"
    r"|"
    r"(?:销量|已售|付款|已拼|月销|成交|热销)\s*[:：]?\s*(\d+(?:\.\d+)?[+万wW人件]?)",
    re.IGNORECASE,
)
_SHOP_RE = re.compile(
    r"(.+?)\s*(?:旗舰店|专卖店|官方店|店铺)\s*(?:订阅数[\d.]*[亿万])?\s*进店",
    re.IGNORECASE,
)

# 非商品标签 — 干扰标签（会被完全跳过）
_BADGE_WORDS = {
    "释放刷新", "百亿补贴品牌优选",
    "超级秒杀", "国家补贴", "不看预售", "筛选按钮",
    "满意度调研", "返回上一页", "任意门", "当前列表视图", "当前看图模式",
    "眼部精华热卖榜", "眼部精华热销榜", "百亿补贴眼部精华热销榜",
    "全部", "天猫", "逛", "直播", "闪购", "拍立淘", "更多 按钮",
}

# 有价值的标签 — 保留为 tag
_GOOD_TAGS = {
    "天猫国际", "天猫国际榜单", "百亿补贴",
    "品牌", "品牌直营", "金牌卖家", "官方授权",
    "新品", "夏上新", "上新", "首发",
    "包邮", "48小时发货", "24小时发货", "次日达",
    "7天无理由", "运费险", "正品保证",
    "旗舰店", "专卖店", "官方店",
}

# ── 原价 ──────────────
_ORIGINAL_PRICE_RE = re.compile(
    r"(?:原价|划线价|市场价|参考价|券后价|专柜价)[:：]?\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)",
)

# ── 物流/发货 ──────────────
_DELIVERY_RE = re.compile(
    r"(包邮|免运费|满\d+包邮|48小时内发货|24小时发货|次日达|当日达|顺丰包邮)",
    re.IGNORECASE,
)

# ── 店铺评分 ──────────────
_SHOP_RATING_RE = re.compile(
    r"(?:评分|好评|描述|服务|物流)\s*[:：]?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
# ── 发货地 ──────────────
_ORIGIN_RE = re.compile(
    r"(?:发货|产地|货源)[:：]?\s*(\S{2,8}(?:省|市|区|县))",
    re.IGNORECASE,
)
_ORIGIN_CITY_RE = re.compile(
    r"(?:广州|深圳|杭州|上海|北京|义乌|金华|温州|苏州|南京|成都|武汉|"
    r"郑州|长沙|东莞|佛山|泉州|厦门|重庆|天津|青岛|合肥|福州|"
    r"南通|嘉兴|宁波|绍兴|台州|中山|汕头)",
)

# ── 评价数 ──────────────
_REVIEW_RE = re.compile(
    r"(\d+(?:\.\d+)?[+万wW]?)\s*(?:条评价|评价|条评论|评论|人评价)",
    re.IGNORECASE,
)

# ── 优惠信息 ──────────────
_ACTIVITY_RE = re.compile(
    r"(?:"
    r"聚划算|淘抢购|百亿补贴|品牌闪购|天猫超级品牌日|"
    r"618|双11|双十二|双12|年货节|38节|女王节|618大促|"
    r"99大促|99划算节|双旦|圣诞|元旦|春节不打烊|"
    r"开学季|新风尚|新势力周|超级品类日|超级会员日|"
    r"天猫|淘宝|今日必抢|限时抢购|即将售罄|最后一天|"
    r"会员价|粉丝价|新客价|首单礼金|新人价|"
    r"满\d+减\d+|满\d+打\d+折|\d+件\d+折|"
    r"券后[¥￥]?\s*\d+(?:\.\d{1,2})?|\d+元券|"
    r"领券立减|限时优惠|活动价|秒杀价|特卖|"
    r"政府补贴|国家补贴|以旧换新|品牌直降"
    r")",
    re.IGNORECASE,
)

# Also add campaign-specific capture for structured output
_ACTIVITY_LIST = [
    "聚划算", "淘抢购", "百亿补贴", "品牌闪购",
    "天猫超级品牌日", "618", "双11", "双十二", "双12",
    "年货节", "女王节", "99划算节",
    "会员价", "粉丝价", "新客价", "首单礼金",
    "今日必抢", "限时抢购", "即将售罄", "最后一天",
    "政府补贴", "国家补贴", "以旧换新", "品牌直降",
]

# ── 规格 ──────────────
_SPEC_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:ml|g|克|毫升|升|L|kg|千克|片|粒|包|盒|瓶|袋|条|双|件|支|只|个|套|罐|桶|斤|两))",
    re.IGNORECASE,
)

# ── SKU 线索 (搜索页文本中偶尔出现) ──────────────
_SKU_CLUE_RE = re.compile(
    r"(\d+色\d+款|\d+色可选|多色可选|多规格可选|"
    r"可选(?:颜色|尺码|规格|型号|口味|香型|款式))",
    re.IGNORECASE,
)

# ── 直播中 ──────────────
_LIVE_RE = re.compile(r"(直播中|正在直播|Live)", re.IGNORECASE)



def _extract_good_tags(text: str) -> str:
    """Extract useful tags from text, comma-separated."""
    hits = []
    for tag in sorted(_GOOD_TAGS, key=len, reverse=True):
        if tag in text:
            hits.append(tag)
    return ", ".join(dict.fromkeys(hits))


def _extract_original_price(text: str) -> str:
    m = _ORIGINAL_PRICE_RE.search(text)
    return m.group(1) if m else ""


def _extract_delivery(text: str) -> str:
    m = _DELIVERY_RE.search(text)
    return m.group(1) if m else ""


def _extract_origin(text: str) -> str:
    m = _ORIGIN_RE.search(text)
    if m:
        return m.group(1)
    m = _ORIGIN_CITY_RE.search(text)
    return m.group(0) if m else ""


def _extract_review_count(text: str) -> str:
    m = _REVIEW_RE.search(text)
    if not m:
        return ""
    raw = m.group(1).rstrip("+")
    if "万" in raw or "w" in raw.lower():
        try:
            return str(int(float(raw.replace("万","").replace("w","").replace("W","")) * 10000))
        except ValueError:
            return raw
    return raw


def _extract_activity(text: str) -> str:
    m = _ACTIVITY_RE.search(text)
    return m.group(1) if m and m.lastindex else (m.group(0) if m else "")

def _extract_coupon(text: str) -> str:
    return _extract_activity(text)


def _extract_spec(text: str) -> str:
    m = _SPEC_RE.search(text)
    return m.group(0) if m else ""


def _extract_sku_clue(text: str) -> str:
    m = _SKU_CLUE_RE.search(text)
    return m.group(0) if m else ""


def _extract_live(text: str) -> str:
    m = _LIVE_RE.search(text)
    return m.group(0) if m else ""


def _extract_rating(text: str) -> str:
    m = _SHOP_RATING_RE.search(text)
    return m.group(1) if m else ""


def _is_badge(text: str) -> bool:
    t = text.strip()
    for bw in _BADGE_WORDS:
        if bw in t:
            return True
    if t.endswith(",可选，按钮") or t.endswith(",已选中") or t.endswith(",未选中"):
        return True
    return False


def _parse_sales(raw: str) -> str:
    raw = raw.strip().rstrip("+").rstrip("人").rstrip("件")
    if "万" in raw or "w" in raw.lower():
        raw = raw.replace("万", "").replace("w", "").replace("W", "")
        try:
            return str(int(float(raw) * 10000))
        except ValueError:
            return raw
    try:
        return str(int(raw.replace(",", "")))
    except ValueError:
        return raw


def _extract_sales(text: str) -> str:
    m = _SALES_RE.search(text)
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def _parse_shop(raw: str) -> str:
    m = _SHOP_RE.search(raw)
    if m:
        return m.group(1).strip()
    return ""


# ── 可见文本提取 ──────────────

def _extract_visible_texts(xml: str) -> list[str]:
    root = ElementTree.fromstring(xml)
    texts: list[str] = []

    def walk(node):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls = node.get("class", "")

        if text and len(text) >= 2:
            texts.append(text)
        elif desc and len(desc) >= 2:
            skip = {
                "隐藏", "返回", "主屏幕", "最近运行的应用", "搜索", "查看更多",
                "系统通知", "云空间通知", "天气通知", "玩机技巧通知",
                "开启 NFC", "振铃器静音", "WLAN 信号强度满格", "无 SIM 卡",
                "正在充电", "已连接 USB 调试", "满意度调研", "任意门",
                "下拉刷新", "回到列表顶部", "当前列表视图",
            }
            if desc not in skip and not desc.startswith("系统通知") and not desc.startswith("天气通知"):
                texts.append(desc)
        for child in node:
            walk(child)

    walk(root)
    return texts


def _extract_products_from_texts(texts: list[str]) -> list[dict[str, str]]:
    products: list[dict[str, str]] = []

    i = 0
    while i < len(texts):
        t = texts[i]
        if _looks_like_price(t):
            price = _extract_price(t)

            # 标题：优先价格行去掉价格部分后的文本
            title_part = _PRICE_RE.sub("", t)
            title_part = _BIG_PRICE_RE.sub("", title_part).strip()
            if title_part and len(title_part) >= 6 and not _is_badge(title_part):
                title = title_part
            else:
                title = ""
                for j in range(max(0, i - 3), i):
                    prev = texts[j].strip()
                    if prev and len(prev) >= 6 and not _looks_like_price(prev) and not _is_badge(prev):
                        title = prev
                        break
                if not title:
                    title = t

            # 销量/店铺/标签/原价/物流/评分/发货地/评价/优惠/规格/SKU/直播：±5行
            sales = ""
            shop = ""
            original_price = ""
            tags = ""
            delivery = ""
            rating = ""
            origin = ""
            review_count = ""
            coupon = ""
            spec = ""
            sku_clue = ""
            live = ""
            for j in range(max(0, i - 2), min(len(texts), i + 6)):
                s = _extract_sales(texts[j])
                if s:
                    sales = _parse_sales(s)
                sh = _SHOP_RE.search(texts[j])
                if sh:
                    shop = _parse_shop(texts[j])
                op = _extract_original_price(texts[j])
                if op:
                    original_price = op
                tg = _extract_good_tags(texts[j])
                if tg:
                    tags = tg
                dv = _extract_delivery(texts[j])
                if dv:
                    delivery = dv
                rt = _extract_rating(texts[j])
                if rt:
                    rating = rt
                og = _extract_origin(texts[j])
                if og:
                    origin = og
                rc = _extract_review_count(texts[j])
                if rc:
                    review_count = rc
                cp = _extract_coupon(texts[j])
                if cp:
                    coupon = cp
                sp = _extract_spec(texts[j])
                if sp:
                    spec = sp
                sk = _extract_sku_clue(texts[j])
                if sk:
                    sku_clue = sk
                lv = _extract_live(texts[j])
                if lv:
                    live = lv

            products.append({
                "title": title,
                "product_price": price,
                "product_original_price": original_price,
                "product_pay_count": sales,
                "product_shop_name": shop,
                "product_tags": tags,
                "product_delivery": delivery,
                "product_shop_rating": rating,
                "product_origin": origin,
                "product_review_count": review_count,
                "product_coupon": coupon,
                "product_spec": spec,
                "product_sku_clue": sku_clue,
                "product_live": live,
            })
            i += 1
        else:
            i += 1

    return products


# ── SKU 提取（详情页） ──────────

_COLOR_WORDS = {
    "白色", "黑色", "红色", "蓝色", "绿色", "黄色", "紫色", "粉色", "橙色",
    "灰色", "棕色", "金色", "银色", "米色", "肤色", "透明",
    "深蓝", "浅蓝", "藏青", "酒红", "玫红", "卡其", "驼色", "军绿",
    "黑金", "白蓝", "黑白", "粉白", "蓝白",
}
_SIZE_WORDS = {
    "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL",
    "均码", "大码", "小码", "标准",
}
_SIZE_NUM = re.compile(r'^\d{2,3}(?:\.\d)?$')


# ── OCR SKU 提取 ──────────
_OCR_READER = None


def _get_ocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr
        _OCR_READER = easyocr.Reader(['ch_sim', 'en'], gpu=True)
    return _OCR_READER


def _ocr_extract_skus(pil_image) -> dict:
    """Run OCR on a detail-page screenshot and extract SKU options."""
    try:
        reader = _get_ocr_reader()
        # PIL Image passed directly
        results = reader.readtext(np.array(pil_image), detail=0)
    except Exception:
        return {}

    if not results:
        return {}

    # Classify OCR lines
    colors: list[str] = []
    sizes: list[str] = []
    specs: list[str] = []

    for text in results:
        t = text.strip()
        if not t or len(t) > 12:
            continue
        # Color
        if t in _COLOR_WORDS:
            colors.append(t)
        # Size
        elif t.upper() in _SIZE_WORDS or _SIZE_NUM.match(t):
            sizes.append(t)
        # Spec (ml/g/etc)
        elif _SPEC_RE.search(t):
            specs.append(t)
        # Short text that might be a variant
        elif 2 <= len(t) <= 8:
            # Filter obvious noise
            noise = {
                '购物车', '收藏', '客服', '店铺', '首页', '宝贝',
                '评价', '详情', '推荐', '参数', '价格', '促销',
                '领券', '满减', '包邮', '已选', '销量', '超级立减', '省钱卡', '红包', '点击领取', '送赠品', '搜索', '点击', '领取', '加购', '开通', '可再享', '送礼',
            }
            skip = False
            for w in noise:
                if w in t:
                    skip = True
                    break
            if not skip and not t.isdigit():
                specs.append(t)

    result = {}
    if colors:
        result['颜色'] = list(dict.fromkeys(colors))
    if sizes:
        result['尺码'] = list(dict.fromkeys(sizes))
    if specs:
        result['规格'] = list(dict.fromkeys(specs[:12]))
    return result


# ── Collector ──────────────


class EcommerceADBCollector(PlatformCollector):

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.settings = settings

    def collect(self, task: CollectionTask) -> CollectionResult:
        keyword = task.query.strip()
        platform_key = task.platform.lower().strip()
        config = _PLATFORM_CONFIG.get(platform_key)
        if not config:
            raise ValueError(f"ADB mode not supported: {platform_key!r}")

        serial = self._resolve_serial(task)
        report_progress("正在连接手机并打开目标APP")
        device = u2.connect(serial) if serial else u2.connect()
        result = CollectionResult(task=task)

        try:
            device.screen_on()

            # 1) 启动 APP
            device.app_stop(config["package"])
            time.sleep(0.5)
            device.app_start(config["package"])
            try:
                device.app_wait(config["package"], front=True, timeout=15)
            except Exception:
                pass
            time.sleep(4)

            w, h = device.window_size()
            sx, sy = config["search_coords"]

            # 2) 点击搜索栏
            device.click(int(w * sx), int(h * sy))
            time.sleep(2.5)

            # 3) 输入中文 (send_keys + search button click)
            try:
                device.send_keys(keyword)
            except Exception:
                # Fallback: ADB broadcast
                device.shell([
                    "am", "broadcast", "-a", "ADB_INPUT_TEXT",
                    "--es", "msg", keyword,
                ])
            time.sleep(0.5)

            # 4) 触发搜索 — click search button at right side
            device.click(int(w * 0.88), int(h * 0.08))
            time.sleep(5)

            # 5) 翻页采集
            max_pages = max(1, task.max_pages)
            seen: set[str] = set()

            for page_index in range(max_pages):
                report_progress(f"正在读取第{page_index + 1}页商品", page_index, max_pages, {"contents": len(result.contents), "comments": len(result.comments)})
                xml = device.dump_hierarchy()

                texts = _extract_visible_texts(xml)
                products = _extract_products_from_texts(texts)

                for item in products:
                    key = (item.get("title") or "")[:60]
                    if not key or key in seen:
                        continue
                    seen.add(key)

                    # Try to extract SKU from detail page via OCR
                    sku_data = {}
                    if task.collect_comments:
                        try:
                            # Click product
                            device.click(int(w * 0.5), int(h * 0.30))
                            time.sleep(4)
                            # SKU area is in the middle of the page (below product image)
                            # No scroll needed — crop from 25% height
                            img = device.screenshot()
                            if img is not None:
                                w_img, h_img = img.size
                                img = img.crop((0, int(h_img * 0.25), w_img, h_img))
                                sku_data = _ocr_extract_skus(img)
                            device.press("back")
                            time.sleep(1.5)
                            device.press("back")
                            time.sleep(1)
                        except Exception:
                            try:
                                device.press("back")
                                device.press("back")
                            except Exception:
                                pass
                            time.sleep(1)

                    result.contents.append(SocialContent(
                        platform=platform_key,
                        keyword=keyword,
                        source_url=f"adb://{config['name']}/search?q={keyword}&page={page_index + 1}",
                        content_id=key,
                        title=item.get("title", ""),
                        product_title=item.get("title", ""),
                        product_price=item.get("product_price", ""),
                        product_original_price=item.get("product_original_price", ""),
                        product_pay_count=item.get("product_pay_count", ""),
                        product_shop_name=item.get("product_shop_name", ""),
                        capture_method="adb_automation",
                        detail_data={
                            "tags": item.get("product_tags", ""),
                            "delivery": item.get("product_delivery", ""),
                            "shop_rating": item.get("product_shop_rating", ""),
                            "origin": item.get("product_origin", ""),
                            "review_count": item.get("product_review_count", ""),
                            "coupon": item.get("product_coupon", ""),
                            "spec": item.get("product_spec", ""),
                            "sku_clue": item.get("product_sku_clue", ""),
                            "live": item.get("product_live", ""),
                            "sku": sku_data,
                        },
                    ))
                    if len(result.contents) >= task.limit:
                        break

                if len(result.contents) >= task.limit:
                    break

                device.swipe_ext("up", scale=0.78)
                time.sleep(2)

            result.run_stats.extend([
                RunStat(scope=platform_key, name="mode", value="adb"),
                RunStat(scope=platform_key, name="products_collected",
                        value=str(len(result.contents))),
                RunStat(scope=platform_key, name="pages_scanned",
                        value=str(min(page_index + 1, max_pages))),
            ])

        except Exception as exc:
            result.warnings.append(f"ADB error: {exc}")

        return result

    @staticmethod
    def _resolve_serial(task) -> str | None:
        if task.serial:
            return task.serial
        try:
            r = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, errors='replace', timeout=8
            )
            for line in r.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    return parts[0]
        except Exception:
            pass
        return None
