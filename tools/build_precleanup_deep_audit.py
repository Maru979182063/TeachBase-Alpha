from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import read_json, write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
_TEXT_INDEX_CACHE: dict[tuple[str, tuple[str, ...]], list[tuple[Path, list[str]]]] = {}
DEFAULT_REPORT_JSON = ROOT / "docs" / "reports" / "precleanup_deep_audit_20260804.json"
DEFAULT_REPORT_MD = ROOT / "docs" / "reports" / "precleanup_deep_audit_20260804.md"
DEFAULT_EXECUTION_REPORT = ROOT / "docs" / "reports" / "precleanup_archive_execution_20260804.json"
DEFAULT_ARCHIVE_ROOT = "_archive/precleanup_20260804"
DEFAULT_SCAN_ROOTS = ["tools", "config", "docs", "tests", "package.json"]
GENERATED_REPORT_REFERENCE_PREFIXES = (
    "docs/reports/cleanup_candidates_",
    "docs/reports/final_chain_surface_classification_",
    "docs/reports/precleanup_archive_execution_",
    "docs/reports/precleanup_post_archive_state_",
    "docs/reports/precleanup_safety_gate_",
    "docs/reports/worktree_compartments_",
)
IGNORED_REFERENCE_PREFIXES = ("docs/reports/precleanup_deep_audit_",)
GUARD_METADATA_REFERENCE_PREFIXES = ("tools/build_worktree_compartment_report.py:",)


def norm_path(path: str | Path) -> str:
    value = str(path).replace("\\", "/").strip().strip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def is_child(path: str, parent: str) -> bool:
    path_norm = norm_path(path)
    parent_norm = norm_path(parent)
    return path_norm != parent_norm and path_norm.startswith(parent_norm + "/")


def is_same_or_child(path: str, parent: str) -> bool:
    return norm_path(path) == norm_path(parent) or is_child(path, parent)


def run_rg(pattern: str, scan_roots: list[str], max_hits: int) -> list[str]:
    existing_roots = [root for root in scan_roots if (ROOT / root).exists() or (ROOT / root).is_file()]
    cmd = ["rg", "--fixed-strings", "--no-heading", "--line-number", "--color", "never", pattern, *existing_roots]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except FileNotFoundError:
        return _python_fixed_string_search(pattern, existing_roots, max_hits)
    except subprocess.TimeoutExpired:
        return []
    if proc.returncode not in {0, 1}:
        return _python_fixed_string_search(pattern, existing_roots, max_hits)
    hits: list[str] = []
    for line in proc.stdout.splitlines():
        normalized = line.replace("\\", "/")
        if normalized not in hits:
            hits.append(normalized)
        if len(hits) >= max_hits:
            break
    return hits


def _python_fixed_string_search(pattern: str, scan_roots: list[str], max_hits: int) -> list[str]:
    """在没有 ripgrep 的 Windows runner 上执行等价的只读引用扫描。"""
    cache_key = (str(ROOT.resolve()), tuple(scan_roots))
    indexed_files = _TEXT_INDEX_CACHE.get(cache_key)
    if indexed_files is None:
        indexed_files = []
        _TEXT_INDEX_CACHE[cache_key] = indexed_files

    paths: list[Path] = []
    if not indexed_files:
        for relative in scan_roots:
            root = ROOT / relative
            if root.is_file():
                paths.append(root)
            elif root.is_dir():
                paths.extend(path for path in root.rglob("*") if path.is_file())
        for path in sorted(set(paths)):
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            if "\x00" not in text:
                indexed_files.append((path, text.splitlines()))

    hits: list[str] = []
    for path, lines in indexed_files:
        for line_number, line in enumerate(lines, start=1):
            if pattern in line:
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{line_number}:{line}")
                if len(hits) >= max_hits:
                    return hits
    return hits


