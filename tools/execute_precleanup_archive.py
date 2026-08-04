from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import read_json, write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_REPORT = ROOT / "docs" / "reports" / "precleanup_deep_audit_20260804.json"
DEFAULT_EXECUTION_JSON = ROOT / "docs" / "reports" / "precleanup_archive_execution_20260804.json"
DEFAULT_EXECUTION_MD = ROOT / "docs" / "reports" / "precleanup_archive_execution_20260804.md"


def norm_path(path: str | Path) -> str:
    value = str(path).replace("\\", "/").strip().strip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def is_inside(path: Path, parent: Path) -> bool:
    resolved = path.resolve()
    parent_resolved = parent.resolve()
    return resolved == parent_resolved or parent_resolved in resolved.parents


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(path: Path) -> dict[str, Any]:
    if path.is_file():
        return {"kind": "file", "file_count": 1, "total_bytes": path.stat().st_size, "sha256": sha256_file(path)}
    file_count = 0
    total_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            file_count += 1
            total_bytes += child.stat().st_size
    return {"kind": "directory", "file_count": file_count, "total_bytes": total_bytes, "sha256": ""}


def validate_item(item: dict[str, Any], expected_archive_root: str) -> tuple[Path, Path, list[str]]:
    source_rel = norm_path(item.get("path", ""))
    target_rel = norm_path(item.get("archive_target", ""))
    expected_archive_root_rel = norm_path(expected_archive_root)
    errors: list[str] = []
    if item.get("decision") != "archive_allowed":
        errors.append("decision_not_archive_allowed")
    if not source_rel or not target_rel:
        errors.append("missing_source_or_target")
    source = (ROOT / source_rel).resolve()
    target = (ROOT / target_rel).resolve()
    archive_root = (ROOT / expected_archive_root_rel).resolve()
    if not expected_archive_root_rel:
        errors.append("missing_expected_archive_root")
    if not is_inside(source, ROOT):
        errors.append("source_outside_workspace")
    if not is_inside(target, ROOT):
        errors.append("target_outside_workspace")
    if not is_inside(target, archive_root):
        errors.append("target_outside_archive_root")
    if target_rel == expected_archive_root_rel:
        errors.append("target_is_archive_root")
    if not source.exists():
        errors.append("source_missing")
    if target.exists():
        errors.append("target_exists")
    if source == target:
        errors.append("source_target_same")
    return source, target, errors


def execute_archive(audit_report: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    if audit_report.get("ok_to_execute_allowed_archive_roots") is not True:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": "audit_report_not_executable",
            "errors": [{"status": "blocked", "validation_errors": ["audit_report_not_executable"]}],
            "moves": [],
            "transactional_prevalidation": True,
            "rollback_attempted": False,
        }
    archive_root = norm_path(str(audit_report.get("archive_root") or ""))
    moves: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    planned: list[tuple[dict[str, Any], Path, Path]] = []
    for item in audit_report.get("allowed_archive_roots", []):
        source, target, validation_errors = validate_item(item, archive_root)
        move_record: dict[str, Any] = {
            "source": norm_path(source.relative_to(ROOT)) if is_inside(source, ROOT) else norm_path(item.get("path", "")),
            "target": norm_path(target.relative_to(ROOT)) if is_inside(target, ROOT) else norm_path(item.get("archive_target", "")),
            "dry_run": dry_run,
            "validation_errors": validation_errors,
            "status": "pending",
        }
        if validation_errors:
            move_record["status"] = "blocked"
            errors.append(move_record)
            moves.append(move_record)
            continue
        planned.append((move_record, source, target))
        moves.append(move_record)
    if errors:
        for move_record in moves:
            if move_record.get("status") == "pending":
                move_record["status"] = "not_started_due_to_prevalidation_error"
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": "prevalidation_failed",
            "errors": errors,
            "moves": moves,
            "transactional_prevalidation": True,
            "rollback_attempted": False,
        }
    moved: list[tuple[dict[str, Any], Path, Path]] = []
    rollback_attempted = False
    for move_record, source, target in planned:
        before = inventory(source)
        move_record["before"] = before
        if dry_run:
            move_record["status"] = "would_move"
        else:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append((move_record, source, target))
            except Exception as exc:
                move_record["status"] = "move_failed"
                move_record["error_type"] = type(exc).__name__
                errors.append(move_record)
                rollback_attempted = rollback_moves(moved)
                break
            after = inventory(target)
            move_record["after"] = after
            if before != after:
                move_record["status"] = "moved_with_inventory_mismatch"
                errors.append(move_record)
                rollback_attempted = rollback_moves(moved)
                break
            else:
                move_record["status"] = "moved"
    if errors:
        for move_record in moves:
            if move_record.get("status") == "pending":
                move_record["status"] = "not_started_due_to_prior_error"
    return {
        "ok": not errors,
        "dry_run": dry_run,
        "error": "" if not errors else "archive_execution_failed",
        "errors": errors,
        "moves": moves,
        "transactional_prevalidation": True,
        "rollback_attempted": rollback_attempted,
    }


def rollback_moves(moved: list[tuple[dict[str, Any], Path, Path]]) -> bool:
    attempted = False
    for move_record, source, target in reversed(moved):
        attempted = True
        try:
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
                move_record["rollback_status"] = "restored_source"
            else:
                move_record["rollback_status"] = "skipped_state_not_restorable"
        except Exception as exc:
            move_record["rollback_status"] = "rollback_failed"
            move_record["rollback_error_type"] = type(exc).__name__
    return attempted


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Precleanup Archive Execution 2026-08-04",
        "",
        f"- ok: `{report['ok']}`",
        f"- dry run: `{report['dry_run']}`",
        f"- error count: `{len(report.get('errors', []))}`",
        f"- transactional prevalidation: `{report.get('transactional_prevalidation')}`",
        f"- rollback attempted: `{report.get('rollback_attempted')}`",
        f"- move count: `{len(report['moves'])}`",
        "",
        "## Moves",
        "",
    ]
    for item in report["moves"]:
        lines.append(f"- `{item['status']}` `{item['source']}` -> `{item['target']}`")
        if item.get("validation_errors"):
            lines.append(f"  - validation errors: `{item['validation_errors']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive only allowed roots from the deep precleanup audit.")
    parser.add_argument("--audit-report", default=str(DEFAULT_AUDIT_REPORT.relative_to(ROOT)))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-json", default=str(DEFAULT_EXECUTION_JSON.relative_to(ROOT)))
    parser.add_argument("--output-md", default=str(DEFAULT_EXECUTION_MD.relative_to(ROOT)))
    args = parser.parse_args()
    audit_report = read_json(ROOT / args.audit_report)
    execution = execute_archive(audit_report, dry_run=bool(args.dry_run))
    report = {
        "schema_version": "precleanup_archive_execution.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "source_audit_report": norm_path(args.audit_report),
        **execution,
    }
    write_json(ROOT / args.output_json, report)
    write_text(ROOT / args.output_md, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
