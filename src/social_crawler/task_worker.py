"""A managed task's isolated execution entry point. No user-provided commands."""
from __future__ import annotations

import argparse
from pathlib import Path

from social_crawler.preflight import check_task
from social_crawler.settings import Settings
from social_crawler.task_progress import callback, report
from social_crawler.task_store import TaskStore, now


def execute(store: TaskStore, task_id: str):
    task = store.get(task_id)
    settings = Settings.model_validate(task["settings"])

    def progress(stage, current, total, counts):
        changes = {"stage": stage, "progress": {"current": current, "total": total} if total else None}
        if counts is not None:
            changes["counts"] = counts
        store.update(task_id, expected={"running"}, **changes)

    token = callback.set(progress)
    try:
        check = check_task(task["source"], task["payload"], settings)
        if not check["ready"]:
            raise ValueError(next(c["message"] for c in check["checks"] if c["status"] == "blocked"))
        if task["source"] == "video":
            from social_crawler.workbench import run_video
            report("正在解析视频信息" if task["payload"]["action"] == "parse" else "正在下载视频或图集")
            result = run_video(task["payload"], settings, record_history=False)
            result.update(counts={"contents": 1, "comments": 0}, quality={"status": "ok"}, preview={})
        else:
            from social_crawler.web_app import run_collection
            result = run_collection(task["payload"], settings, record_history=False)
        status = "partial" if result.get("quality", {}).get("status") == "warning" else "success" if result.get("ok") else "failed"
        store.update(task_id, expected={"running"}, **{k: v for k, v in result.items() if k not in {"id", "status", "historyItem"}}, status=status, stage="任务完成，请确认提示" if status == "partial" else "任务完成" if status == "success" else "任务未完成，请查看原因", finishedAt=now(), progress=None)
    except Exception as exc:
        from social_crawler.web_app import friendly_error
        message = str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError)) else friendly_error(str(exc))
        store.update(task_id, expected={"running"}, status="failed", stage="任务失败", message=message, quality={"status": "failed", "warnings": [message]}, finishedAt=now(), progress=None)
    finally:
        callback.reset(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    execute(TaskStore(Path(args.db)), args.id)
