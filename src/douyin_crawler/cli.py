from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from douyin_crawler import __version__
from douyin_crawler.config import CrawlConfig
from douyin_crawler.device import DouyinDevice
from douyin_crawler.excel import jsonl_to_excel, rows_to_excel
from douyin_crawler.ui_scraper import extract_visible_products


app = typer.Typer(help="Douyin crawler for Android Emulator, mitmproxy, adb and uiautomator2.")
console = Console()


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def run(
    keyword: str = typer.Option(..., help="Product search keyword, for example nike"),
    pages: int = typer.Option(5, help="Swipe pages"),
    excel: Path = typer.Option(Path("output/products.xlsx"), help="Excel output file"),
    serial: str | None = typer.Option(None, help="adb serial, for example emulator-5554"),
    package: str = typer.Option("com.ss.android.ugc.aweme", help="Douyin package name"),
    proxy_port: int = typer.Option(8080, help="mitmproxy listen port"),
) -> None:
    config = CrawlConfig(
        keyword=keyword,
        pages=pages,
        excel_path=_excel_path(excel),
        output_dir=_excel_path(excel).parent,
        serial=serial,
        package_name=package,
        proxy_port=proxy_port,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if config.capture_path.exists():
        config.capture_path.unlink()

    mitm = start_mitmdump(config)
    try:
        console.print("[cyan]Starting Douyin automation...[/cyan]")
        device = DouyinDevice(config.serial, config.package_name)
        device.prepare()
        device.search(config.keyword)
        time.sleep(config.wait_after_search)
        device.swipe_pages(config.pages, config.wait_after_swipe)
        time.sleep(2)
    finally:
        mitm.terminate()
        try:
            mitm.wait(timeout=8)
        except subprocess.TimeoutExpired:
            mitm.kill()

    count = jsonl_to_excel(config.capture_path, config.excel_path)
    console.print(f"[green]Done.[/green] Exported {count} rows to {config.excel_path}")
    if count == 0:
        log_path = config.output_dir / "mitmproxy.log"
        if _has_certificate_trust_error(log_path):
            console.print(
                "[yellow]Douyin rejected the mitmproxy user certificate. "
                "API capture cannot read HTTPS responses in this emulator. "
                "Use run-ui for visible page data or an authorized data source for full product fields.[/yellow]"
            )
        else:
            console.print("[yellow]No API products were parsed. Check mitmproxy visibility and UI selectors.[/yellow]")


@app.command("run-ui")
def run_ui(
    keyword: str = typer.Option(..., help="Product search keyword, for example nike"),
    pages: int = typer.Option(5, help="Swipe pages"),
    excel: Path = typer.Option(Path("output/products_ui.xlsx"), help="Excel output file"),
    serial: str | None = typer.Option(None, help="adb serial, for example emulator-5554"),
    package: str = typer.Option("com.ss.android.ugc.aweme", help="Douyin package name"),
) -> None:
    excel_path = _excel_path(excel)

    console.print("[cyan]Starting UI-visible Douyin collection...[/cyan]")
    device = DouyinDevice(serial, package)
    device.prepare()
    device.search(keyword)
    time.sleep(4)
    device.tap_product_tab()

    rows = []
    for page in range(max(pages, 1)):
        console.print(f"[cyan]Reading visible page {page + 1}/{pages}[/cyan]")
        time.sleep(2)
        rows.extend(extract_visible_products(device.d.dump_hierarchy(), keyword))
        device.d.swipe_ext("up", scale=0.78)

    count = rows_to_excel(rows, excel_path)
    console.print(f"[green]Done.[/green] Exported {count} visible rows to {excel_path}")
    if count == 0:
        console.print("[yellow]No visible products were parsed. Confirm the app loaded results and the Product tab is visible.[/yellow]")


def start_mitmdump(config: CrawlConfig) -> subprocess.Popen:
    addon_path = Path(__file__).with_name("mitm_addon.py")
    log_path = config.output_dir / "mitmproxy.log"
    env = os.environ.copy()
    env["DOUYIN_CAPTURE_PATH"] = str(config.capture_path)
    env["DOUYIN_KEYWORD"] = config.keyword

    mitmdump_bin = Path(sys.executable).with_name("mitmdump.exe")
    command = [
        str(mitmdump_bin) if mitmdump_bin.exists() else "mitmdump",
        "-p",
        str(config.proxy_port),
        "-s",
        str(addon_path),
        "--set",
        "block_global=false",
    ]
    console.print(f"[cyan]Starting mitmdump on port {config.proxy_port}; log: {log_path}[/cyan]")
    try:
        log_file = log_path.open("w", encoding="utf-8", errors="replace")
        return subprocess.Popen(command, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        console.print("[red]mitmdump not found. Install requirements in the project venv first.[/red]")
        raise typer.Exit(code=1)


def _excel_path(path: Path) -> Path:
    if path.parent in (Path(""), Path(".")):
        return Path("output") / path.name
    return path


def _has_certificate_trust_error(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    text = log_path.read_text(encoding="utf-8", errors="ignore").lower()
    return "does not trust the proxy" in text or "certificate unknown" in text


if __name__ == "__main__":
    app()
