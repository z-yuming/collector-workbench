from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from social_crawler import __version__
from social_crawler.exporters import export_result
from social_crawler.models import CollectionTask
from social_crawler.registry import get_collector
from social_crawler.settings import load_settings
from social_crawler.validator import validate_excel_export, write_validation_outputs
from social_crawler.web_app import run_app


app = typer.Typer(help="Public social platform data crawler platform.")
console = Console()


@app.command()
def version() -> None:
    console.print(__version__)


@app.command("app")
def start_app(
    host: str = typer.Option("127.0.0.1", help="Host for the local app"),
    port: int = typer.Option(8765, help="Port for the local app"),
    open_browser: bool = typer.Option(True, help="Open browser after starting"),
) -> None:
    run_app(host=host, port=port, open_browser=open_browser)


@app.command()
def collect(
    platform: str = typer.Option("douyin", help="Platform name: douyin, sample"),
    task_type: str = typer.Option("keyword", help="Task type: keyword, profile, content, comments, products"),
    query: str = typer.Option(..., help="Keyword, profile URL, or content URL"),
    limit: int = typer.Option(50, help="Max content rows or UI pages depending on collector"),
    comments: bool = typer.Option(False, help="Collect public comments when supported"),
    max_comments: int = typer.Option(20, help="Max comments per content item"),
    max_pages: int = typer.Option(3, help="Max search result pages for keyword video collection"),
    mode: str = typer.Option("ui", help="Collector mode: ui, web, api, sample"),
    serial: str | None = typer.Option(None, help="ADB serial for APP UI collectors"),
    resume: bool = typer.Option(False, help="Resume by skipping candidates stored in the task checkpoint"),
    output: Path | None = typer.Option(None, help="Output file path, default under data/exports"),
    formats: str = typer.Option("excel,jsonl,report", help="Comma-separated: excel,csv,jsonl,sqlite,report"),
    settings_path: Path | None = typer.Option(None, help="Optional settings JSON path"),
) -> None:
    settings = load_settings(settings_path)
    task = CollectionTask(
        platform=platform,
        task_type=task_type,  # type: ignore[arg-type]
        query=query,
        limit=limit,
        collect_comments=comments,
        max_comments_per_item=max_comments,
        max_pages=max_pages,
        mode=mode,
        serial=serial or settings.default_serial,
        resume=resume,
    )
    collector = get_collector(platform, mode, settings)

    console.print(f"[cyan]Collecting {platform}/{task_type}: {query}[/cyan]")
    result = collector.collect(task)
    output_path = output or settings.output_dir / f"{platform}_{task_type}_{_safe_name(query)}.xlsx"
    selected_formats = [item.strip().lower() for item in formats.split(",") if item.strip()]
    exported = export_result(result, output_path, selected_formats)

    console.print(
        f"[green]Done.[/green] contents={len(result.contents)}, "
        f"products={len(result.product_rows)}, comments={len(result.comments)}"
    )
    for name, path in exported.items():
        console.print(f"{name}: {path}")
    for warning in result.warnings:
        console.print(f"[yellow]Warning: {warning}[/yellow]")


@app.command("collect-and-validate")
def collect_and_validate(
    platform: str = typer.Option("douyin", help="Platform name: douyin, generic_web, sample"),
    task_type: str = typer.Option("keyword", help="Task type: keyword, profile, content, comments, products"),
    query: str = typer.Option(..., help="Keyword, profile URL, content URL, or local HTML path"),
    limit: int = typer.Option(50, help="Max content rows or UI pages depending on collector"),
    comments: bool = typer.Option(False, help="Collect public comments when supported"),
    max_comments: int = typer.Option(20, help="Max comments per content item"),
    max_pages: int = typer.Option(3, help="Max search result pages for keyword video collection"),
    mode: str = typer.Option("ui", help="Collector mode: ui, web, api, sample"),
    serial: str | None = typer.Option(None, help="ADB serial for APP UI collectors"),
    resume: bool = typer.Option(False, help="Resume by skipping candidates stored in the task checkpoint"),
    output: Path | None = typer.Option(None, help="Output file path, default under data/exports"),
    formats: str = typer.Option("excel,jsonl,report", help="Comma-separated: excel,csv,jsonl,sqlite,report"),
    min_contents: int = typer.Option(1, help="Minimum required rows in contents sheet"),
    min_comments: int = typer.Option(0, help="Minimum required rows in comments sheet"),
    check_evidence: bool = typer.Option(True, help="Check raw/screenshot evidence paths exist"),
    settings_path: Path | None = typer.Option(None, help="Optional settings JSON path"),
) -> None:
    settings = load_settings(settings_path)
    task = CollectionTask(
        platform=platform,
        task_type=task_type,  # type: ignore[arg-type]
        query=query,
        limit=limit,
        collect_comments=comments,
        max_comments_per_item=max_comments,
        max_pages=max_pages,
        mode=mode,
        serial=serial or settings.default_serial,
        resume=resume,
    )
    collector = get_collector(platform, mode, settings)

    console.print(f"[cyan]Collecting {platform}/{task_type}: {query}[/cyan]")
    result = collector.collect(task)
    output_path = output or settings.output_dir / f"{platform}_{task_type}_{_safe_name(query)}.xlsx"
    selected_formats = [item.strip().lower() for item in formats.split(",") if item.strip()]
    if "excel" not in selected_formats:
        selected_formats.append("excel")
    exported = export_result(result, output_path, selected_formats)
    excel_path = exported["excel"]

    report = validate_excel_export(
        excel_path,
        min_contents=min_contents,
        min_comments=min_comments,
        check_evidence=check_evidence,
    )
    validation_outputs = write_validation_outputs(report, excel_path)

    status = "[green]OK[/green]" if report.ok else "[red]FAILED[/red]"
    console.print(
        f"[green]Done.[/green] contents={len(result.contents)}, "
        f"products={len(result.product_rows)}, comments={len(result.comments)}"
    )
    console.print(f"Validation: {status}")
    console.print(f"errors={len(report.errors)}, warnings={len(report.warnings)}, missing_evidence={len(report.evidence_missing)}")
    for name, path in exported.items():
        console.print(f"{name}: {path}")
    for name, path in validation_outputs.items():
        console.print(f"validation_{name}: {path}")
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("validate-export")
def validate_export(
    export_path: Path = typer.Argument(..., help="Excel export path to validate"),
    require_comments: bool = typer.Option(False, help="Fail if comments sheet is empty"),
    min_contents: int = typer.Option(1, help="Minimum required rows in contents sheet"),
    min_comments: int = typer.Option(0, help="Minimum required rows in comments sheet"),
    check_evidence: bool = typer.Option(True, help="Check raw/screenshot evidence paths exist"),
) -> None:
    report = validate_excel_export(
        export_path,
        require_comments=require_comments,
        min_contents=min_contents,
        min_comments=min_comments,
        check_evidence=check_evidence,
    )
    outputs = write_validation_outputs(report, export_path)
    status = "[green]OK[/green]" if report.ok else "[red]FAILED[/red]"
    console.print(f"Validation: {status}")
    console.print(f"errors={len(report.errors)}, warnings={len(report.warnings)}, missing_evidence={len(report.evidence_missing)}")
    for name, path in outputs.items():
        console.print(f"{name}: {path}")
    if not report.ok:
        raise typer.Exit(code=1)


def _safe_name(value: str) -> str:
    keep = []
    for char in value.strip()[:60]:
        keep.append(char if char.isalnum() or char in ("-", "_") else "_")
    return "".join(keep).strip("_") or "task"


if __name__ == "__main__":
    app()
