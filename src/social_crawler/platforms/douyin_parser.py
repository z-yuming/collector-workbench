from __future__ import annotations

import re

from social_crawler.models import SocialComment, SocialContent
from social_crawler.ui_xml import UiNode, parse_nodes, visible_labels


COUNT_RE = re.compile(r"(?P<count>\d+(?:\.\d+)?\s*[万wW]?)")
PRICE_RE = re.compile(r"(?:¥|￥)\s*(?P<price>\d+(?:\.\d+)?)")
TIME_RE = re.compile(
    r"^(刚刚|今天|昨天|前天)$|^(今天|昨天|前天)\s+\d{1,2}:\d{2}$|"
    r"^\d{1,2}(:\d{2})?$|^\d{1,2}-\d{1,2}$|"
    r"^\d{4}-\d{1,2}-\d{1,2}$|^\d+\s*(秒|分钟|小时|天|周|月|年)前$"
)
METRIC_ALIASES = {
    "like_count": ("点赞", "赞"),
    "comment_count": ("评论",),
    "favorite_count": ("收藏",),
    "share_count": ("分享", "转发"),
    "play_count": ("播放", "观看"),
}
NAVIGATION_NOISE = {
    "首页",
    "朋友",
    "拍摄",
    "消息",
    "我",
    "搜索",
    "推荐",
    "同城",
    "关注",
    "商城",
    "团购",
    "经验",
    "隐藏",
    "返回",
    "最近运行的应用",
    "主屏幕",
}
COMMENT_PANEL_MARKERS = ("全部评论", "条评论", "写评论", "发评论", "评论 ")
COMMENT_CONTROL_NOISE = (
    "回复",
    "展开",
    "查看",
    "写评论",
    "发评论",
    "评论区",
    "全部评论",
    "大家都在搜",
    "AI 解析",
    "点踩",
    "关闭",
    "缩小评论区",
    "插入图片",
    "at",
    "表情",
    "作者",
    "全屏观看",
    "相关搜索",
    "拍同款",
)


def extract_public_content_from_xml(
    xml: str,
    *,
    platform: str,
    keyword: str = "",
    source_url: str = "ui://douyin/current",
    screenshot_path: str = "",
    raw_path: str = "",
    capture_method: str = "douyin_ui_public",
) -> SocialContent | None:
    labels = visible_labels(xml)
    metrics = extract_metrics(labels)
    title = extract_title(labels)
    author = extract_author(labels)
    product = extract_product(labels)

    if not (metrics or title or product):
        return None

    return SocialContent(
        platform=platform,
        keyword=keyword,
        source_url=source_url,
        author_name=author,
        title=title or product.get("product_title", ""),
        description=title,
        like_count=metrics.get("like_count", ""),
        comment_count=metrics.get("comment_count", ""),
        favorite_count=metrics.get("favorite_count", ""),
        share_count=metrics.get("share_count", ""),
        play_count=metrics.get("play_count", ""),
        product_title=product.get("product_title", ""),
        product_price=product.get("product_price", ""),
        product_pay_count=product.get("product_pay_count", ""),
        screenshot_path=screenshot_path,
        raw_path=raw_path,
        capture_method=capture_method,
    )


def extract_comments_from_xml(
    xml: str,
    *,
    platform: str,
    content_id: str = "",
    source_url: str = "ui://douyin/comments",
    limit: int = 20,
) -> list[SocialComment]:
    nodes = [node for node in parse_nodes(xml) if is_app_content_node(node)]
    labels = [node.label for node in nodes if node.label]
    start_index = find_comment_start_index(labels)
    if start_index == 0 and not any(any(marker in label for marker in COMMENT_PANEL_MARKERS) for label in labels):
        return []
    structured_comments = extract_sequenced_comments(labels, start_index, platform, content_id, source_url, limit)
    if structured_comments:
        return structured_comments
    if start_index > 0:
        return extract_structured_label_comments(labels, start_index, platform, content_id, source_url, limit)

    comments: list[SocialComment] = []
    seen: set[str] = set()

    for index, label in enumerate(labels[start_index:], start=start_index):
        structured = parse_structured_comment(label)
        if structured:
            text, author, likes = structured
            if text in seen:
                continue
            comments.append(
                SocialComment(
                    platform=platform,
                    content_id=content_id,
                    source_url=source_url,
                    comment_id=f"ui-comment-{len(comments) + 1}",
                    comment_text=text,
                    comment_author=author,
                    comment_likes=likes,
                )
            )
            seen.add(text)
            if len(comments) >= limit:
                break
            continue

        text = clean_comment_text(label)
        if not text or text in seen:
            continue
        author = nearest_author(labels, index)
        likes = nearest_metric_after(labels, index, aliases=("赞", "点赞"))
        comments.append(
            SocialComment(
                platform=platform,
                content_id=content_id,
                source_url=source_url,
                comment_id=f"ui-comment-{len(comments) + 1}",
                comment_text=text,
                comment_author=author,
                comment_likes=likes,
            )
        )
        seen.add(text)
        if len(comments) >= limit:
            break

    return comments