def reference_patterns(path: str) -> list[str]:
    normalized = norm_path(path)
    name = Path(normalized).name
    stem = Path(normalized).stem
    patterns = [normalized, normalized.replace("/", "\\"), name]
    if stem and stem != name:
        patterns.append(stem)
    return sorted(set(item for item in patterns if item))


def find_references(path: str, scan_roots: list[str], max_hits: int) -> list[str]:
    hits: list[str] = []
    path_norm = norm_path(path)
    for pattern in reference_patterns(path_norm):
        for hit in run_rg(pattern, scan_roots, max_hits):
            if hit.startswith(path_norm + ":"):
                continue
            if hit.startswith(IGNORED_REFERENCE_PREFIXES):
                continue
            if hit not in hits:
                hits.append(hit)
            if len(hits) >= max_hits:
                return hits
    return hits


def split_references(references: list[str]) -> tuple[list[str], list[str], list[str]]:
    blocking: list[str] = []
    generated_report_only: list[str] = []
    guard_metadata_only: list[str] = []
    for reference in references:
        normalized = reference.replace("\\", "/")
        if normalized.startswith(GENERATED_REPORT_REFERENCE_PREFIXES):
            generated_report_only.append(reference)
        elif normalized.startswith(GUARD_METADATA_REFERENCE_PREFIXES):
            guard_metadata_only.append(reference)
        else:
            blocking.append(reference)
    return blocking, generated_report_only, guard_metadata_only


def load_archive_candidates(cleanup_report: dict[str, Any]) -> list[dict[str, Any]]:
    items = cleanup_report.get("samples_by_action", {}).get("archive_candidate", [])
    return [item for item in items if isinstance(item, dict)]


