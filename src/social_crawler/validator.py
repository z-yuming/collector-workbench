from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


REQUIRED_SHEETS = ("contents", "comments", "run_stats", "task", "warnings")


@dataclass
class ValidationReport:
    export_path: Path
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    evidence_missing: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> dict:
        return {
            "export_path": str(self.export_path),
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
            "evidence_missing": self.evidence_missing,
        }


def validate_excel_export(
    path: Path,
    *,
    require_comments: bool = False,
    min_contents: int = 1,
    min_comments: int = 0,
    check_evidence: bool = True,
) -> ValidationReport:
    report = ValidationReport(export_path=path)
    if not path.exists():
        report.fail(f"Export file does not exist: {path}")
        return report

    with pd.ExcelFile(path) as book:
        sheet_names = book.sheet_names
    missing_sheets = [sheet for sheet in REQUIRED_SHEETS if sheet not in sheet_names]
    if missing_sheets:
        report.fail(f"Missing required sheets: {', '.join(missing_sheets)}")
        return report

    frames = {sheet: pd.read_excel(path, sheet_name=sheet).fillna("") for sheet in REQUIRED_SHEETS}
    report.counts = {sheet: len(frame) for sheet, frame in frames.items()}

    required_comments = max(min_comments, 1 if require_comments else 0)
    if report.counts["contents"] < min_contents:
        report.fail(f"contents sheet has {report.counts['contents']} row(s), below minimum {min_contents}")
    if report.counts["comments"] < required_comments:
        report.fail(f"comments sheet has {report.counts['comments']} row(s), below minimum {required_comments}")
    if report.counts["run_stats"] == 0:
        report.warn("run_stats sheet is empty")
    if report.counts["warnings"]:
        report.warn(f"warnings sheet has {report.counts['warnings']} row(s)")

    if check_evidence:
        missing = missing_evidence_paths(frames["contents"], frames["comments"])
        report.evidence_missing = missing
        if missing:
            report.warn(f"{len(missing)} evidence path(s) do not exist")

    return report


def missing_evidence_paths(contents: pd.DataFrame, comments: pd.DataFrame) -> list[str]:
    missing: list[str] = []
    for frame in (contents, comments):
        for column in ("raw_path", "screenshot_path"):
            if column not in frame.columns:
                continue
            for value in frame[column].astype(str):
                clean = value.strip()
                if not clean or clean.lower() == "nan":
                    continue
                if not Path(clean).exists():
                    missing.append(clean)
    return missing


def write_validation_outputs(report: ValidationReport, target: Path) -> dict[str, Path]:
    target.parent.mkdir(parents=True, exist_ok=True)
    json_path = target.with_suffix(".validation.json")
    md_path = target.with_suffix(".validation.md")
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_validation_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def render_validation_markdown(report: ValidationReport) -> str:
    lines = [
        "# Export Validation Report",
        "",
        f"- Export: {report.export_path}",
        f"- OK: {report.ok}",
        "",
        "## Counts",
        "",
    ]
    for key, value in report.counts.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Errors", ""])
    lines.extend([f"- {item}" for item in report.errors] or ["- None"])

    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in report.warnings] or ["- None"])

    lines.extend(["", "## Missing Evidence", ""])
    lines.extend([f"- {item}" for item in report.evidence_missing[:50]] or ["- None"])
    return "\n".join(lines) + "\n"
