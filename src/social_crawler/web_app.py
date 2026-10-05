from __future__ import annotations

import functools
import gzip
import io
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import create_connection
from urllib import request as urlrequest
from urllib.parse import unquote, urlparse, quote

from douyin_crawler.device import DouyinDevice
from social_crawler.exporters import export_result
from social_crawler.models import CollectionResult, CollectionTask, RunStat
from social_crawler.registry import get_collector
from social_crawler.settings import Settings, load_settings
from social_crawler import workbench
from social_crawler.task_progress import report as report_progress
from social_crawler import results
from social_crawler.task_runtime import get_manager
from social_crawler.task_store import public_task
from social_crawler.validator import validate_excel_export, write_validation_outputs


STATIC_DIR = Path(__file__).parent / "web_static"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VIDEO_HELPER_ROOT = Path(os.environ.get("VIDEO_DOWNLOAD_HELPER_ROOT", str(PROJECT_ROOT / "tools/VideoDownloadHelper-windows-v0.2.4-20260706-141912")))
VIDEO_HELPER_DATA_ROOT = Path(os.environ.get("VIDEO_DOWNLOAD_HELPER_DATA_DIR", str(PROJECT_ROOT / "data/video-helper")))
VIDEO_HELPER_PORT = int(os.environ.get("VIDEO_DOWNLOAD_HELPER_PORT", "8766"))

# Static file cache (path -> (bytes, content_type))
_STATIC_CACHE: dict[str, tuple[bytes, str]] = {}
_CACHE_LOCK = threading.Lock()

# Screenshot cache
_SCREENSHOT_CACHE: dict[str, tuple[bytes, float]] = {}
_SCREENSHOT_TTL = 2.0  # seconds


def _preload_static() -> None:
    """Preload all static files into memory on startup."""
    for p in STATIC_DIR.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(STATIC_DIR)).replace("\\", "/")
            ct = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            _STATIC_CACHE[rel] = (p.read_bytes(), ct)
    # Ensure index.html is also mapped to "" and "/"
    if "index.html" in _STATIC_CACHE:
        data, ct = _STATIC_CACHE["index.html"]
        _STATIC_CACHE[""] = (data, ct)
        _STATIC_CACHE["/"] = (data, ct)


def _get_cached_static(request_path: str) -> tuple[bytes, str] | None:
    key = request_path.lstrip("/") if request_path not in ("", "/") else "index.html"
    return _STATIC_CACHE.get(key) or _STATIC_CACHE.get(request_path.lstrip("/"))


def _static_etag(data: bytes) -> str:
    return f'"{hash(data) & 0xFFFFFFFF:x}"'


