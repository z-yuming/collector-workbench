from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mitmproxy import http

from douyin_crawler.parser import extract_products


CAPTURE_PATH = Path(os.environ.get("DOUYIN_CAPTURE_PATH", "output/captured_products.jsonl"))
KEYWORD = os.environ.get("DOUYIN_KEYWORD", "")


class DouyinProductAddon:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        CAPTURE_PATH.parent.mkdir(parents=True, exist_ok=True)

    def response(self, flow: http.HTTPFlow) -> None:
        if not looks_like_target_response(flow):
            return

        payload = load_json(flow)
        if payload is None:
            return

        products = extract_products(payload, flow.request.pretty_url)
        if not products:
            return

        with CAPTURE_PATH.open("a", encoding="utf-8") as file:
            for product in products:
                row_id = product["row_id"]
                if row_id in self.seen:
                    continue
                self.seen.add(row_id)
                product["keyword"] = KEYWORD
                product["captured_at"] = datetime.now().isoformat(timespec="seconds")
                file.write(json.dumps(product, ensure_ascii=False) + "\n")


def looks_like_target_response(flow: http.HTTPFlow) -> bool:
    url = flow.request.pretty_url.lower()
    content_type = flow.response.headers.get("content-type", "").lower() if flow.response else ""
    if "application/json" not in content_type and "text/plain" not in content_type:
        return False
    host_ok = any(domain in url for domain in ("douyin.com", "snssdk.com", "amemv.com", "byte"))
    topic_ok = any(token in url for token in ("search", "product", "goods", "ecom", "commodity"))
    return host_ok and topic_ok


def load_json(flow: http.HTTPFlow) -> Any | None:
    if not flow.response:
        return None
    try:
        text = flow.response.get_text(strict=False)
        return json.loads(text)
    except Exception:
        return None


addons = [DouyinProductAddon()]

