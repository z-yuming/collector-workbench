from __future__ import annotations

from typing import Literal

from social_crawler.ui_xml import visible_labels


DouyinPageState = Literal["search_results", "comment_panel", "video_detail", "launching", "unknown"]


def detect_page_state(xml: str) -> DouyinPageState:
    labels = visible_labels(xml)
    joined = "\n".join(labels)

    if "火山引擎提供云和 AI 服务" in joined:
        return "launching"
    if "et_search_kw" in xml and "综合" in labels and "视频" in labels:
        return "search_results"
    if any("评论 " in label or "全部评论" in label or "写评论" in label for label in labels):
        return "comment_panel"
    if any("评论" in label and "按钮" in label for label in labels) and any(
        marker in joined for marker in ("未点赞", "收藏", "分享")
    ):
        return "video_detail"
    return "unknown"