def extract_structured_label_comments(
    labels: list[str],
    start_index: int,
    platform: str,
    content_id: str,
    source_url: str,
    limit: int,
) -> list[SocialComment]:
    comments: list[SocialComment] = []
    seen: set[str] = set()
    for label in labels[start_index:]:
        structured = parse_structured_comment(label)
        if not structured:
            continue
        text, author, likes = structured
        if text in seen:
            continue
        comments.append(
            SocialComment(
                platform=platform,
                content_id=content_id,
                source_url=source_url,
                comment_id=f"ui-comment-{len(comments) + 1}",
                comment_text=text,
                comment_author=author,
                comment_likes=likes,
            )
        )
        seen.add(text)
        if len(comments) >= limit:
            break
    return comments


def has_comment_panel(xml: str) -> bool:
    labels = visible_labels(xml)
    return any(any(marker in label for marker in COMMENT_PANEL_MARKERS) for label in labels)


def is_app_content_node(node: UiNode) -> bool:
    if node.resource_id.startswith("com.android.systemui"):
        return False
    if node.center_y < 90 or node.center_y > 2100:
        return False
    return True


def extract_sequenced_comments(
    labels: list[str],
    start_index: int,
    platform: str,
    content_id: str,
    source_url: str,
    limit: int,
) -> list[SocialComment]:
    comments: list[SocialComment] = []
    seen: set[str] = set()
    index = start_index
    while index < len(labels) - 1:
        author = labels[index].strip()
        text = next_comment_body(labels, index + 1)
        if not is_comment_author(author) or not text:
            index += 1
            continue

        window = labels[index + 1 : index + 8]
        if not any(TIME_RE.match(item.strip()) or item.strip().startswith("·") for item in window):
            index += 1
            continue

        likes = ""
        for item in window:
            if "赞" not in item:
                continue
            match = COUNT_RE.search(item)
            likes = match.group("count") if match else likes
            break

        key = f"{author}|{text}"
        if key not in seen:
            comments.append(
                SocialComment(
                    platform=platform,
                    content_id=content_id,
                    source_url=source_url,
                    comment_id=f"ui-comment-{len(comments) + 1}",
                    comment_text=text,
                    comment_author=author,
                    comment_likes=likes,
                )
            )
            seen.add(key)
        if len(comments) >= limit:
            break
        index += 1
    return comments


def next_comment_body(labels: list[str], start_index: int) -> str:
    for label in labels[start_index : start_index + 4]:
        clean = clean_comment_text(label)
        if clean and not TIME_RE.match(clean) and not clean.startswith("·"):
            return clean
    return ""


def is_comment_author(label: str) -> bool:
    clean = label.strip()
    if not clean or len(clean) > 30:
        return False
    if is_noise(clean):
        return False
    if not re.search(r"[0-9A-Za-z_\u4e00-\u9fff]", clean):
        return False
    if TIME_RE.match(clean) or clean.startswith("·"):
        return False
    if COUNT_RE.fullmatch(clean):
        return False
    if any(token in clean for token in COMMENT_CONTROL_NOISE):
        return False
    if looks_like_metric_label(clean):
        return False
    return True


def extract_metrics(labels: list[str]) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for field, aliases in METRIC_ALIASES.items():
        value = find_metric(labels, aliases)
        if value:
            metrics[field] = value
    return metrics


def find_metric(labels: list[str], aliases: tuple[str, ...]) -> str:
    for label in labels:
        compact = label.replace("，", ",").replace(" ", "")
        if not any(alias in compact for alias in aliases):
            continue
        match = COUNT_RE.search(compact)
        if match:
            return match.group("count")

    for index, label in enumerate(labels):
        if any(label.strip() == alias for alias in aliases):
            for candidate in labels[index + 1 : index + 4]:
                if candidate in NAVIGATION_NOISE:
                    continue
                match = COUNT_RE.search(candidate)
                if match:
                    return match.group("count")
    return ""


