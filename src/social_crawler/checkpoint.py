from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from social_crawler.models import CollectionTask


class TaskCheckpoint(BaseModel):
    platform: str
    task_type: str
    query: str
    mode: str
    processed_candidate_ids: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def processed_set(self) -> set[str]:
        return set(self.processed_candidate_ids)

    def mark_processed(self, candidate_id: str) -> None:
        if candidate_id not in self.processed_candidate_ids:
            self.processed_candidate_ids.append(candidate_id)
        self.updated_at = datetime.now().isoformat(timespec="seconds")


def checkpoint_path(log_dir: Path, task: CollectionTask) -> Path:
    directory = log_dir / "checkpoints"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{task.platform}_{task.task_type}_{task.mode}_{safe_name(task.query)}.json"


def load_checkpoint(log_dir: Path, task: CollectionTask) -> TaskCheckpoint:
    path = checkpoint_path(log_dir, task)
    if not path.exists():
        return TaskCheckpoint(platform=task.platform, task_type=task.task_type, query=task.query, mode=task.mode)
    return TaskCheckpoint(**json.loads(path.read_text(encoding="utf-8")))


def save_checkpoint(log_dir: Path, task: CollectionTask, checkpoint: TaskCheckpoint) -> Path:
    path = checkpoint_path(log_dir, task)
    path.write_text(json.dumps(checkpoint.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def safe_name(value: str) -> str:
    safe = []
    for char in value.strip()[:60]:
        safe.append(char if char.isalnum() or char in ("-", "_") else "_")
    return "".join(safe).strip("_") or "task"
