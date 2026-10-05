"""
Hermes 抖音无水印解析 CLI v2
================================
  python hermes_douyin.py download <url> [--quality 1080p]
  python hermes_douyin.py batch <user_url> [--pages 5] [--concurrent 4]
  python hermes_douyin.py list <user_url> [--pages 5]
  python hermes_douyin.py meta <url>
  python hermes_douyin.py user-from-video <url>
  python hermes_douyin.py check               # 验证 Cookie 是否有效
输出: JSON 到 stdout（batch 模式逐行输出进度 JSON）
"""

import sys, json, os, re, time, argparse, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from douyin_video_parser import DouyinVideoParser


# ── Cookie 管理 ──────────────────────────────────────────────

COOKIE_FILE = SCRIPT_DIR / "douyin_cookie.txt"

def load_cookie():
    try:
        return COOKIE_FILE.read_text("utf-8").lstrip("\ufeff").strip()
    except Exception:
        return ""

def cookie_is_loaded(dp):
    """检查 parser 是否带有效 Cookie"""
    return bool(dp.cookie and len(dp.cookie) > 50)


# ── Cookie 有效性检测 ────────────────────────────────────────

def check_cookie(dp):
    """用一个已知链接测试 Cookie 是否有效"""
    test_url = "https://www.douyin.com/user/MS4wLjABAAAAc8zBUlm6BFIMdkOHRhRwvtzswRAuJ8D1pcWjsALGjS4tZhumG95Yxt7WVm--EUnJ"
    try:
        urls = dp.get_user_aweme_urls(test_url, max_pages=1, count=1)
    except Exception as e:
        return {"valid": False, "error": str(e), "hint": "网络错误或 API 不可达"}
    if urls:
        return {"valid": True, "sample_url": urls[0]}
    # 如果能解析到用户页但无作品 → Cookie 可能有效但用户无作品
    # 用 meta 测试
    test_video = "https://www.douyin.com/video/7596624498590326201"
    meta = dp.parse_video_meta(test_video)
    if meta:
        return {"valid": True, "sample_meta": meta.get("desc", "")[:50]}
    return {"valid": False, "error": "Cookie 无效或已过期", "hint": "请重新获取 Cookie 后放入 douyin_cookie.txt"}


# ── 下载核心：单个视频 ────────────────────────────────────────

