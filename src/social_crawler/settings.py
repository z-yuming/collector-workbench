from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


DEFAULT_PROJECT_ROOT = Path(os.environ.get("COLLECTOR_PROJECT_ROOT", str(Path(__file__).resolve().parents[2])))


class PlatformSettings(BaseModel):
    package_name: str = ""
    max_comments_per_item: int = 20


class Settings(BaseModel):
    project_root: Path = DEFAULT_PROJECT_ROOT
    adb_path: Path = DEFAULT_PROJECT_ROOT / "platform-tools/adb.exe"
    default_serial: str | None = None
    default_platform: str = "douyin"
    default_mode: str = "ui"
    enable_mitm: bool = False
    output_dir: Path = DEFAULT_PROJECT_ROOT / "data/exports"
    log_dir: Path = DEFAULT_PROJECT_ROOT / "data/logs"
    screenshot_dir: Path = DEFAULT_PROJECT_ROOT / "data/screenshots"
    raw_dir: Path = DEFAULT_PROJECT_ROOT / "data/raw"
    platforms: dict[str, PlatformSettings] = Field(default_factory=dict)

    def ensure_dirs(self) -> None:
        for path in (self.output_dir, self.log_dir, self.screenshot_dir, self.raw_dir):
            path.mkdir(parents=True, exist_ok=True)

    def platform(self, name: str) -> PlatformSettings:
        return self.platforms.get(name, PlatformSettings())


def load_settings(path: Path | None = None) -> Settings:
    config_path = path or DEFAULT_PROJECT_ROOT / "config/settings.json"
    if not config_path.exists():
        settings = Settings()
        settings.ensure_dirs()
        return settings

    data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    # Relative settings travel with a source checkout or the portable package.
    project_root = Path(data.get("project_root", DEFAULT_PROJECT_ROOT))
    if not project_root.is_absolute():
        project_root = config_path.resolve().parent.parent / project_root
    data["project_root"] = project_root.resolve()
    for name in ("adb_path", "output_dir", "log_dir", "screenshot_dir", "raw_dir"):
        if name in data:
            value = Path(data[name])
            data[name] = value if value.is_absolute() else data["project_root"] / value
    platforms = {
        name: PlatformSettings(**value)
        for name, value in data.get("platforms", {}).items()
    }
    data["platforms"] = platforms
    settings = Settings(**data)
    settings.ensure_dirs()
    return settings