def run_app(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> None:
    settings = load_settings()
    _preload_static()
    handler = make_handler(settings)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    print(f"Social crawler app running at {url}")
    _start_scheduler(settings)
    try:
        server.serve_forever()
    finally:
        get_manager(settings).close()
        server.server_close()


def make_handler(settings: Settings) -> type[BaseHTTPRequestHandler]:
    manager = get_manager(settings)
    class AppHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/tasks":
                self._json({"ok": True, "items": [public_task(t) for t in manager.store.active()]})
                return
            if parsed.path.startswith("/api/tasks/"):
                try:
                    self._json({"ok": True, "task": public_task(manager.store.get(unquote(parsed.path.removeprefix("/api/tasks/"))))})
                except KeyError as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path.startswith("/api/workbench/records/"):
                try:
                    self._json({"ok": True, "item": results.result_detail(settings, unquote(parsed.path.removeprefix("/api/workbench/records/")))})
                except (KeyError, ValueError) as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path.startswith("/api/workbench/result-file/"):
                try:
                    path = results.original_result_file(settings, unquote(parsed.path.removeprefix("/api/workbench/result-file/")))
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name))
                    self.end_headers()
                    with path.open("rb") as source:
                        shutil.copyfileobj(source, self.wfile)
                except ValueError as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/workbench/status":
                self._json(workbench.module_status())
                return
            if parsed.path == "/api/workbench/history":
                try:
                    page, limit = history_pagination(parsed.query)
                    params = parse_qs(parsed.query)
                    values = {key: params.get(key, [default])[0] for key, default in {"source": "all", "search": "", "status": "all", "platform": "", "start": "", "end": ""}.items()}
                    result = results.list_results(settings, page, limit, **values)
                    self._json({"ok": True, **result})
                except ValueError as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if parsed.path.startswith("/api/workbench/video-file/"):
                try:
                    path = workbench.video_file(unquote(parsed.path.removeprefix("/api/workbench/video-file/")))
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name))
                    self.end_headers()
                    from shutil import copyfileobj
                    with path.open("rb") as source:
                        copyfileobj(source, self.wfile)
                except ValueError:
                    self._json({"ok": False, "message": "下载文件不存在。"}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/health":
                self._json({"ok": True, "projectRoot": str(settings.project_root.resolve()), "pid": os.getpid()})
                return
            if parsed.path == "/api/device":
                self._json(device_status(settings))
                return
            if parsed.path == "/api/device/screenshot":
                self._serve_device_screenshot()
                return
            if parsed.path == "/api/schedules":
                with SCHEDULE_LOCK:
                    jobs = sorted(_schedule_jobs.values(), key=lambda j: j.get("nextRun", ""))
                self._json({"ok": True, "jobs": jobs})
                return
            if parsed.path == "/api/history":
                try:
                    page, limit = history_pagination(parsed.query)
                except ValueError as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                items, total = read_history_paginated(settings, page, limit)
                self._json({"ok": True, "items": items, "total": total, "page": page, "limit": limit})
                return
            if parsed.path == "/api/video-helper/status":
                self._json(video_helper_status())
                return
            if parsed.path.startswith("/api/file/"):
                self._serve_output_file(parsed.path.removeprefix("/api/file/"))
                return
            self._serve_static(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"/api/preflight", "/api/tasks"} or parsed.path.startswith("/api/tasks/"):
                try:
                    from social_crawler.preflight import check_task
                    body = self._read_json()
                    if not isinstance(body, dict):
                        raise ValueError("任务参数必须是对象。")
                    key = body.get("requestKey")
                    if key is not None and (not isinstance(key, str) or len(key) > 128):
                        raise ValueError("任务请求标识无效。")
                    if parsed.path == "/api/preflight":
                        self._json(check_task(body.get("source", "collect"), body.get("payload", {}), settings))
                    elif parsed.path == "/api/tasks":
                        task = manager.submit(body.get("source", "collect"), body.get("payload", {}), request_key=key)
                        self._json({"ok": True, "task": task}, status=HTTPStatus.ACCEPTED)
                    else:
                        parts = parsed.path.removeprefix("/api/tasks/").split("/")
                        if len(parts) != 2 or parts[1] not in {"cancel", "retry"}:
                            raise ValueError("任务操作无效。")
                        task_id = unquote(parts[0])
                        if parts[1] == "cancel":
                            task = manager.cancel(task_id)
                        else:
                            old = manager.store.get(task_id)
                            if old["status"] in {"queued", "running", "cancelling"}:
                                raise ValueError("任务尚未结束，请等待或取消后再重试。")
                            task = manager.submit(old["source"], old["payload"], request_key=body.get("requestKey"))
                            manager.store.update(task["id"], retryOf=old["id"])
                        self._json({"ok": True, "task": task})
                except (ValueError, KeyError, TypeError) as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception:
                    self._json({"ok": False, "message": "任务服务暂不可用，请刷新后重试。"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path in {"/api/workbench/scraper/start", "/api/workbench/video"}:
                try:
                    if parsed.path.endswith("/start"):
                        result = workbench.start_scraper(settings)
                    else:
                        task = manager.submit("video", self._read_json())
                        result = manager.store.wait(task["id"])
                    self._json(result)
                except (ValueError, RuntimeError) as exc:
                    self._json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception:
                    self._json({"ok": False, "message": "模块运行失败，请检查本地运行环境。"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/device/tap":
                try:
                    payload = self._read_json()
                    self._json(tap_device(settings, payload))
                except Exception as exc:
                    self._json(
                        {"ok": False, "error": str(exc), "message": friendly_error(str(exc))},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/device/mirror":
                try:
                    payload = self._read_json()
                    self._json(open_native_mirror(settings, payload))
                except Exception as exc:
                    self._json(
                        {"ok": False, "error": str(exc), "message": friendly_error(str(exc))},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/device/open-url":
                try:
                    payload = self._read_json()
                    self._json(open_url_on_device(settings, payload))
                except Exception as exc:
                    self._json(
                        {"ok": False, "error": str(exc), "message": friendly_error(str(exc))},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/video-helper/start":
                self._json(start_video_helper())
                return
            if parsed.path == "/api/video-helper/download":
                try:
                    payload = self._read_json()
                    self._json(video_helper_download(payload))
                except Exception as exc:
                    self._json(
                        {"ok": False, "error": str(exc), "message": friendly_error(str(exc))},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/video-helper/open-folder":
                self._json(video_helper_open_folder())
                return
            if parsed.path == "/api/schedules":
                payload = self._read_json()
                action = payload.get("action", "create")
                if action == "delete":
                    job_id = payload.get("id", "")
                    with SCHEDULE_LOCK:
                        _schedule_jobs.pop(job_id, None)
                    _remove_schedule_file(job_id)
                    self._json({"ok": True})
                    return
                now = datetime.now()
                job = {
                    "id": payload.get("id") or f"sch_{int(time.time()*1000)}",
                    "platform": payload.get("platform", "taobao"),
                    "mode": payload.get("mode", "adb"),
                    "taskType": payload.get("taskType", "products"),
                    "query": payload.get("query", ""),
                    "serial": payload.get("serial") or settings.default_serial,
                    "limit": int(payload.get("limit", 30)),
                    "interval": payload.get("interval", "6h"),
                    "enabled": bool(payload.get("enabled", True)),
                    "payload": payload,
                    "createdAt": now.isoformat(),
                    "lastRun": None,
                    "lastResult": None,
                    "lastCounts": {},
                }
                interval_min = _parse_interval(job["interval"])
                job["nextRun"] = (now + timedelta(minutes=interval_min)).isoformat()
                _save_schedule(job)
                with SCHEDULE_LOCK:
                    _schedule_jobs[job["id"]] = job
                self._json({"ok": True, "job": job})
                return
            if parsed.path != "/api/run":
                self._json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json()
                task = manager.submit("collect", payload)
                response = public_task(manager.store.wait(task["id"]))
                self._json(response)
            except Exception as exc:
                failure = record_failure(settings, payload if "payload" in locals() else {}, exc)
                self._json(
                    {
                        "ok": False,
                        "error": str(exc),
                        "message": failure["message"],
                        "quality": failure["quality"],
                        "historyItem": failure,
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1024 * 1024:
                raise ValueError("任务参数过大，请减少本次输入内容。")
            if not length:
                return {}
            raw_bytes = self.rfile.read(length)
            # Try common encodings for Chinese Windows environments
            for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    raw = raw_bytes.decode(enc)
                    return json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            # Last resort
            raw = raw_bytes.decode("utf-8", errors="replace")
            return json.loads(raw)

        def _send_response(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK,
                           extra_headers: dict | None = None, cache_max_age: int | None = None) -> None:
            # gzip if client accepts it and body is large enough
            accept_encoding = self.headers.get("Accept-Encoding", "")
            if "gzip" in accept_encoding and len(body) > 512 and content_type.startswith(("text/", "application/json", "application/javascript", "image/svg")):
                buf = io.BytesIO()
                with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
                    gz.write(body)
                body = buf.getvalue()
                extra_headers = (extra_headers or {}) | {"Content-Encoding": "gzip"}

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if cache_max_age is not None:
                self.send_header("Cache-Control", f"public, max-age={cache_max_age}")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_response(body, "application/json; charset=utf-8", status)

        def _serve_static(self, request_path: str) -> None:
            cached = _get_cached_static(request_path)
            if cached is None:
                # Fall back to disk for files not in preload cache
                path = STATIC_DIR / "index.html" if request_path in {"", "/"} else STATIC_DIR / request_path.lstrip("/")
                if not path.exists() or not path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body, ct = path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            else:
                body, ct = cached

            etag = _static_etag(body)
            if self.headers.get("If-None-Match") == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.end_headers()
                return

            # Revalidate local UI assets after a service update; do not retain stale task code.
            self._send_response(body, ct, extra_headers={"ETag": etag}, cache_max_age=0)

        def _serve_output_file(self, relative_name: str) -> None:
            name = unquote(relative_name)
            path = (settings.output_dir / name).resolve()
            if not path.is_relative_to(settings.output_dir.resolve()) or not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = path.read_bytes()
            ct = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._send_response(
                body, ct,
                extra_headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(path.name, safe="")},
                cache_max_age=300,
            )

        def _serve_device_screenshot(self) -> None:
            status = device_status(settings)
            serial = status.get("selectedSerial") or settings.default_serial
            if not status.get("devices") or not serial:
                self._json({"ok": False, "message": "没有检测到可用手机或模拟器"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                return

            now = time.time()
            cached = _SCREENSHOT_CACHE.get(serial)
            if cached and (now - cached[1]) < _SCREENSHOT_TTL:
                body = cached[0]
            else:
                result = run_adb(settings, ["-s", str(serial), "exec-out", "screencap", "-p"], binary=True)
                if result["returncode"] != 0 or not result["stdout"]:
                    self._json({"ok": False, "message": "手机截图失败"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                body = result["stdout"]
                _SCREENSHOT_CACHE[serial] = (body, now)

            self._send_response(body, "image/png", extra_headers={"Cache-Control": "no-store"})

    return AppHandler


def run_collection(payload: dict, settings: Settings, *, record_history: bool = True) -> dict:
    if bool(payload.get("batchLinks")):
        return run_batch_collection(payload, settings, record_history=record_history)

    task = build_task(payload, settings)
    collector = get_collector(task.platform, task.mode, settings)
    report_progress("正在读取采集内容")
    result = collector.collect(task)
    report_progress("正在生成文件并校验数据", counts={"contents": len(result.contents), "comments": len(result.comments)})
    response = export_and_validate(result, payload, settings, output_name(task))
    history_item = history_from_response(task, response, payload)
    if record_history:
        append_history(settings, history_item)
    response["historyItem"] = history_item
    return response


def run_batch_collection(payload: dict, settings: Settings, *, record_history: bool = True) -> dict:
    queries = split_batch_queries(str(payload.get("query") or ""))
    if not queries:
        raise ValueError("请至少粘贴一个视频链接")

    base_task = build_task({**payload, "query": "batch_links"}, settings)
    combined = CollectionResult(task=base_task)
    collector = get_collector(base_task.platform, base_task.mode, settings)

    for index, query in enumerate(queries, start=1):
        report_progress(f"正在处理第{index}/{len(queries)}条链接", index - 1, len(queries), {"contents": len(combined.contents), "comments": len(combined.comments)})
        task = build_task({**payload, "query": query, "limit": 1, "maxPages": 1}, settings)
        try:
            result = collector.collect(task)
            combined.contents.extend(result.contents)
            combined.comments.extend(result.comments)
            combined.run_stats.extend(result.run_stats)
            combined.warnings.extend(result.warnings)
            combined.run_stats.append(
                RunStat(scope="batch", name="link_done", value=str(index), detail=query)
            )
        except Exception as exc:
            combined.warnings.append(f"链接采集失败：{query}；原因：{friendly_error(str(exc))}")
            combined.run_stats.append(
                RunStat(scope="batch", name="link_failed", value=str(index), detail=f"{query} | {exc}")
            )

    combined.run_stats.append(RunStat(scope="batch", name="total_links", value=str(len(queries))))
    report_progress("正在生成批量结果并校验数据", len(queries), len(queries), {"contents": len(combined.contents), "comments": len(combined.comments)})
    combined.run_stats.append(RunStat(scope="batch", name="collected_contents", value=str(len(combined.contents))))
    response = export_and_validate(combined, payload, settings, output_name(base_task))
    history_item = history_from_response(base_task, response, payload)
    history_item["query"] = f"批量链接 {len(queries)} 条"
    if record_history:
        append_history(settings, history_item)
    response["historyItem"] = history_item
    return response


def export_and_validate(result: CollectionResult, payload: dict, settings: Settings, filename: str) -> dict:
    task = result.task
    output_path = settings.output_dir / output_name(task)
    if filename:
        output_path = settings.output_dir / filename
    formats = parse_formats(payload.get("formats") or "excel,jsonl,report")
    if "excel" not in formats:
        formats.append("excel")
    exported = export_result(result, output_path, formats)

    validation = validate_excel_export(
        exported["excel"],
        min_contents=int(payload.get("minContents") or 1),
        min_comments=int(payload.get("minComments") or 0),
        check_evidence=bool(payload.get("checkEvidence", True)),
    )
    validation_outputs = write_validation_outputs(validation, exported["excel"])
    quality = quality_summary(result, payload, validation.ok)
    return {
        "ok": validation.ok and quality["status"] != "failed",
        "quality": quality,
        "counts": {
            "contents": len(result.contents),
            "products": len(result.product_rows),
            "comments": len(result.comments),
            "warnings": len(result.warnings),
        },
        "validation": validation.to_dict(),
        "exports": {name: str(path) for name, path in exported.items()},
        "validationOutputs": {name: str(path) for name, path in validation_outputs.items()},
        "downloadLinks": download_links({**exported, **{f"validation_{k}": v for k, v in validation_outputs.items()}}, settings),
        "preview": preview_result(result),
    }


def build_task(payload: dict, settings: Settings) -> CollectionTask:
    max_comments = payload.get("maxComments")
    return CollectionTask(
        platform=str(payload.get("platform") or "sample"),
        task_type=str(payload.get("taskType") or "keyword"),  # type: ignore[arg-type]
        query=str(payload.get("query") or ""),
        limit=int(payload.get("limit") or 1),
        collect_comments=bool(payload.get("comments", True)),
        max_comments_per_item=int(max_comments if max_comments is not None else 1),
        max_pages=int(payload.get("maxPages") or 1),
        mode=str(payload.get("mode") or "sample"),
        serial=str(payload.get("serial") or settings.default_serial or "") or None,
        resume=bool(payload.get("resume", False)),
    )


def output_name(task: CollectionTask) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{task.platform}_{task.task_type}_{safe_name(task.query)}_{stamp}_{time.time_ns() % 1000000:06d}.xlsx"


def safe_name(value: str) -> str:
    keep = []
    for char in value.strip()[:50]:
        keep.append(char if char.isalnum() or char in ("-", "_") else "_")
    return "".join(keep).strip("_") or "task"


def parse_formats(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def split_batch_queries(value: str) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for line in value.replace(",", "\n").splitlines():
        clean = line.strip()
        if not clean:
            continue
        if "http" in clean and not clean.startswith(("http://", "https://")):
            clean = clean[clean.find("http") :]
        clean = clean.strip(" \t，,。；;")
        if clean and clean not in seen:
            queries.append(clean)
            seen.add(clean)
    return queries


def download_links(paths: dict[str, Path], settings: Settings) -> dict[str, str]:
    links: dict[str, str] = {}
    output_dir = settings.output_dir.resolve()
    for name, path in paths.items():
        resolved = path.resolve()
        if resolved.is_relative_to(output_dir):
            links[name] = f"/api/file/{quote(resolved.name, safe='')}"
    return links


def preview_result(result: CollectionResult, limit: int = 5) -> dict:
    return {
        "contents": [
            {
                "title": item.title or item.description or item.content_id,
                "author": item.author_name,
                "likes": item.like_count,
                "comments": item.comment_count,
                "favorites": item.favorite_count,
                "shares": item.share_count,
                "plays": item.play_count,
                "productTitle": item.product_title,
                "productPrice": item.product_price,
                "productOriginalPrice": item.product_original_price,
                "productPayCount": item.product_pay_count,
                "productImageUrl": item.product_image_url,
                "productShopName": item.product_shop_name,
                "sourceUrl": item.source_url,
            }
            for item in result.contents[:limit]
        ],
        "comments": [
            {
                "author": item.comment_author,
                "text": item.comment_text,
                "likes": item.comment_likes,
            }
            for item in result.comments[:limit]
        ],
    }


def quality_summary(result: CollectionResult, payload: dict, validation_ok: bool) -> dict:
    task_type = str(payload.get("taskType") or "")
    comments_requested = bool(payload.get("comments", True))
    strict_comments = bool(payload.get("strictComments", False))
    content_ok = len(result.contents) > 0
    comments_ok = len(result.comments) > 0
    products_ok = len(result.product_rows) > 0
    warnings: list[str] = []
    if task_type == "products":
        if not content_ok:
            warnings.append("没有采到商品数据；请确认手机已登录、没有协议/验证码弹窗，并且 APP 能正常打开商品/商城结果页。")
        elif content_ok and not products_ok:
            warnings.append("采到了结果，但没有识别到商品价格或商品字段，请确认 APP 已切到商品/商城结果页。")
    elif comments_requested and not comments_ok:
        warnings.append("没有采到评论；视频数据仍可用。可打开评论区后重试，或关闭评论采集。")
    if result.contents and task_type != "products":
        first = result.contents[0]
        if not (first.like_count or first.comment_count or first.favorite_count or first.share_count):
            warnings.append("没有识别到互动数据，请确认手机画面停在目标视频页。")
        if first.title.startswith("发布时间"):
            warnings.append("标题/文案识别不完整，但作者和互动数据可用。")
    status = "failed"
    label = "失败"
    if strict_comments and comments_requested and not comments_ok:
        status = "failed"
        label = "失败"
    elif validation_ok and content_ok and task_type == "products" and products_ok and not warnings:
        status = "ok"
        label = "可用"
    elif validation_ok and content_ok and task_type == "products":
        status = "warning"
        label = "需确认"
    elif validation_ok and content_ok and not warnings:
        status = "ok"
        label = "可用"
    elif validation_ok and content_ok:
        status = "warning"
        label = "需确认"
    return {
        "status": status,
        "label": label,
        "contentOk": content_ok,
        "commentsRequested": comments_requested,
        "strictComments": strict_comments,
        "commentsOk": comments_ok,
        "warnings": warnings,
    }


# ── History (with pagination + count limit) ────────────────────────

_HISTORY_MAX_LINES = 5000  # Keep at most 5000 entries


def history_path(settings: Settings) -> Path:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    return settings.log_dir / "task_history.jsonl"


def append_history(settings: Settings, item: dict) -> None:
    path = history_path(settings)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, ensure_ascii=False) + "\n")
    _trim_history_if_needed(path)


def _trim_history_if_needed(path: Path) -> None:
    """Keep history under _HISTORY_MAX_LINES by trimming oldest entries."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _HISTORY_MAX_LINES:
            path.write_text("\n".join(lines[-_HISTORY_MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def read_history(settings: Settings, limit: int = 20) -> list[dict]:
    """Backward-compatible: return last N items."""
    items, _ = read_history_paginated(settings, 0, limit)
    return items


def read_history_paginated(settings: Settings, page: int = 0, limit: int = 20) -> tuple[list[dict], int]:
    """Return (items, total_count) for paginated history reads."""
    path = history_path(settings)
    if not path.exists():
        return [], 0

    # Read from tail to avoid loading whole file
    all_lines = path.read_text(encoding="utf-8").splitlines()
    valid: list[dict] = []
    for line in reversed(all_lines):
        line = line.strip()
        if not line:
            continue
        try:
            valid.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    total = len(valid)
    start = page * limit
    end = start + limit
    return valid[start:end], total


def history_pagination(query: str) -> tuple[int, int]:
    params = parse_qs(query)
    try:
        page = int(params.get("page", ["0"])[0] or "0")
        limit = int(params.get("limit", ["20"])[0] or "20")
    except ValueError as exc:
        raise ValueError("任务记录页码和每页数量必须是整数。") from exc
    if page < 0 or limit < 1:
        raise ValueError("任务记录页码不能小于 0，每页至少显示 1 条。")
    return page, min(limit, 100)


def history_from_response(task: CollectionTask, response: dict, payload: dict | None = None) -> dict:
    created_at = datetime.now().isoformat(timespec="seconds")
    return {
        "id": f"{int(time.time() * 1000)}-{safe_name(task.query)}",
        "createdAt": created_at,
        "platform": task.platform,
        "mode": task.mode,
        "taskType": task.task_type,
        "query": task.query,
        "payload": safe_payload(payload or task.model_dump()),
        "ok": response["ok"],
        "quality": response.get("quality", {}),
        "counts": response["counts"],
        "downloadLinks": response["downloadLinks"],
        "preview": response["preview"],
    }


def record_failure(settings: Settings, payload: dict, exc: Exception) -> dict:
    message = friendly_error(str(exc))
    query = str(payload.get("query") or "")
    task_type = str(payload.get("taskType") or "content")
    item = {
        "id": f"{int(time.time() * 1000)}-failed-{safe_name(query)}",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "platform": str(payload.get("platform") or "douyin"),
        "mode": str(payload.get("mode") or "ui"),
        "taskType": task_type,
        "query": query,
        "payload": safe_payload(payload),
        "ok": False,
        "message": message,
        "error": str(exc),
        "quality": {
            "status": "failed",
            "label": "失败",
            "contentOk": False,
            "commentsRequested": bool(payload.get("comments", True)),
            "commentsOk": False,
            "warnings": [message],
        },
        "counts": {"contents": 0, "products": 0, "comments": 0, "warnings": 1},
        "downloadLinks": {},
        "preview": {"contents": [], "comments": []},
    }
    append_history(settings, item)
    return item


def safe_payload(payload: dict) -> dict:
    allowed = {
        "platform",
        "mode",
        "taskType",
        "query",
        "serial",
        "limit",
        "maxPages",
        "maxComments",
        "minContents",
        "minComments",
        "formats",
        "comments",
        "resume",
        "checkEvidence",
        "batchLinks",
        "strictComments",
    }
    return {key: value for key, value in payload.items() if key in allowed}


# ── Device / ADB ────────────────────────────────────────────────────

def device_status(settings: Settings) -> dict:
    adb_path = settings.adb_path
    package_name = settings.platform("douyin").package_name or "com.ss.android.ugc.aweme"
    if not adb_path.exists():
        return {
            "ok": False,
            "adbFound": False,
            "message": f"没有找到 ADB：{adb_path}",
            "devices": [],
        }

    output = run_adb(settings, ["devices"])
    if output["returncode"] != 0:
        return {
            "ok": False,
            "adbFound": True,
            "message": output["stderr"] or output["stdout"] or "ADB 检查失败",
            "devices": [],
        }

    devices = parse_adb_devices(output["stdout"])
    ready_devices = [item for item in devices if item["state"] == "device"]
    selected = choose_device(ready_devices, settings.default_serial)
    app_installed = False
    if selected:
        pm = run_adb(settings, ["-s", selected["serial"], "shell", "pm", "path", package_name])
        app_installed = pm["returncode"] == 0 and package_name in pm["stdout"]

    if not ready_devices:
        message = "没有检测到可用手机或模拟器"
    elif not app_installed:
        message = "设备已连接，但没有检测到抖音 APP"
    else:
        message = "设备可用，抖音 APP 已安装"

    return {
        "ok": bool(ready_devices and app_installed),
        "adbFound": True,
        "message": message,
        "defaultSerial": settings.default_serial,
        "selectedSerial": selected["serial"] if selected else "",
        "douyinInstalled": app_installed,
        "devices": devices,
    }


def run_adb(settings: Settings, args: list[str], *, binary: bool = False) -> dict:
    try:
        completed = subprocess.run(
            [str(settings.adb_path), *args],
            capture_output=True,
            text=not binary,
            timeout=8,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
        )
    except Exception as exc:
        return {"returncode": 1, "stdout": b"" if binary else "", "stderr": str(exc)}
    return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def parse_adb_devices(output: str) -> list[dict]:
    devices: list[dict] = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append({"serial": parts[0], "state": parts[1]})
    return devices


def choose_device(devices: list[dict], default_serial: str | None) -> dict | None:
    if not devices:
        return None
    if default_serial:
        for item in devices:
            if item["serial"] == default_serial:
                return item
    return devices[0]


def tap_device(settings: Settings, payload: dict) -> dict:
    status = device_status(settings)
    serial = str(payload.get("serial") or status.get("selectedSerial") or settings.default_serial or "")
    if not serial:
        return {"ok": False, "message": "没有检测到可用手机或模拟器"}
    x = int(float(payload.get("x")))
    y = int(float(payload.get("y")))
    result = run_adb(settings, ["-s", serial, "shell", "input", "tap", str(x), str(y)])
    if result["returncode"] != 0:
        return {"ok": False, "message": "点击发送失败", "error": result["stderr"] or result["stdout"]}
    return {"ok": True, "message": "已点击手机画面", "x": x, "y": y, "serial": serial}


def open_native_mirror(settings: Settings, payload: dict | None = None) -> dict:
    status = device_status(settings)
    serial = str((payload or {}).get("serial") or status.get("selectedSerial") or settings.default_serial or "")
    if not serial:
        return {"ok": False, "message": "没有检测到可用手机或模拟器"}
    scrcpy_path = find_scrcpy()
    if not scrcpy_path:
        return {"ok": False, "message": "没有找到 scrcpy，请先安装原生投屏组件"}
    args = [
        str(scrcpy_path),
        "--serial",
        serial,
        "--window-title",
        "采集助手 - 手机原生投屏",
        "--stay-awake",
    ]
    subprocess.Popen(args, cwd=str(scrcpy_path.parent), close_fds=True)
    return {"ok": True, "message": "已打开原生投屏窗口", "serial": serial, "scrcpy": str(scrcpy_path)}


def open_url_on_device(settings: Settings, payload: dict) -> dict:
    url = str(payload.get("url") or "").strip()
    if not url:
        return {"ok": False, "message": "请先粘贴视频链接"}
    status = device_status(settings)
    serial = str(payload.get("serial") or status.get("selectedSerial") or settings.default_serial or "")
    if not serial:
        return {"ok": False, "message": "没有检测到可用手机或模拟器"}
    package_name = settings.platform("douyin").package_name or "com.ss.android.ugc.aweme"
    target_url = DouyinDevice._normalize_douyin_url(url)
    result = run_adb(
        settings,
        [
            "-s",
            serial,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            target_url,
            "-p",
            package_name,
        ],
    )
    if result["returncode"] != 0:
        return {"ok": False, "message": "打开视频链接失败", "error": result["stderr"] or result["stdout"]}
    return {"ok": True, "message": "已发送到手机，请在手机画面确认是否打开目标视频", "serial": serial, "targetUrl": target_url}


def find_scrcpy() -> Path | None:
    command = shutil.which("scrcpy")
    if command:
        return Path(command)
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        local_app_data / "Microsoft" / "WinGet" / "Links" / "scrcpy.exe",
    ]
    packages = local_app_data / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        candidates.extend(packages.glob("Genymobile.scrcpy_*/*/scrcpy.exe"))
    for path in candidates:
        if path.exists():
            return path
    return None


def friendly_error(message: str) -> str:
    lower = message.lower()
    if "html source not found" in lower or "no such file" in lower:
        return "没有找到这个网页或文件，请检查链接/路径是否正确"
    if "unsupported collector" in lower:
        return "当前任务类型暂不支持，请换一种采集方式"
    if "adb" in lower and ("not found" in lower or "no such file" in lower):
        return "没有找到 ADB 工具，请检查 Android 环境"
    if "device" in lower and ("not found" in lower or "offline" in lower or "not online" in lower):
        return "没有检测到可用手机或模拟器，请检查连接状态"
    if "timed out" in lower or "timeout" in lower:
        return "采集超时，请检查网络、APP 页面或稍后重试"
    if "至少粘贴" in message:
        return message
    return "采集失败，请查看详细日志"


# ── Video Helper ────────────────────────────────────────────────────

def is_port_open(port: int) -> bool:
    try:
        with create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def video_helper_paths() -> dict[str, Path]:
    data_root = VIDEO_HELPER_DATA_ROOT
    return {
        "root": VIDEO_HELPER_ROOT,
        "start": VIDEO_HELPER_ROOT / "start_windows.bat",
        "latest": data_root / "captured-media" / "latest.json",
        "exports": data_root / "exports",
    }


def read_video_helper_latest() -> dict:
    latest = video_helper_paths()["latest"]
    if not latest.exists():
        return {}
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_video_helper_media(item: dict) -> bool:
    url = str(item.get("url") or "").strip()
    if not url:
        return False
    content_type = str(item.get("contentType") or "").split(";", 1)[0].strip().lower()
    if content_type.startswith(("video/", "audio/")) or content_type in {
        "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/x-mpegurl",
        "application/dash+xml", "application/mp4", "application/mp2t",
    }:
        return True
    if content_type and content_type not in {"application/octet-stream", "binary/octet-stream"}:
        return False
    path = unquote(urlparse(url).path).lower()
    if path.endswith((".js", ".jsx", ".tsx", ".json", ".html", ".htm", ".css", ".xml", ".map")):
        return False
    if path.endswith((".mp4", ".webm", ".mov", ".mkv", ".m4v", ".m3u8", ".mpd", ".m4s", ".ts", ".mp3", ".m4a", ".aac", ".ogg", ".wav")):
        return True
    return str(item.get("kind") or "").lower() in {"video", "audio", "hls", "dash", "manifest", "playlist", "segment"}


def video_helper_items(payload: dict) -> list[dict]:
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    items = state.get("items") if isinstance(state.get("items"), list) else []
    result: list[dict] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url or not is_video_helper_media(item):
            continue
        result.append(
            {
                "index": index,
                "url": url,
                "pageTitle": item.get("pageTitle") or "",
                "pageUrl": item.get("pageUrl") or "",
                "contentType": item.get("contentType") or "",
                "kind": item.get("kind") or "",
                "contentLength": item.get("contentLength") or 0,
                "authorName": item.get("authorName") or "",
                "videoTitle": item.get("videoTitle") or item.get("title") or "",
                "publishDate": item.get("publishDate") or "",
                "discoveredAt": item.get("discoveredAt") or "",
            }
        )
    return result


def video_helper_status() -> dict:
    paths = video_helper_paths()
    latest = read_video_helper_latest()
    items = video_helper_items(latest)
    running = is_port_open(VIDEO_HELPER_PORT)
    first_item = items[0] if items else {}
    state = latest.get("state") if isinstance(latest.get("state"), dict) else {}
    page_context = state.get("pageContext") if isinstance(state.get("pageContext"), dict) else {}
    return {
        "ok": True,
        "running": running,
        "port": VIDEO_HELPER_PORT,
        "root": str(paths["root"]),
        "startBat": str(paths["start"]),
        "latestPath": str(paths["latest"]),
        "exportsDir": str(paths["exports"]),
        "hasLatest": bool(latest),
        "reportedAt": latest.get("reportedAt", ""),
        "pageTitle": (page_context.get("title") or first_item.get("pageTitle", "")) if items else "",
        "tabUrl": state.get("tabUrl", ""),
        "items": items[:20],
        "message": "视频下载助手服务已连接" if running else "视频下载助手服务未启动",
    }


def start_video_helper() -> dict:
    if is_port_open(VIDEO_HELPER_PORT):
        return video_helper_status()
    start_bat = video_helper_paths()["start"]
    if not start_bat.exists():
        return {"ok": False, "running": False, "message": f"没有找到插件启动脚本：{start_bat}"}
    python = Path(os.environ.get("VIDEO_HELPER_PYTHON", str(VIDEO_HELPER_DATA_ROOT / "runtime/.venv/Scripts/python.exe")))
    server = VIDEO_HELPER_ROOT / "capture-server/capture_server.py"
    if not python.is_file() or not server.is_file():
        return {"ok": False, "running": False, "message": "视频捕获助手的运行环境不完整。"}
    VIDEO_HELPER_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with (VIDEO_HELPER_DATA_ROOT / "service.log").open("ab") as output:
        subprocess.Popen(
            [str(python), str(server)], cwd=server.parent, stdout=output, stderr=output,
            env={**os.environ, "VIDEO_DOWNLOAD_HELPER_DATA_DIR": str(VIDEO_HELPER_DATA_ROOT), "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            close_fds=True,
        )
    time.sleep(1)
    status = video_helper_status()
    status["ok"] = True
    status["message"] = "视频捕获助手已连接。" if status["running"] else "视频捕获助手正在启动，请稍后刷新状态。"
    return status


def post_video_helper(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        f"http://127.0.0.1:{VIDEO_HELPER_PORT}{path}",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def video_helper_download(payload: dict) -> dict:
    if not is_port_open(VIDEO_HELPER_PORT):
        raise RuntimeError("视频下载助手服务未启动")
    latest = read_video_helper_latest()
    state = latest.get("state") if isinstance(latest.get("state"), dict) else {}
    items = state.get("items") if isinstance(state.get("items"), list) else []
    media_items = [item for item in items if isinstance(item, dict) and is_video_helper_media(item)]
    if not media_items:
        raise RuntimeError("还没有捕获到视频媒体，请先在 Chrome 打开并播放视频")
    try:
        index = int(payload.get("index", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("请选择列表中的视频媒体") from exc
    if index < 0 or index >= len(items):
        raise RuntimeError("请选择列表中的视频媒体")
    selected = items[index]
    if not isinstance(selected, dict) or not is_video_helper_media(selected):
        raise RuntimeError("所选内容不是视频媒体，请刷新列表后重试")
    result = post_video_helper(
        "/complete-download",
        {
            "selected": selected,
            "items": media_items,
            "pageTitle": selected.get("pageTitle") or state.get("tabUrl") or "完整抓取视频",
            "authorName": selected.get("authorName") or "",
            "publishDate": selected.get("publishDate") or "",
        },
    )
    result["status"] = video_helper_status()
    return result


def video_helper_open_folder() -> dict:
    exports = video_helper_paths()["exports"]
    if is_port_open(VIDEO_HELPER_PORT):
        return post_video_helper("/open-path", {"path": str(exports)})
    if exports.exists():
        if os.name == "nt":
            os.startfile(str(exports))
        return {"ok": True, "message": "已打开导出目录"}
    return {"ok": False, "message": f"导出目录不存在：{exports}"}


# ── Export cleanup ─────────────────────────────────────────────────

def cleanup_old_exports(settings: Settings, max_age_days: int = 30) -> int:
    """Delete export files older than max_age_days. Returns count of removed files."""
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    export_dir = settings.output_dir
    if not export_dir.exists():
        return 0
    for p in export_dir.glob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


# ── Self-update check ───────────────────────────────────────────────

def parse_qs(query: str) -> dict[str, list[str]]:
    """Minimal query string parser (stdlib http.server doesn't expose parse_qs easily)."""
    result: dict[str, list[str]] = {}
    if not query:
        return result
    # Python 3.7+ has urllib.parse.parse_qs, but we import urlparse only via urllib.parse
    from urllib.parse import parse_qs as _parse_qs
    return _parse_qs(query)

# ── Scheduler ────────────────────────────────────────────────────────

SCHEDULE_DIR = Path(__file__).parent / "schedule_jobs"
SCHEDULE_LOCK = threading.Lock()
_schedule_jobs: dict[str, dict] = {}
_scheduler_running = False


def _parse_interval(interval_str: str) -> int:
    interval_str = interval_str.strip().lower()
    if interval_str.endswith("m"):
        return int(interval_str[:-1])
    if interval_str.endswith("h"):
        return int(interval_str[:-1]) * 60
    if interval_str.endswith("d"):
        return int(interval_str[:-1]) * 1440
    return 360


def _load_schedules() -> dict[str, dict]:
    jobs: dict[str, dict] = {}
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    for p in SCHEDULE_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            jobs[data.get("id", p.stem)] = data
        except Exception:
            pass
    return jobs


def _save_schedule(job: dict) -> None:
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    path = SCHEDULE_DIR / f"{job['id']}.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_schedule_file(job_id: str) -> None:
    path = SCHEDULE_DIR / f"{job_id}.json"
    if path.exists():
        path.unlink()


def _scheduler_thread(settings: Settings) -> None:
    global _schedule_jobs, _scheduler_running
    _scheduler_running = True
    while _scheduler_running:
        try:
            now = datetime.now()
            with SCHEDULE_LOCK:
                jobs = dict(_schedule_jobs)
            for job_id, job in jobs.items():
                if job.get("lastTaskId"):
                    try:
                        latest = get_manager(settings).store.get(job["lastTaskId"])
                        if latest["status"] != job.get("lastResult"):
                            job["lastResult"] = latest["status"]
                            job["lastCounts"] = latest.get("counts", {})
                            job["lastError"] = latest.get("message", "") if latest["status"] in {"failed", "interrupted"} else ""
                            _save_schedule(job)
                    except KeyError:
                        pass
                if not job.get("enabled", True):
                    continue
                next_run = job.get("nextRun")
                if next_run:
                    try:
                        next_dt = datetime.fromisoformat(next_run)
                    except Exception:
                        next_dt = None
                    if next_dt and now >= next_dt:
                        print(f"[Scheduler] Running {job_id}: {job.get('platform')}/{job.get('query')}")
                        job["lastRun"] = now.isoformat()
                        interval_min = _parse_interval(job.get("interval", "6h"))
                        job["nextRun"] = (now + timedelta(minutes=interval_min)).isoformat()
                        _save_schedule(job)
                        _execute_scheduled_job(job, settings)
        except Exception as exc:
            print(f"[Scheduler] Error: {exc}")
        time.sleep(30)


def _execute_scheduled_job(job: dict, settings: Settings) -> None:
    """Use the same parameter parser and device queue as manual execution."""
    try:
        payload = job.get("payload") or {key: job[key] for key in ("platform", "mode", "taskType", "query", "serial", "limit") if key in job}
        task = get_manager(settings).submit("collect", payload, schedule_id=job["id"])
        job["lastTaskId"] = task["id"]
        job["lastResult"] = task["status"]
        _save_schedule(job)
    except Exception as exc:
        job["lastResult"] = "error"
        job["lastError"] = str(exc)[:500]
        _save_schedule(job)


def _start_scheduler(settings: Settings) -> None:
    global _schedule_jobs, _scheduler_running
    _schedule_jobs = _load_schedules()
    if not _scheduler_running:
        threading.Thread(target=_scheduler_thread, args=(settings,), daemon=True).start()