def _download_one(dp, url, quality=None, save_root=None, idx=0, total=0):
    """下载单个视频/图集，返回结果 dict"""
    result = dp.parse_video(url)
    if not result:
        return {"url": url, "status": "parse_failed", "error": "解析失败"}
    
    ct = result.get("content_type", "video")
    meta = {k: v for k, v in result.items() if k not in ("qualities", "nwm_url", "image_data")}
    
    save_root = Path(save_root or (SCRIPT_DIR / "downloads"))
    save_root.mkdir(parents=True, exist_ok=True)
    
    if ct == "video":
        qualities = result.get("qualities", [])
        if not qualities:
            return {"url": url, "status": "no_stream", "meta": meta}
        target = qualities[0]
        if quality:
            match = next((q for q in qualities if q.get("ratio") == quality), None)
            if match:
                target = match
        video_url = target["url"]
        filename = f"{result.get('aweme_id', 'video')}_{target['ratio']}.mp4"
        save_path = save_root / filename
        
        headers = {"User-Agent": dp.user_agent, "Referer": "https://www.douyin.com/"}
        try:
            req = urllib.request.Request(video_url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            save_path.write_bytes(data)
            return {
                "url": url, "status": "downloaded", "path": str(save_path),
                "filesize": len(data), "quality": target["quality_label"],
                "meta": meta, "index": idx, "total": total,
            }
        except Exception as e:
            return {"url": url, "status": "dl_failed", "error": str(e), "meta": meta}
    
    elif ct == "image":
        img_data = result.get("image_data", {})
        img_urls = img_data.get("image_urls", [])
        album_dir = save_root / str(result.get("aweme_id", "album"))
        album_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, img_url in enumerate(img_urls):
            try:
                ext = ".mp4" if img_data.get("is_live") else ".jpg"
                sp = album_dir / f"{i+1:03d}{ext}"
                req = urllib.request.Request(img_url, headers={"User-Agent": dp.user_agent})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    sp.write_bytes(resp.read())
                saved.append(str(sp))
            except Exception:
                saved.append(f"FAIL:{img_url[:50]}")
        return {
            "url": url, "status": "downloaded", "files": saved,
            "image_count": len(saved), "is_live": img_data.get("is_live", False),
            "meta": meta, "index": idx, "total": total,
        }
    
    return {"url": url, "status": "unknown", "meta": meta}


# ── 并发批量下载 ──────────────────────────────────────────────

_print_lock = Lock()

def batch_download(dp, urls, quality=None, concurrent=3, save_root=None):
    """并发下载多个视频，逐行输出 JSON 进度"""
    save_root = Path(save_root or (SCRIPT_DIR / "downloads"))
    total = len(urls)
    results = []
    completed = 0
    
    # 先输出 batch 头部
    _emit({"type": "batch_start", "total": total, "concurrent": concurrent})
    
    with ThreadPoolExecutor(max_workers=concurrent) as pool:
        futures = {
            pool.submit(_download_one, dp, url, quality, save_root, i, total): (i, url)
            for i, url in enumerate(urls)
        }
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            completed += 1
            _emit({
                "type": "progress",
                "completed": completed,
                "total": total,
                "item": r,
            })
    
    success = sum(1 for r in results if r.get("status") == "downloaded")
    _emit({
        "type": "batch_done",
        "total": total,
        "success": success,
        "failed": total - success,
        "save_root": str(save_root),
    })
    return results


def _emit(obj):
    """线程安全输出一行 JSON"""
    with _print_lock:
        print(json.dumps(obj, ensure_ascii=False), flush=True)


# ── CLI ───────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Hermes 抖音无水印解析器 v2")
    sub = ap.add_subparsers(dest="command", required=True)
    
    # download
    d = sub.add_parser("download", help="下载单个视频/图集")
    d.add_argument("url")
    d.add_argument("--quality")
    d.add_argument("--cookie")
    d.add_argument("--output", default=None, help="保存目录")
    
    # batch
    b = sub.add_parser("batch", help="批量并发下载用户主页全部作品")
    b.add_argument("user_url", help="用户主页或任意视频链接")
    b.add_argument("--pages", type=int, default=5)
    b.add_argument("--concurrent", type=int, default=3)
    b.add_argument("--quality")
    b.add_argument("--cookie")
    b.add_argument("--output")
    
    # list
    l = sub.add_parser("list", help="列出用户主页所有作品链接")
    l.add_argument("user_url")
    l.add_argument("--pages", type=int, default=5)
    l.add_argument("--cookie")
    
    # meta
    m = sub.add_parser("meta", help="仅获取视频/图集元数据")
    m.add_argument("url")
    m.add_argument("--cookie")
    
    # user-from-video
    ufv = sub.add_parser("user-from-video", help="从视频链接获取用户主页")
    ufv.add_argument("url")
    ufv.add_argument("--cookie")
    
    # check
    sub.add_parser("check", help="验证 Cookie 是否有效")
    
    args = ap.parse_args()
    dp = DouyinVideoParser()
    if not getattr(args, "cookie", None):
        dp.set_cookie(load_cookie())
    else:
        dp.set_cookie(args.cookie)
    
    try:
        if args.command == "check":
            print(json.dumps(check_cookie(dp), ensure_ascii=False, indent=2))
        
        elif args.command == "download":
            r = _download_one(dp, args.url, args.quality, args.output)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        
        elif args.command == "meta":
            r = dp.parse_video_meta(args.url)
            print(json.dumps(r or {"error": "解析失败"}, ensure_ascii=False, indent=2))
        
        elif args.command == "user-from-video":
            home = dp.get_user_home_from_video_url(args.url)
            print(json.dumps({"user_home": home} if home else {"error": "无法找到用户主页"}, ensure_ascii=False, indent=2))
        
        elif args.command == "list":
            urls = dp.get_user_aweme_urls(args.user_url, max_pages=min(args.pages, 20))
            print(json.dumps({"count": len(urls), "urls": urls}, ensure_ascii=False, indent=2))
        
        elif args.command == "batch":
            # 先拿列表
            urls = dp.get_user_aweme_urls(args.user_url, max_pages=min(args.pages, 20))
            if not urls:
                # 尝试从视频链接反查用户
                home = dp.get_user_home_from_video_url(args.user_url)
                if home:
                    urls = dp.get_user_aweme_urls(home, max_pages=min(args.pages, 20))
            if not urls:
                _emit({"type": "error", "error": "无法获取作品列表，请检查链接或 Cookie"})
                sys.exit(1)
            batch_download(dp, urls, args.quality, args.concurrent, args.output)
    
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()