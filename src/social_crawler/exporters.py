from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd
from pydantic import BaseModel

from social_crawler.models import CollectionResult


CONTENT_COLUMNS = [
    "platform",
    "keyword",
    "source_url",
    "content_id",
    "author_name",
    "author_id",
    "title",
    "description",
    "published_at",
    "like_count",
    "comment_count",
    "favorite_count",
    "share_count",
    "play_count",
    "product_title",
    "product_price",
    "product_original_price",
    "product_pay_count",
    "product_image_url",
    "product_shop_name",
    "screenshot_path",
    "raw_path",
    "capture_method",
    "collected_at",
]

COMMENT_COLUMNS = [
    "platform",
    "content_id",
    "source_url",
    "comment_id",
    "comment_text",
    "comment_author",
    "comment_author_id",
    "comment_likes",
    "comment_time",
    "screenshot_path",
    "raw_path",
    "collected_at",
]

RUN_STAT_COLUMNS = [
    "scope",
    "name",
    "value",
    "detail",
    "collected_at",
]


def export_result(result: CollectionResult, target: Path, formats: list[str]) -> dict[str, Path]:
    target.parent.mkdir(parents=True, exist_ok=True)
    exported: dict[str, Path] = {}
    stem = target.with_suffix("")

    if "excel" in formats:
        path = target if target.suffix.lower() in (".xlsx", ".xls") else stem.with_suffix(".xlsx")
        export_excel(result, path)
        exported["excel"] = path

    if "csv" in formats:
        path = stem.with_suffix(".csv")
        export_csv(result, path)
        exported["csv"] = path

    if "jsonl" in formats:
        path = stem.with_suffix(".jsonl")
        export_jsonl(result, path)
        exported["jsonl"] = path

    if "sqlite" in formats:
        path = stem.with_suffix(".sqlite")
        export_sqlite(result, path)
        exported["sqlite"] = path

    if "report" in formats:
        path = stem.with_suffix(".md")
        export_report(result, path)
        exported["report"] = path

    return exported


def export_excel(result: CollectionResult, path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _frame(result.contents, CONTENT_COLUMNS).to_excel(writer, sheet_name="contents", index=False)
        _frame(result.product_rows, CONTENT_COLUMNS).to_excel(writer, sheet_name="products", index=False)
        _frame(result.comments, COMMENT_COLUMNS).to_excel(writer, sheet_name="comments", index=False)
        _frame(result.run_stats, RUN_STAT_COLUMNS).to_excel(writer, sheet_name="run_stats", index=False)
        pd.DataFrame([result.task.model_dump()]).to_excel(writer, sheet_name="task", index=False)
        pd.DataFrame({"warning": result.warnings}).to_excel(writer, sheet_name="warnings", index=False)


def export_csv(result: CollectionResult, path: Path) -> None:
    _frame(result.contents, CONTENT_COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")
    if result.comments:
        _frame(result.comments, COMMENT_COLUMNS).to_csv(
            path.with_name(f"{path.stem}_comments.csv"),
            index=False,
            encoding="utf-8-sig",
        )


def export_jsonl(result: CollectionResult, path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for kind, rows in (("content", result.contents), ("comment", result.comments), ("run_stat", result.run_stats)):
            for row in rows:
                payload = {"type": kind, **row.model_dump()}
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def export_sqlite(result: CollectionResult, path: Path) -> None:
    with sqlite3.connect(path) as conn:
        _frame(result.contents, CONTENT_COLUMNS).to_sql("contents", conn, if_exists="replace", index=False)
        _frame(result.product_rows, CONTENT_COLUMNS).to_sql("products", conn, if_exists="replace", index=False)
        _frame(result.comments, COMMENT_COLUMNS).to_sql("comments", conn, if_exists="replace", index=False)
        _frame(result.run_stats, RUN_STAT_COLUMNS).to_sql("run_stats", conn, if_exists="replace", index=False)
        pd.DataFrame([result.task.model_dump()]).to_sql("task", conn, if_exists="replace", index=False)


def export_report(result: CollectionResult, path: Path) -> None:
    stats = _latest_stats(result)
    lines = [
        "# Collection Run Report",
        "",
        "## Task",
        "",
        f"- Platform: {result.task.platform}",
        f"- Task type: {result.task.task_type}",
        f"- Query: {result.task.query}",
        f"- Mode: {result.task.mode}",
        f"- Limit: {result.task.limit}",
        f"- Max comments per item: {result.task.max_comments_per_item}",
        f"- Max pages: {result.task.max_pages}",
        f"- Resume: {result.task.resume}",
        "",
        "## Summary",
        "",
        f"- Contents: {len(result.contents)}",
        f"- Products: {len(result.product_rows)}",
        f"- Comments: {len(result.comments)}",
        f"- Warnings: {len(result.warnings)}",
        f"- Attempted candidates: {stats.get('attempted_candidates', '')}",
        f"- Failed candidates: {stats.get('failed_candidates', '')}",
        f"- No-comment candidates: {stats.get('no_comment_candidates', '')}",
        f"- Resume skipped candidates: {stats.get('resume_skipped_candidates', '')}",
        f"- Pages visited: {stats.get('pages_visited', '')}",
        f"- Max pages: {stats.get('max_pages', '')}",
        f"- Checkpoint: {stats.get('checkpoint_path', '')}",
        "",
        "## Top Contents",
        "",
    ]
    if result.contents:
        for index, item in enumerate(result.contents[:10], start=1):
            lines.append(
                f"{index}. {item.title or item.description or item.content_id} | "
                f"author={item.author_name} | likes={item.like_count} | comments={item.comment_count}"
            )
    else:
        lines.append("- No content rows exported.")

    lines.extend(["", "## Comment Samples", ""])
    if result.comments:
        for index, item in enumerate(result.comments[:10], start=1):
            text = item.comment_text.replace("\n", " ")[:120]
            lines.append(f"{index}. {item.comment_author}: {text} | likes={item.comment_likes}")
    else:
        lines.append("- No comment rows exported.")

    lines.extend(["", "## Warnings", ""])
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Evidence", ""])
    raw_paths = _unique_values([item.raw_path for item in result.contents] + [item.raw_path for item in result.comments])
    screenshot_paths = _unique_values(
        [item.screenshot_path for item in result.contents] + [item.screenshot_path for item in result.comments]
    )
    lines.append(f"- Raw files: {len(raw_paths)}")
    lines.append(f"- Screenshot files: {len(screenshot_paths)}")
    for value in raw_paths[:10]:
        lines.append(f"- Raw: {value}")
    for value in screenshot_paths[:10]:
        lines.append(f"- Screenshot: {value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _latest_stats(result: CollectionResult) -> dict[str, str]:
    stats: dict[str, str] = {}
    for item in result.run_stats:
        stats[item.name] = item.value
    return stats


def _unique_values(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        unique.append(clean)
        seen.add(clean)
    return unique


def _frame(rows: Iterable[BaseModel], columns: list[str]) -> pd.DataFrame:
    data = [row.model_dump() for row in rows]
    frame = pd.DataFrame(data)
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]