def effective_roots(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_candidates = sorted(candidates, key=lambda item: (norm_path(str(item.get("path") or "")).count("/"), norm_path(str(item.get("path") or ""))))
    roots: list[dict[str, Any]] = []
    for item in sorted_candidates:
        path = norm_path(str(item.get("path") or ""))
        if not path:
            continue
        if any(is_same_or_child(path, norm_path(str(root.get("path") or ""))) for root in roots):
            continue
        roots.append({**item, "path": path})
    return roots


def path_inventory(path: str) -> dict[str, Any]:
    absolute = (ROOT / path).resolve()
    try:
        inside_workspace = absolute == ROOT.resolve() or ROOT.resolve() in absolute.parents
    except RuntimeError:
        inside_workspace = False
    exists = absolute.exists()
    is_dir = absolute.is_dir()
    file_count = 0
    total_bytes = 0
    if exists and is_dir:
        for child in absolute.rglob("*"):
            if child.is_file():
                file_count += 1
                total_bytes += child.stat().st_size
    elif exists and absolute.is_file():
        file_count = 1
        total_bytes = absolute.stat().st_size
    return {
        "exists": exists,
        "kind_observed": "directory" if is_dir else "file" if exists else "missing",
        "inside_workspace": inside_workspace,
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


def audit_candidate(item: dict[str, Any], protected_paths: list[str], scan_roots: list[str], max_hits: int) -> dict[str, Any]:
    path = norm_path(str(item.get("path") or ""))
    inventory = path_inventory(path)
    references = find_references(path, scan_roots, max_hits)
    blocking_references, generated_report_references, guard_metadata_references = split_references(references)
    protected_overlaps = [protected for protected in protected_paths if is_same_or_child(protected, path) or is_same_or_child(path, protected)]
    blockers: list[str] = []
    if not inventory["exists"]:
        blockers.append("path_missing")
    if not inventory["inside_workspace"]:
        blockers.append("path_outside_workspace")
    if blocking_references:
        blockers.append("referenced_by_repo")
    if protected_overlaps:
        blockers.append("protected_path_overlap")
    if item.get("risk") != "low":
        blockers.append("risk_not_low")
    if item.get("proposed_action") != "archive_candidate":
        blockers.append("not_archive_candidate")
    return {
        "path": path,
        "kind": item.get("kind") or inventory["kind_observed"],
        "source_category": item.get("category") or "",
        "source_reason": item.get("reason") or "",
        "inventory": inventory,
        "reference_count_capped": len(references),
        "reference_scan_hit_limit": max_hits,
        "reference_scan_truncated": len(references) >= max_hits,
        "reference_samples": references,
        "blocking_reference_count_capped": len(blocking_references),
        "blocking_reference_samples": blocking_references[:max_hits],
        "generated_report_reference_count_capped": len(generated_report_references),
        "generated_report_reference_samples": generated_report_references[:max_hits],
        "guard_metadata_reference_count_capped": len(guard_metadata_references),
        "guard_metadata_reference_samples": guard_metadata_references[:max_hits],
        "protected_overlap_count": len(protected_overlaps),
        "protected_overlap_samples": protected_overlaps[:max_hits],
        "blockers": blockers,
        "decision": "archive_allowed" if not blockers else "blocked_needs_review",
        "archive_target": norm_path(f"{DEFAULT_ARCHIVE_ROOT}/{path}"),
    }


def protected_paths(classification: dict[str, Any]) -> list[str]:
    records = classification.get("records", [])
    return sorted(
        norm_path(str(item.get("path") or ""))
        for item in records
        if isinstance(item, dict) and item.get("category") == "protected_final_chain_surface" and item.get("path")
    )


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    cleanup_report = read_json(Path(args.cleanup_report))
    classification = read_json(Path(args.classification_report))
    safety_path = Path(args.safety_report)
    # 首次 clean checkout 尚无 safety 报告；此时只生成未武装审计，绝不授权归档。
    safety = read_json(safety_path) if safety_path.is_file() else {}
    candidates = load_archive_candidates(cleanup_report)
    roots = effective_roots(candidates)
    protected = protected_paths(classification)
    audited = [audit_candidate(item, protected, args.scan_roots, args.max_reference_hits) for item in roots]
    execution_path = Path(
        getattr(args, "execution_report", "docs/reports/precleanup_archive_execution_20260804.json")
    )
    execution = read_json(execution_path) if execution_path.is_file() else {}
    guard_paths = {
        norm_path(str(move.get("source") or ""))
        for move in execution.get("moves", [])
        if isinstance(move, dict) and move.get("source")
    }
    guard_paths.add("outputs/pipeline_baseline_snapshot")
    audited_paths = {item["path"] for item in audited}
    # 历史归档源与仍在使用的 baseline 必须持续接受 fail-closed 复核。
    for path in sorted(guard_paths - audited_paths):
        audited.append(
            audit_candidate(
                {
                    "path": path,
                    "kind": "directory" if path == "outputs/pipeline_baseline_snapshot" else "file",
                    "category": "historical_or_probe_surface",
                    "reason": "post-archive reproducibility guard",
                },
                protected,
                args.scan_roots,
                args.max_reference_hits,
            )
        )
    allowed = [item for item in audited if item["decision"] == "archive_allowed"]
    blocked = [item for item in audited if item["decision"] != "archive_allowed"]
    report = {
        "schema_version": "precleanup_deep_audit.v0.1",
        "report_phase": "pre_execution_authorization_snapshot",
        "post_execution_state_report": False,
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "source_reports": {
            "cleanup_report": norm_path(args.cleanup_report),
            "classification_report": norm_path(args.classification_report),
            "safety_report": norm_path(args.safety_report),
            "execution_report": norm_path(execution_path),
        },
        "precleanup_safety_ok": bool(safety.get("ok") is True),
        "candidate_summary": {
            "archive_candidate_source_count": len(candidates),
            "effective_archive_root_count": len(roots),
            "archive_allowed_count": len(allowed),
            "blocked_needs_review_count": len(blocked),
            "review_candidates_not_in_scope": int(cleanup_report.get("counts_by_risk", {}).get("review", 0) or 0),
        },
        "rules": [
            "only archive_candidate + low risk entries may be considered",
            "parent directories absorb child candidates; duplicate child moves are suppressed",
            "any repository reference blocks archive",
            "any protected final-chain overlap blocks archive",
            "missing paths or paths outside workspace block archive",
            "blocked_needs_review entries are not moved, archived, or deleted",
            "allowed entries are revalidated by the archive executor before any filesystem move",
            "reference counts ending in _capped are sample counts, not total repository counts",
            "generated reports and cleanup guard metadata are classified separately from blocking repository references",
        ],
        "archive_root": DEFAULT_ARCHIVE_ROOT,
        "allowed_archive_roots": allowed,
        "blocked_roots": blocked,
        "ok_to_execute_allowed_archive_roots": bool(safety.get("ok") is True and allowed and not any(item["blockers"] for item in allowed)),
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["candidate_summary"]
    lines = [
        "# Precleanup Deep Audit 2026-08-04",
        "",
        "This is a pre-execution authorization snapshot, not a post-archive state report.",
        "It authorizes only `archive_allowed` roots, and the archive executor must revalidate them before moving files.",
        "All paths are relative git paths; no local absolute path is part of the reproducible input contract.",
        "",
        "## Summary",
        "",
        f"- precleanup safety ok: `{report['precleanup_safety_ok']}`",
        f"- archive candidate source count: `{summary['archive_candidate_source_count']}`",
        f"- effective archive roots: `{summary['effective_archive_root_count']}`",
        f"- archive allowed: `{summary['archive_allowed_count']}`",
        f"- blocked needs review: `{summary['blocked_needs_review_count']}`",
        f"- review candidates not in scope: `{summary['review_candidates_not_in_scope']}`",
        "",
        "## Allowed Archive Roots",
        "",
    ]
    if report["allowed_archive_roots"]:
        for item in report["allowed_archive_roots"]:
            inv = item["inventory"]
            lines.append(
                f"- `{item['path']}` -> `{item['archive_target']}` "
                f"(files={inv['file_count']}, bytes={inv['total_bytes']})"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Blocked Roots", ""])
    if report["blocked_roots"]:
        for item in report["blocked_roots"]:
            lines.append(f"- `{item['path']}`: blockers={item['blockers']}")
            for ref in item["reference_samples"][:5]:
                lines.append(f"  - ref: `{ref}`")
            if item["generated_report_reference_count_capped"] and not item["blocking_reference_count_capped"]:
                lines.append(f"  - generated report refs ignored: `{item['generated_report_reference_count_capped']}`")
            if item["guard_metadata_reference_count_capped"] and not item["blocking_reference_count_capped"]:
                lines.append(f"  - guard metadata refs ignored: `{item['guard_metadata_reference_count_capped']}`")
    else:
        lines.append("- None")
    lines.extend(["", "## Rules", ""])
    for rule in report["rules"]:
        lines.append(f"- {rule}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deep pre-cleanup audit with executable archive scope.")
    parser.add_argument("--cleanup-report", default="docs/reports/cleanup_candidates_cleanroom_20260731.json")
    parser.add_argument("--classification-report", default="docs/reports/final_chain_surface_classification_cleanroom_20260731.json")
    parser.add_argument("--safety-report", default="docs/reports/precleanup_safety_gate_20260804.json")
    parser.add_argument("--execution-report", default=str(DEFAULT_EXECUTION_REPORT.relative_to(ROOT)))
    parser.add_argument("--scan-roots", nargs="*", default=DEFAULT_SCAN_ROOTS)
    parser.add_argument("--max-reference-hits", type=int, default=20)
    parser.add_argument("--output-json", default=str(DEFAULT_REPORT_JSON.relative_to(ROOT)))
    parser.add_argument("--output-md", default=str(DEFAULT_REPORT_MD.relative_to(ROOT)))
    args = parser.parse_args()
    report = build_report(args)
    write_json(ROOT / args.output_json, report)
    write_text(ROOT / args.output_md, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 退出码表示审计是否成功生成；实际归档权限始终由报告内的 fail-closed 字段控制。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
