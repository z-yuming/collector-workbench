from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TaskType = Literal["keyword", "profile", "content", "comments", "products"]


class CollectionTask(BaseModel):
    platform: str
    task_type: TaskType
    query: str
    limit: int = 50
    collect_comments: bool = False
    max_comments_per_item: int = 20
    max_pages: int = 3
    mode: str = "ui"
    serial: str | None = None
    resume: bool = False


class SocialContent(BaseModel):
    platform: str
    keyword: str = ""
    source_url: str = ""
    content_id: str = ""
    author_name: str = ""
    author_id: str = ""
    title: str = ""
    description: str = ""
    published_at: str = ""
    like_count: str = ""
    comment_count: str = ""
    favorite_count: str = ""
    share_count: str = ""
    play_count: str = ""
    product_title: str = ""
    product_price: str = ""
    product_original_price: str = ""
    product_pay_count: str = ""
    product_image_url: str = ""
    product_shop_name: str = ""
    screenshot_path: str = ""
    detail_data: dict = Field(default_factory=dict)
    raw_path: str = ""
    capture_method: str = ""
    collected_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class SocialComment(BaseModel):
    platform: str
    content_id: str = ""
    source_url: str = ""
    comment_id: str = ""
    comment_text: str = ""
    comment_author: str = ""
    comment_author_id: str = ""
    comment_likes: str = ""
    comment_time: str = ""
    screenshot_path: str = ""
    raw_path: str = ""
    collected_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class RunStat(BaseModel):
    scope: str
    name: str
    value: str = ""
    detail: str = ""
    collected_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class CollectionResult(BaseModel):
    task: CollectionTask
    contents: list[SocialContent] = Field(default_factory=list)
    comments: list[SocialComment] = Field(default_factory=list)
    run_stats: list[RunStat] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def product_rows(self) -> list[SocialContent]:
        return [row for row in self.contents if row.product_title or row.product_price]
