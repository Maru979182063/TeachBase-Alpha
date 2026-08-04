from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import read_json, write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTION_REPORT = ROOT / "docs" / "reports" / "precleanup_archive_execution_20260804.json"
DEFAULT_DEEP_AUDIT_REPORT = ROOT / "docs" / "reports" / "precleanup_deep_audit_20260804.json"
DEFAULT_REPORT_JSON = ROOT / "docs" / "reports" / "precleanup_post_archive_state_20260804.json"
DEFAULT_REPORT_MD = ROOT / "docs" / "reports" / "precleanup_post_archive_state_20260804.md"


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
    if not path.exists():
        return {"exists": False, "kind": "missing", "file_count": 0, "total_bytes": 0, "sha256": ""}
    if path.is_file():
        return {
            "exists": True,
            "kind": "file",
            "file_count": 1,
            "total_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    file_count = 0
    total_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            file_count += 1
            total_bytes += child.stat().st_size
    return {"exists": True, "kind": "directory", "file_count": file_count, "total_bytes": total_bytes, "sha256": ""}


def comparable_inventory(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": item.get("kind"),
        "file_count": item.get("file_count"),
        "total_bytes": item.get("total_bytes"),
        "sha256": item.get("sha256", ""),
    }


def archive_files(archive_root: Path) -> list[str]:
    if not archive_root.exists():
        return []
    return sorted(norm_path(path.relative_to(ROOT)) for path in archive_root.rglob("*") if path.is_file())


def inspect_move(move: dict[str, Any], archive_root: str) -> dict[str, Any]:
    source_rel = norm_path(str(move.get("source") or ""))
    target_rel = norm_path(str(move.get("target") or ""))
    source = (ROOT / source_rel).resolve()
    target = (ROOT / target_rel).resolve()
    archive_root_path = (ROOT / archive_root).resolve()
    source_state = inventory(source)
    target_state = inventory(target)
    expected = comparable_inventory(move.get("after", {}))
    actual = comparable_inventory(target_state)
    checks = {
        "move_record_status_moved": move.get("status") == "moved",
        "source_missing_after_archive": source_state["exists"] is False,
        "target_exists_after_archive": target_state["exists"] is True,
        "target_inside_archive_root": is_inside(target, archive_root_path),
        "execution_record_before_after_match": move.get("before") == move.get("after"),
        "target_inventory_matches_execution": actual == expected,
    }
    return {
        "source": source_rel,
        "target": target_rel,
        "checks": checks,
        "ok": all(checks.values()),
        "source_state": source_state,
        "target_state": target_state,
        "expected_target_state": expected,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    execution = read_json(Path(args.execution_report))
    deep_audit = read_json(Path(args.deep_audit_report))
    archive_root = norm_path(str(deep_audit.get("archive_root") or "_archive/precleanup_20260804"))
    move_inspections = [inspect_move(move, archive_root) for move in execution.get("moves", [])]
    expected_archive_targets = sorted(item["target"] for item in move_inspections)
    actual_archive_files = archive_files(ROOT / archive_root)
    unexpected_archive_files = sorted(set(actual_archive_files) - set(expected_archive_targets))
    missing_archive_files = sorted(set(expected_archive_targets) - set(actual_archive_files))
    blocked_by_path = {item.get("path"): item for item in deep_audit.get("blocked_roots", []) if isinstance(item, dict)}
    source_block_checks = []
    for item in move_inspections:
        blocked = blocked_by_path.get(item["source"], {})
        source_block_checks.append(
            {
                "source": item["source"],
                "blocked_in_current_deep_audit": bool(blocked),
                "has_path_missing_blocker": "path_missing" in blocked.get("blockers", []),
            }
        )
    baseline_block = blocked_by_path.get("outputs/pipeline_baseline_snapshot", {})
    checks = {
        "execution_report_successful_real_run": execution.get("ok") is True and execution.get("dry_run") is False,
        "current_deep_audit_not_executable": deep_audit.get("ok_to_execute_allowed_archive_roots") is False,
        "current_deep_audit_has_no_allowed_roots": not deep_audit.get("allowed_archive_roots"),
        "moved_sources_blocked_as_missing": all(
            item["blocked_in_current_deep_audit"] and item["has_path_missing_blocker"] for item in source_block_checks
        ),
        "baseline_snapshot_still_blocked_by_reference": "referenced_by_repo" in baseline_block.get("blockers", []),
        "all_move_inspections_ok": all(item["ok"] for item in move_inspections),
        "no_unexpected_archive_files": not unexpected_archive_files,
        "no_missing_archive_files": not missing_archive_files,
    }
    return {
        "schema_version": "precleanup_post_archive_state.v0.1",
        "report_phase": "post_archive_state_inspection",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "source_reports": {
            "execution_report": norm_path(args.execution_report),
            "deep_audit_report": norm_path(args.deep_audit_report),
        },
        "archive_root": archive_root,
        "checks": checks,
        "ok": all(checks.values()),
        "move_inspections": move_inspections,
        "source_block_checks": source_block_checks,
        "actual_archive_file_count": len(actual_archive_files),
        "expected_archive_file_count": len(expected_archive_targets),
        "unexpected_archive_files": unexpected_archive_files,
        "missing_archive_files": missing_archive_files,
        "baseline_snapshot_blockers": baseline_block.get("blockers", []),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Precleanup Post Archive State 2026-08-04",
        "",
        "This report inspects the filesystem after archive execution. It does not move, delete, or restore files.",
        "All paths are relative git paths; no local absolute path is part of the reproducible input contract.",
        "",
        "## Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- archive root: `{report['archive_root']}`",
        f"- expected archive files: `{report['expected_archive_file_count']}`",
        f"- actual archive files: `{report['actual_archive_file_count']}`",
        "",
        "## Checks",
        "",
    ]
    for name, value in report["checks"].items():
        lines.append(f"- `{name}`: `{value}`")
    lines.extend(["", "## Moves", ""])
    for item in report["move_inspections"]:
        lines.append(f"- `{item['source']}` -> `{item['target']}` ok=`{item['ok']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect post-archive cleanup state without changing files.")
    parser.add_argument("--execution-report", default=str(DEFAULT_EXECUTION_REPORT.relative_to(ROOT)))
    parser.add_argument("--deep-audit-report", default=str(DEFAULT_DEEP_AUDIT_REPORT.relative_to(ROOT)))
    parser.add_argument("--output-json", default=str(DEFAULT_REPORT_JSON.relative_to(ROOT)))
    parser.add_argument("--output-md", default=str(DEFAULT_REPORT_MD.relative_to(ROOT)))
    args = parser.parse_args()
    report = build_report(args)
    write_json(ROOT / args.output_json, report)
    write_text(ROOT / args.output_md, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
