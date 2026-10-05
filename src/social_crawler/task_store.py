"""Persistent task state and searchable result index, shared by the app and workers."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from social_crawler.settings import Settings

ACTIVE = {"queued", "running", "cancelling"}
LABELS = {"queued": "排队中", "running": "处理中", "cancelling": "正在取消", "cancelled": "已取消", "success": "完成", "partial": "需确认", "failed": "失败", "interrupted": "运行中断"}


def now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def public_task(task: dict) -> dict:
    return {k: v for k, v in task.items() if k not in {"settings", "pid", "resource", "requestKey"}}


class TaskStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, status TEXT, resource TEXT, created TEXT, request_key TEXT UNIQUE, document TEXT);
                CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(status, created);
                CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, source TEXT, status TEXT, platform TEXT, created TEXT, query TEXT, document TEXT);
                CREATE INDEX IF NOT EXISTS records_page ON records(created DESC, id);
                CREATE INDEX IF NOT EXISTS records_filter ON records(source, status, created DESC);
                CREATE TABLE IF NOT EXISTS imports(name TEXT PRIMARY KEY, fingerprint TEXT);
            """)
            db.commit()

    @classmethod
    def for_settings(cls, settings: Settings) -> TaskStore:
        return cls(settings.log_dir.parent / "workbench/tasks.sqlite3")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def put_record(db, record):
        db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?)", (record["id"], record.get("source", "collect"), record.get("status", "success" if record.get("ok") else "failed"), record.get("platform", ""), record.get("createdAt", ""), record.get("query", ""), json.dumps(record, ensure_ascii=False)))

    def create(self, source: str, payload: dict, settings: Settings, resource: str, request_key: str | None = None, schedule_id: str | None = None) -> dict:
        task = {"id": "task-" + uuid.uuid4().hex, "source": source, "payload": payload, "platform": payload.get("platform", "douyin" if source == "video" else ""), "taskType": payload.get("taskType", "media_download" if payload.get("action") == "download" else "media_parse"), "query": payload.get("query") or payload.get("url", ""), "createdAt": now(), "status": "queued", "stage": "等待执行", "ok": False, "quality": {"status": "warning", "label": LABELS["queued"]}, "counts": {}, "preview": {}, "downloadLinks": {}, "events": [], "progress": None, "resource": resource, "settings": settings.model_dump(mode="json"), "scheduleId": schedule_id, "requestKey": request_key}
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if request_key:
                row = db.execute("SELECT document FROM tasks WHERE request_key=?", (request_key,)).fetchone()
                if row:
                    db.commit()
                    return json.loads(row[0])
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)", (task["id"], "queued", resource, task["createdAt"], request_key, json.dumps(task, ensure_ascii=False)))
            self.put_record(db, public_task(task))
            db.commit()
        return task

    def get(self, task_id: str) -> dict:
        with closing(self.connect()) as db:
            row = db.execute("SELECT document FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError("任务不存在。")
        return json.loads(row[0])

    def update(self, task_id: str, *, expected=None, **changes) -> dict:
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError("任务不存在。")
            task = json.loads(row[0])
            if expected is None or task["status"] in expected:
                stage = changes.get("stage")
                if stage and stage != task.get("stage"):
                    task["events"] = (task.get("events", []) + [{"at": now(), "stage": stage}])[-40:]
                task.update(changes)
                task["updatedAt"] = now()
                task["quality"] = {**task.get("quality", {}), "label": LABELS[task["status"]]}
                db.execute("UPDATE tasks SET status=?,document=? WHERE id=?", (task["status"], json.dumps(task, ensure_ascii=False), task_id))
                self.put_record(db, public_task(task))
            db.commit()
        return task

    def active(self) -> list[dict]:
        with closing(self.connect()) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT document FROM tasks WHERE status IN ('queued','running','cancelling') ORDER BY created,id")]

    def recover(self):
        for task in self.active():
            if task["status"] != "queued":
                self.update(task["id"], expected={"running", "cancelling"}, status="interrupted", stage="服务重启，任务已中断，可重试", message="上次运行被中断。已保留记录，请检查结果后重试。", finishedAt=now(), pid=None)

    def wait(self, task_id: str, timeout: float = 1800) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.get(task_id)
            if task["status"] not in ACTIVE:
                return task
            time.sleep(.2)
        return self.get(task_id)
