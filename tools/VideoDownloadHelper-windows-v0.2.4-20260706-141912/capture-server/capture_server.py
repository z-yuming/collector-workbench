from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parent
APP_DATA_DIR_NAME = "VideoDownloadHelper"


def get_default_data_root() -> Path:
    configured = os.environ.get("VIDEO_DOWNLOAD_HELPER_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    system_name = platform.system().lower()
    if system_name == "darwin":
        movies_dir = Path.home() / "Movies"
        base_dir = movies_dir if movies_dir.exists() else Path.home() / "Downloads"
        return base_dir / APP_DATA_DIR_NAME

    if system_name == "windows":
        return ROOT.parents[2] / "data/video-helper"

    return Path.home() / APP_DATA_DIR_NAME


DATA_ROOT = get_default_data_root()
LEGACY_OUT_DIR = ROOT / "captured-media"
OUT_DIR = DATA_ROOT / "captured-media"
DOWNLOAD_DIR = OUT_DIR / "downloads"
EXPORT_DIR = DATA_ROOT / "exports"

OUT_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
LATEST_PATH = OUT_DIR / "latest.json"
LOG_PATH = OUT_DIR / "events.log"
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()


def migrate_legacy_data() -> None:
    if not LEGACY_OUT_DIR.exists() or LEGACY_OUT_DIR.resolve() == OUT_DIR.resolve():
        return

    for source in LEGACY_OUT_DIR.iterdir():
        target = OUT_DIR / source.name
        if target.exists():
            continue
        shutil.move(str(source), str(target))

    try:
        LEGACY_OUT_DIR.rmdir()
    except OSError:
        pass


migrate_legacy_data()


def sanitize_filename(text: str) -> str:
    filtered = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in str(text or "download"))
    collapsed = " ".join(filtered.split()).strip()
    return (collapsed or "download")[:80]


