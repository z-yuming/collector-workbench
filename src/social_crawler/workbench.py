"""Adapters for collector modules stored within this project directory."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse, quote
from urllib.request import urlopen

from social_crawler.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = Path(os.environ.get("SCRAPER_WORKBENCH_ROOT", str(PROJECT_ROOT / "modules/scraper")))
SCRAPER_PYTHON = Path(os.environ.get("SCRAPER_WORKBENCH_PYTHON", os.environ.get("COLLECTOR_PYTHON", str(PROJECT_ROOT / ".venv/Scripts/python.exe"))))
SCRAPER_PORT = int(os.environ.get("SCRAPER_WORKBENCH_PORT", "5566"))
VIDEO_ROOT = Path(os.environ.get("VIDEO_PARSER_ROOT", str(PROJECT_ROOT / "modules/video-parser")))
VIDEO_PYTHON = Path(os.environ.get("VIDEO_PARSER_PYTHON", str(VIDEO_ROOT / "venv/Scripts/python.exe")))
_start_lock = threading.Lock()
_video_lock = threading.Lock()
_scraper_process: subprocess.Popen | None = None


def scraper_running() -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{SCRAPER_PORT}/api/platforms", timeout=1) as response:
            data = json.load(response)
            return isinstance(data, (dict, list)) and response.status == 200
    except Exception:
        return False


def module_status() -> dict:
    return {
        "ok": True,
        "scraper": {"running": scraper_running(), "available": (SCRAPER_ROOT / "app.py").is_file() and SCRAPER_PYTHON.is_file(), "url": f"http://127.0.0.1:{SCRAPER_PORT}/"},
        "video": {"available": (VIDEO_ROOT / "hermes_douyin.py").is_file() and VIDEO_PYTHON.is_file()},
    }


def start_scraper(settings: Settings) -> dict:
    global _scraper_process
    with _start_lock:
        if scraper_running():
            return module_status()
        if not (SCRAPER_ROOT / "app.py").is_file() or not SCRAPER_PYTHON.is_file():
            raise RuntimeError("店铺与竞品模块的运行环境不完整，请检查工作台模块目录。")
        user_launcher = Path(__file__).resolve().parents[2] / "scripts/start-scraper-module.ps1"
        if os.name == "nt" and user_launcher.is_file() and os.environ.get("COLLECTOR_PORTABLE") != "1":
            launch = subprocess.run(["schtasks.exe", "/Run", "/TN", "CollectorWorkbench-Scraper"], capture_output=True, timeout=10)
            if launch.returncode:
                raise RuntimeError("无法启动店铺模块的用户会话，请检查工作台启动配置。")
        elif _scraper_process is None or _scraper_process.poll() is not None:
            settings.log_dir.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "SCRAPER_UI_PORT": str(SCRAPER_PORT), "PYTHONIOENCODING": "utf-8"}
            with (settings.log_dir / "workbench-scraper.log").open("ab") as output:
                _scraper_process = subprocess.Popen(
                    [str(SCRAPER_PYTHON), str(SCRAPER_ROOT / "app.py")], cwd=SCRAPER_ROOT,
                    stdout=output, stderr=output, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
        for _ in range(20):
            if scraper_running():
                return module_status()
            if _scraper_process is not None and _scraper_process.poll() is not None:
                raise RuntimeError("店铺与竞品模块启动失败，请检查工作台运行环境。")
            time.sleep(0.25)
    raise RuntimeError("模块正在启动，请稍后点击刷新状态。")


def video_file(relative_path: str) -> Path:
    root = (VIDEO_ROOT / "downloads").resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("下载文件不存在。")
    return target


def _video_json(output: str) -> dict:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", output):
        try:
            result, _ = decoder.raw_decode(output[match.start():])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue
    raise RuntimeError("视频模块没有返回有效结果。")


def video_url(payload: dict) -> str:
    found = re.search(r"https?://[^\s<>\"'，。]+", str(payload.get("url") or ""))
    url = found.group(0) if found else ""
    parsed = urlparse(url)
    if parsed.hostname not in {"douyin.com", "www.douyin.com", "v.douyin.com"} or parsed.username or parsed.password:
        raise ValueError("请粘贴抖音视频或图集的分享链接。")
    return url


def run_video(payload: dict, settings: Settings, *, record_history: bool = True) -> dict:
    action = payload.get("action")
    if action not in {"parse", "download"}:
        raise ValueError("请选择解析信息或下载文件。")
    url = video_url(payload)
    if not VIDEO_PYTHON.is_file() or not (VIDEO_ROOT / "hermes_douyin.py").is_file():
        raise RuntimeError("视频解析模块的运行环境不完整。")
    if not _video_lock.acquire(blocking=False):
        raise RuntimeError("视频模块正在处理上一项任务，请等待完成。")
    try:
        command = [str(VIDEO_PYTHON), "hermes_douyin.py", "meta" if action == "parse" else "download", url]
        if action == "download":
            command += ["--output", str(VIDEO_ROOT / "downloads")]
        try:
            process = subprocess.run(command, cwd=VIDEO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("视频处理超时，请检查网络和链接后重试。") from exc
        raw = _video_json(process.stdout)
        if process.returncode or raw.get("error") or (action == "download" and raw.get("status") != "downloaded"):
            raise RuntimeError("视频处理失败，请确认链接可正常打开，并检查原视频项目的登录状态。")
        metadata = raw.get("meta", raw)
        allowed = {"desc", "title", "author", "author_name", "author_nickname", "nickname", "create_time", "duration", "aweme_id", "content_type", "image_count", "digg_count", "comment_count", "share_count", "collect_count"}
        metadata = {key: value for key, value in metadata.items() if key in allowed and isinstance(value, (str, int, float, bool))} if isinstance(metadata, dict) else {}
        if action == "parse" and not metadata:
            raise RuntimeError("视频模块没有返回可用信息，请检查链接后重试。")
        downloads = {}
        if action == "download":
            paths = raw.get("files") if isinstance(raw.get("files"), list) else [raw.get("path")]
            for index, path in enumerate(paths):
                if not isinstance(path, str) or path.startswith("FAIL:"):
                    continue
                try:
                    relative = Path(path).resolve().relative_to((VIDEO_ROOT / "downloads").resolve()).as_posix()
                    saved = video_file(relative)
                    if saved.stat().st_size:
                        downloads[saved.name] = "/api/workbench/video-file/" + quote(relative, safe="/")
                except (ValueError, OSError):
                    continue
            if not downloads:
                raise RuntimeError("视频模块未生成可用文件，请检查下载结果。")
        result = {"ok": True, "metadata": metadata, "downloadLinks": downloads, "action": action, "url": url}
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        entry = {"id": f"video-{time.time_ns()}", "source": "video", "createdAt": datetime.now().isoformat(timespec="seconds"), "platform": "douyin", "taskType": "media_download" if action == "download" else "media_parse", "query": url, "ok": True, "quality": {"status": "ok", "label": "已下载" if downloads else "已解析"}, "counts": {"contents": 1, "comments": 0}, "downloadLinks": downloads, "preview": {}, "metadata": metadata}
        if record_history:
            with (settings.log_dir / "workbench-video-history.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result
    finally:
        _video_lock.release()


def combined_history(primary: list[dict], settings: Settings, page: int, limit: int, source: str = "all") -> dict:
    if source not in {"all", "collect", "scraper", "video"}:
        raise ValueError("任务来源无效。")
    records = [{**row, "source": "collect"} for row in primary if isinstance(row, dict)]
    database = SCRAPER_ROOT / "data.db"
    if database.is_file():
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                for table in ["scrape_history", "crawler_jobs"]:
                    rows = connection.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
                    for row in rows:
                        row = dict(row)
                        pending = row.get("status") in {"running", "pending", "queued"}
                        ok = row.get("status") in {"success", "completed", "done"}
                        records.append({"id": f"scraper-{table}-{row['id']}", "source": "scraper", "createdAt": row.get("created_at", ""), "platform": row.get("platform", ""), "taskType": row.get("task_type") or "product", "query": row.get("keyword") or row.get("url") or row.get("shop_name") or "店铺任务", "ok": ok, "quality": {"status": "warning" if pending else "ok" if ok else "failed", "label": "处理中" if pending else "可用" if ok else "失败"}, "counts": {"contents": row.get("item_count", 0), "comments": 0}, "downloadLinks": {}, "preview": {}})
        except sqlite3.Error:
            pass
    video_history = settings.log_dir / "workbench-video-history.jsonl"
    if video_history.is_file():
        for line in video_history.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    records.append({**row, "source": "video"})
            except json.JSONDecodeError:
                continue
    known_files = {link for row in records if row.get("source") == "video" for link in row.get("downloadLinks", {}).values()}
    download_root = (VIDEO_ROOT / "downloads").resolve()
    if download_root.is_dir():
        from datetime import datetime
        for file in download_root.rglob("*"):
            if not file.is_file() or file.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv", ".mp3", ".m4a", ".jpg", ".jpeg", ".png", ".webp"}:
                continue
            try:
                relative = file.resolve().relative_to(download_root).as_posix()
                stat = file.stat()
            except (ValueError, OSError):
                continue
            link = "/api/workbench/video-file/" + quote(relative, safe="/")
            if not stat.st_size or link in known_files:
                continue
            records.append({"id": "saved-video-" + relative, "source": "video", "createdAt": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"), "platform": "douyin", "taskType": "saved_media", "query": file.name, "ok": True, "quality": {"status": "ok", "label": "已保存"}, "counts": {"contents": 1, "comments": 0}, "downloadLinks": {file.name: link}, "preview": {}})
    counts = {name: sum(row["source"] == name for row in records) for name in ["collect", "scraper", "video"]}
    selected = [row for row in records if source == "all" or row["source"] == source]
    selected.sort(key=lambda row: str(row.get("createdAt", "")), reverse=True)
    return {"items": selected[page * limit:(page + 1) * limit], "total": len(selected), "page": page, "limit": limit, "sourceCounts": counts}