def extract_title(labels: list[str]) -> str:
    candidates = []
    for label in labels:
        clean = label.strip()
        if is_noise(clean):
            continue
        if len(clean) < 6:
            continue
        if any(alias in clean for aliases in METRIC_ALIASES.values() for alias in aliases):
            continue
        if PRICE_RE.search(clean):
            continue
        candidates.append(clean)
    return candidates[0] if candidates else ""


def extract_author(labels: list[str]) -> str:
    for label in labels:
        clean = label.strip()
        if clean.startswith("@") and len(clean) > 1:
            return clean.lstrip("@")
        if "作者" in clean:
            parts = re.split(r"[:：,，]", clean, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return ""


def find_comment_start_index(labels: list[str]) -> int:
    for index, label in enumerate(labels):
        if any(marker in label for marker in COMMENT_PANEL_MARKERS):
            return index + 1
    return 0


def parse_structured_comment(label: str) -> tuple[str, str, str] | None:
    clean = label.strip()
    if not clean or any(marker in clean for marker in COMMENT_CONTROL_NOISE):
        return None
    parts = [part.strip() for part in re.split(r"[,，\n]", clean) if part.strip()]
    if len(parts) < 2:
        return None

    author = ""
    likes = ""
    body_parts: list[str] = []
    for part in parts:
        if not author and len(part) <= 30 and not TIME_RE.match(part) and "赞" not in part:
            author = part
            continue
        if "赞" in part:
            match = COUNT_RE.search(part)
            likes = match.group("count") if match else likes
            continue
        if TIME_RE.match(part):
            continue
        body_parts.append(part)

    text = "，".join(body_parts).strip()
    if not clean_comment_text(text):
        return None
    return text, author, likes


def extract_product(labels: list[str]) -> dict[str, str]:
    for index, label in enumerate(labels):
        match = PRICE_RE.search(label)
        if not match:
            continue
        title = nearest_title_before(labels, index) or nearest_title_after(labels, index)
        pay_count = nearest_metric_after(labels, index, aliases=("人付款", "已售", "销量"))
        return {
            "product_title": title,
            "product_price": match.group("price"),
            "product_pay_count": pay_count,
        }
    return {}


def nearest_title_before(labels: list[str], index: int) -> str:
    for label in reversed(labels[max(0, index - 6) : index]):
        clean = label.strip()
        if clean and not is_noise(clean) and not PRICE_RE.search(clean):
            return clean
    return ""


def nearest_title_after(labels: list[str], index: int) -> str:
    for label in labels[index + 1 : index + 6]:
        clean = label.strip()
        if clean and not is_noise(clean) and not PRICE_RE.search(clean):
            return clean
    return ""


def nearest_author(labels: list[str], index: int) -> str:
    for label in reversed(labels[max(0, index - 4) : index]):
        clean = label.strip()
        if clean and len(clean) <= 24 and not is_noise(clean) and not clean_comment_text(clean):
            return clean
    return ""


def nearest_metric_after(labels: list[str], index: int, aliases: tuple[str, ...]) -> str:
    for label in labels[index + 1 : index + 6]:
        if any(alias in label for alias in aliases):
            match = COUNT_RE.search(label)
            if match:
                return match.group("count")
    return ""


def clean_comment_text(label: str) -> str:
    clean = label.strip()
    if is_noise(clean) or len(clean) < 2:
        return ""
    if any(token in clean for token in COMMENT_CONTROL_NOISE):
        return ""
    if looks_like_metric_label(clean):
        return ""
    if COUNT_RE.fullmatch(clean):
        return ""
    if clean.startswith("@") and not any(separator in clean for separator in (":", "：", " ")):
        return ""
    if PRICE_RE.search(clean):
        return ""
    return clean if len(clean) <= 300 else ""


def is_noise(value: str) -> bool:
    if not value:
        return True
    clean = value.strip(" ，,")
    return clean in NAVIGATION_NOISE or clean.endswith("按钮")


def looks_like_metric_label(value: str) -> bool:
    clean = value.strip()
    aliases = {alias for alias_group in METRIC_ALIASES.values() for alias in alias_group}
    if not any(alias in clean for alias in aliases):
        return False
    return clean in aliases or "按钮" in clean or bool(COUNT_RE.search(clean))
