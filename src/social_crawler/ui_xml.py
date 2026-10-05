from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree


BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass(frozen=True)
class UiNode:
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    bounds: tuple[int, int, int, int]

    @property
    def label(self) -> str:
        return self.text or self.content_desc

    @property
    def center_x(self) -> int:
        return (self.bounds[0] + self.bounds[2]) // 2

    @property
    def center_y(self) -> int:
        return (self.bounds[1] + self.bounds[3]) // 2


def parse_nodes(xml: str) -> list[UiNode]:
    root = ElementTree.fromstring(xml)
    nodes: list[UiNode] = []
    for raw in root.iter("node"):
        nodes.append(
            UiNode(
                text=(raw.get("text") or "").strip(),
                content_desc=(raw.get("content-desc") or "").strip(),
                resource_id=(raw.get("resource-id") or "").strip(),
                class_name=(raw.get("class") or "").strip(),
                bounds=parse_bounds(raw.get("bounds") or ""),
            )
        )
    return nodes


def visible_labels(xml: str) -> list[str]:
    labels: list[str] = []
    for node in parse_nodes(xml):
        for value in (node.text, node.content_desc):
            if value and value not in labels:
                labels.append(value)
    return labels


def parse_bounds(value: str) -> tuple[int, int, int, int]:
    match = BOUNDS_RE.fullmatch(value)
    if not match:
        return (0, 0, 0, 0)
    return tuple(int(item) for item in match.groups())
