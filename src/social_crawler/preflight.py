"""Mode-specific checks, without claiming an unverified login is valid."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from social_crawler import workbench
from social_crawler.settings import Settings


def check_task(source: str, payload: dict, settings: Settings) -> dict:
    from social_crawler.web_app import build_task, safe_payload, run_adb, parse_adb_devices
    from social_crawler.registry import get_collector
    checks = []

    def add(key, label, status, message):
        checks.append({"key": key, "label": label, "status": status, "message": message})

    clean = {}
    try:
        if not isinstance(payload, dict):
            raise ValueError("任务参数必须是对象。")
        if source == "video":
            clean = {"action": payload.get("action"), "url": workbench.video_url(payload)}
            if clean["action"] not in {"parse", "download"}:
                raise ValueError("请选择解析信息或下载文件。")
            available = workbench.VIDEO_PYTHON.is_file() and (workbench.VIDEO_ROOT / "hermes_douyin.py").is_file()
            add("runtime", "视频组件", "ok" if available else "blocked", "视频组件已安装" if available else "视频组件不完整，请检查模块运行环境。")
            add("login", "链接与登录", "warning", "请确认链接可以正常打开；登录有效性将在执行时确认。")
        elif source == "collect":
            clean = safe_payload(payload)
            task = build_task(clean, settings)
            if not task.query.strip():
                raise ValueError("请填写关键词、链接或已保存网页路径。")
            if not 1 <= task.limit <= 10000 or not 1 <= task.max_pages <= 1000 or not 0 <= task.max_comments_per_item <= 10000:
                raise ValueError("数量和翻页数必须为正整数，评论数量不能小于0。")
            get_collector(task.platform, task.mode, settings)
            add("parameters", "任务参数", "ok", "平台、方式和参数可用")
            if task.mode in {"ui", "adb"}:
                if not settings.adb_path.is_file():
                    add("device", "手机连接", "blocked", "未找到手机连接组件，请检查ADB路径。")
                else:
                    result = run_adb(settings, ["devices"])
                    devices = parse_adb_devices(result["stdout"]) if result["returncode"] == 0 else []
                    serial = task.serial or next((d["serial"] for d in devices if d["state"] == "device"), "")
                    state = next((d["state"] for d in devices if d["serial"] == serial), "missing")
                    messages = {"unauthorized": "请在手机上允许USB调试授权，再检查连接。", "offline": "手机处于离线状态，请重新连接。"}
                    if state != "device":
                        add("device", "手机连接", "blocked", messages.get(state, "没有连接可用手机。请连接手机并开启USB调试，或选择浏览器/已保存网页方式。"))
                    else:
                        clean["serial"] = serial
                        add("device", "手机连接", "ok", f"手机已连接：{serial}")
                        aliases = {"tmall": "taobao", "pdd": "pinduoduo", "jingdong": "jd"}
                        platform = aliases.get(task.platform, task.platform)
                        packages = {"douyin": "com.ss.android.ugc.aweme", "taobao": "com.taobao.taobao", "jd": "com.jingdong.app.mall", "pinduoduo": "com.xunmeng.pinduoduo"}
                        package = settings.platform(platform).package_name or packages.get(platform)
                        if package:
                            pm = run_adb(settings, ["-s", serial, "shell", "pm", "path", package])
                            installed = pm["returncode"] == 0 and "package:" in pm["stdout"]
                            add("app", "目标APP", "ok" if installed else "blocked", "对应APP已安装" if installed else "设备上未找到对应APP，请先安装并正常登录。")
                        add("login", "APP登录", "warning", "登录状态待确认：请在手机上打开对应APP，确认已登录且没有验证弹窗。")
            elif task.mode == "browser":
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        installed = Path(p.chromium.executable_path).is_file()
                    add("browser", "浏览器组件", "ok" if installed else "blocked", "浏览器组件已安装" if installed else "缺少浏览器运行文件，请安装Chromium组件或使用已保存网页方式。")
                except Exception:
                    add("browser", "浏览器组件", "blocked", "浏览器组件无法加载，请检查本地运行环境。")
                add("login", "网站访问", "warning", "网站访问和登录状态将在执行时确认；遇到登录或验证限制，可使用已保存网页。")
            elif task.mode in {"search", "html"} or task.platform == "generic_web":
                query = task.query.strip().strip('"')
                remote = query.startswith(("https://", "http://"))
                local = Path(query)
                if not local.is_absolute():
                    local = settings.project_root / local
                if remote and task.platform == "generic_web":
                    add("input", "网页链接", "warning", "网页链接格式可用，网络可达性将在读取时确认。")
                elif local.is_file():
                    clean["query"] = str(local.resolve())
                    add("input", "已保存网页", "ok", "网页文件存在，可在本地读取")
                else:
                    add("input", "已保存网页", "blocked", "没有找到网页文件。请填写完整HTML文件路径，或改用浏览器搜索。")
        else:
            raise ValueError("任务来源无效。")
    except (ValueError, RuntimeError, OSError) as exc:
        add("parameters", "任务参数", "blocked", str(exc)[:500])

    try:
        folders = [settings.output_dir, settings.log_dir, settings.raw_dir, settings.screenshot_dir]
        if source == "video":
            folders.append(workbench.VIDEO_ROOT / "downloads")
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=folder):
                pass
        free = shutil.disk_usage(settings.output_dir).free
        add("storage", "文件保存", "blocked" if free < 10 * 1024**2 else "warning" if free < 512 * 1024**2 else "ok", "磁盘可用空间不足，请清理后再开始。" if free < 10 * 1024**2 else "保存目录可写，剩余空间较少。" if free < 512 * 1024**2 else "保存目录可写，磁盘空间充足")
    except OSError:
        add("storage", "文件保存", "blocked", "保存目录不可写，请检查文件夹权限或磁盘空间。")
    return {"ok": True, "ready": not any(c["status"] == "blocked" for c in checks), "checks": checks, "payload": clean}