def normalize_label(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip()


def normalize_publish_date(text: str | None) -> str:
    value = normalize_label(text)
    if not value:
        return ""
    if len(value) == 5 and value.count("-") == 1:
        month, day = value.split("-", 1)
        if month.isdigit() and day.isdigit():
            return f"{month.zfill(2)}-{day.zfill(2)}"
    return value


def is_path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (headers or {}).items():
        name = str(key or "").strip().lower()
        if not name or value is None or name == "range":
            continue
        result[name] = str(value)
    return result


def extract_query_value(url: str, key: str) -> str:
    try:
        values = parse_qs(urlparse(url).query).get(key, [])
        return values[0] if values else ""
    except Exception:
        return ""


def extract_path_parts(url: str) -> list[str]:
    try:
        return [part for part in urlparse(url).path.split("/") if part]
    except Exception:
        return []


def get_path_marker(url: str, marker: str) -> str:
    parts = extract_path_parts(url)
    for index, part in enumerate(parts):
        if part == marker and index > 0:
            return parts[index - 1]
    return ""


def metadata_match_score(video_item: dict, candidate: dict) -> int:
    score = 0
    video_l = extract_query_value(video_item.get("url", ""), "l")
    candidate_l = extract_query_value(candidate.get("url", ""), "l")
    if video_l and candidate_l == video_l:
        score += 90

    video_dy_q = extract_query_value(video_item.get("url", ""), "dy_q")
    candidate_dy_q = extract_query_value(candidate.get("url", ""), "dy_q")
    if video_dy_q and candidate_dy_q == video_dy_q:
        score += 40

    video_path_token = get_path_marker(video_item.get("url", ""), "video")
    candidate_path_token = get_path_marker(candidate.get("url", ""), "video")
    if video_path_token and candidate_path_token == video_path_token:
        score += 160

    video_tos_token = get_path_marker(video_item.get("url", ""), "tos")
    candidate_tos_token = get_path_marker(candidate.get("url", ""), "tos")
    if video_tos_token and candidate_tos_token == video_tos_token:
        score += 70

    if candidate.get("pageUrl") and candidate.get("pageUrl") == video_item.get("pageUrl"):
        score += 10

    if normalize_label(candidate.get("authorName")):
        score += 30
    if normalize_label(candidate.get("videoTitle")):
        score += 30
    if normalize_publish_date(candidate.get("publishDate")):
        score += 50

    return score


def pick_best_metadata(video_item: dict, items: list[dict]) -> dict:
    direct_author = normalize_label(video_item.get("authorName"))
    direct_date = normalize_publish_date(video_item.get("publishDate"))
    direct_title = normalize_label(video_item.get("videoTitle"))
    if direct_author or direct_date or direct_title:
        return video_item

    candidates = [
        item for item in items
        if normalize_label(item.get("authorName")) or normalize_publish_date(item.get("publishDate")) or normalize_label(item.get("videoTitle"))
    ]
    if not candidates:
        return video_item

    best = max(candidates, key=lambda candidate: metadata_match_score(video_item, candidate))
    if metadata_match_score(video_item, best) < 120:
        return video_item
    return best


def is_dash_audio_candidate(item: dict) -> bool:
    url = str(item.get("url", ""))
    lowered = url.lower()
    content_type = str(item.get("contentType", "")).lower()
    return (
        "media-audio" in lowered
        or item.get("kind") == "audio"
        or content_type.startswith("audio/")
    )


def is_music_track_candidate(item: dict) -> bool:
    url = str(item.get("url", "")).lower()
    return (
        url.endswith(".mp3")
        or ".mp3?" in url
        or "ies-music" in url
        or "music-east" in url
    )


def needs_separate_audio(video_item: dict) -> bool:
    lowered = str(video_item.get("url", "")).lower()
    return "media-video-" in lowered


def download_file(item: dict, target_path: Path) -> None:
    request = urllib.request.Request(
        item["url"],
        headers=normalize_headers(item.get("requestHeaders")),
    )
    with urllib.request.urlopen(request, timeout=90) as response, target_path.open("wb") as out_file:
        while True:
            chunk = response.read(1024 * 512)
            if not chunk:
                break
            out_file.write(chunk)


def pick_best_audio(video_item: dict, items: list[dict]) -> dict | None:
    if not needs_separate_audio(video_item):
        return None

    audio_candidates = [
        item for item in items
        if is_dash_audio_candidate(item) and not is_music_track_candidate(item)
    ]
    if not audio_candidates:
        return None

    video_l = extract_query_value(video_item["url"], "l")
    video_dy_q = extract_query_value(video_item["url"], "dy_q")
    video_path_token = get_path_marker(video_item["url"], "video")
    video_tos_token = get_path_marker(video_item["url"], "tos")
    video_discovered = int(video_item.get("discoveredAt") or 0)
    strong_matches: list[tuple[dict, tuple[int, int]]] = []

    def score(candidate: dict) -> tuple[int, int]:
        score = 0
        candidate_l = extract_query_value(candidate["url"], "l")
        candidate_dy_q = extract_query_value(candidate["url"], "dy_q")
        candidate_path_token = get_path_marker(candidate["url"], "video")
        candidate_tos_token = get_path_marker(candidate["url"], "tos")

        if candidate_l == video_l and video_l:
            score += 80
        if candidate_dy_q == video_dy_q and video_dy_q:
            score += 40
        if candidate_path_token == video_path_token and video_path_token:
            score += 160
        if candidate_tos_token == video_tos_token and video_tos_token:
            score += 80
        if candidate.get("pageUrl") == video_item.get("pageUrl"):
            score += 10
        discovered = int(candidate.get("discoveredAt") or 0)
        if video_discovered and discovered:
            score += max(0, 30 - min(30, abs(video_discovered - discovered) // 100))
        score += min(20, int((candidate.get("contentLength") or 0) / 1024 / 64))
        return score, int(candidate.get("contentLength") or 0)

    for candidate in audio_candidates:
        candidate_score = score(candidate)
        candidate_l = extract_query_value(candidate["url"], "l")
        candidate_path_token = get_path_marker(candidate["url"], "video")
        if (
            candidate_score[0] >= 240
            or (video_l and candidate_l == video_l)
            or (video_path_token and candidate_path_token == video_path_token)
        ):
            strong_matches.append((candidate, candidate_score))

    if not strong_matches:
        return None

    return max(strong_matches, key=lambda entry: entry[1])[0]


def merge_streams(video_path: Path, audio_path: Path | None, output_path: Path) -> None:
    if not audio_path or not audio_path.exists():
        shutil.copy2(video_path, output_path)
        return

    command = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c",
        "copy",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg merge failed")


def open_output_path(target_path: Path) -> None:
    resolved = target_path.expanduser().resolve()
    system_name = platform.system().lower()

    directory = resolved if resolved.is_dir() else resolved.parent
    if not directory.exists():
        directory = EXPORT_DIR

    if system_name == "windows":
        if resolved.exists() and resolved.is_file():
            subprocess.Popen(["explorer.exe", f"/select,{resolved}"])
            return
        os.startfile(str(directory))
        return

    if system_name == "darwin":
        if resolved.exists() and resolved.is_file():
            subprocess.Popen(["open", "-R", str(resolved)])
            return
        subprocess.Popen(["open", str(directory)])
        return

    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, str(directory)])


def build_output_name(payload: dict, selected: dict) -> str:
    metadata = pick_best_metadata(selected, payload.get("items") or [])
    author_name = normalize_label(
        payload.get("authorName")
        or metadata.get("authorName")
        or selected.get("authorName")
    )
    publish_date = normalize_publish_date(
        payload.get("publishDate")
        or metadata.get("publishDate")
        or selected.get("publishDate")
    )
    fallback_title = normalize_label(
        payload.get("pageTitle")
        or selected.get("pageTitle")
        or selected.get("title")
        or "完整抓取视频"
    )

    if author_name and publish_date:
        base = sanitize_filename(f"{author_name}_{publish_date}")
    elif author_name:
        base = sanitize_filename(author_name)
    elif publish_date:
        base = sanitize_filename(publish_date)
    else:
        base = sanitize_filename(fallback_title)
    return f"{base}.mp4"


def run_complete_download(payload: dict) -> dict:
    selected = payload["selected"]
    items = payload["items"]
    output_name = payload.get("outputName") or build_output_name(payload, selected)
    output_path = EXPORT_DIR / output_name

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = DOWNLOAD_DIR / f"job-{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    video_path = work_dir / "video.mp4"
    download_file(selected, video_path)

    audio_item = pick_best_audio(selected, items)
    audio_path: Path | None = None
    if audio_item:
        audio_path = work_dir / "audio.mp4"
        download_file(audio_item, audio_path)

    merge_streams(video_path, audio_path, output_path)
    open_output_path(output_path)

    result = {
        "ok": True,
        "outputPath": str(output_path),
        "outputName": output_name,
        "outputSize": output_path.stat().st_size,
        "videoUrl": selected["url"],
        "audioUrl": audio_item["url"] if audio_item else "",
        "audioSize": audio_path.stat().st_size if audio_path and audio_path.exists() else 0,
    }

    shutil.rmtree(work_dir, ignore_errors=True)
    return result


class Handler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.end_headers()

    def parse_json_body(self) -> dict:
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/report":
            self.handle_report()
            return
        if self.path == "/complete-download":
            self.handle_complete_download()
            return
        if self.path == "/open-path":
            self.handle_open_path()
            return
        self.send_error(404, "Not Found")

    def handle_report(self) -> None:
        try:
            payload = self.parse_json_body()
        except Exception:
            self.send_error(400, "Invalid JSON")
            return

        LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

        self.send_json({"ok": True})

    def handle_complete_download(self) -> None:
        try:
            payload = self.parse_json_body()
            result = run_complete_download(payload)
            self.send_json(result)
        except Exception as error:
            self.send_json(
                {
                    "ok": False,
                    "error": str(error),
                },
                status=500,
            )

    def handle_open_path(self) -> None:
        try:
            payload = self.parse_json_body()
            path_text = str(payload.get("path") or "").strip()
            if not path_text:
                raise ValueError("Missing path")

            target_path = Path(path_text).expanduser()
            if not (
                is_path_within_root(target_path, DATA_ROOT)
                or is_path_within_root(target_path, EXPORT_DIR)
            ):
                raise ValueError("Path outside allowed directories")

            open_output_path(target_path)
            self.send_json({"ok": True})
        except Exception as error:
            self.send_json(
                {
                    "ok": False,
                    "error": str(error),
                },
                status=500,
            )

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    port = int(os.environ.get("VIDEO_DOWNLOAD_HELPER_PORT", "8766"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"capture server listening on http://127.0.0.1:{port}")
    print(f"exports directory: {EXPORT_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
