from __future__ import annotations

from dataclasses import dataclass

from social_crawler.ui_xml import UiNode, parse_nodes


@dataclass(frozen=True)
class SearchResultCandidate:
    row_id: str
    title: str
    author_name: str
    published_at: str
    like_count: str
    tap_x: int
    tap_y: int


def extract_video_candidates(xml: str) -> list[SearchResultCandidate]:
    nodes = parse_nodes(xml)
    desc_nodes = [node for node in nodes if node.resource_id.endswith(":id/desc") and node.label]
    candidates: list[SearchResultCandidate] = []
    seen: set[str] = set()

    for desc in desc_nodes:
        if desc.center_y < 480:
            continue
        nearby = _nearby_nodes(nodes, desc)
        author = _first_by_suffix(nearby, ":id/+j")
        published_at = _first_by_suffix(nearby, ":id/3+4")
        like_count = _first_by_suffix(nearby, ":id/n_=")
        tap_x = desc.center_x
        tap_y = max(520, desc.bounds[1] - 320)
        key = f"{desc.label}|{author}|{published_at}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            SearchResultCandidate(
                row_id=f"search-video:{key}",
                title=desc.label,
                author_name=author,
                published_at=published_at,
                like_count=like_count,
                tap_x=tap_x,
                tap_y=tap_y,
            )
        )
    return candidates


def _nearby_nodes(nodes: list[UiNode], desc: UiNode) -> list[UiNode]:
    left, _, right, bottom = desc.bounds
    return [
        node
        for node in nodes
        if left - 80 <= node.center_x <= right + 80 and bottom <= node.center_y <= bottom + 260
    ]


def _first_by_suffix(nodes: list[UiNode], suffix: str) -> str:
    for node in nodes:
        if node.resource_id.endswith(suffix):
            return node.label
    return ""
