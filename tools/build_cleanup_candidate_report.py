from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CANDIDATE_CATEGORIES = {
    "known_non_final_legacy",
    "historical_or_probe_surface",
    "finalish_name_needs_review",
    "unregistered_output_surface",
}
NEVER_DELETE_CATEGORIES = {
    "protected_final_chain_surface",
    "chain_adjacent_needs_review",
    "unclassified_non_chain_surface",
}
DEFAULT_SCAN_ROOTS = ["tools", "config", "prompts", "schemas", "docs", "tests", "package.json"]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm_path(path: str | Path) -> str:
    value = str(path).replace("\\", "/").strip().strip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def flatten_samples(classification: dict[str, Any]) -> list[dict[str, Any]]:
    records = classification.get("records")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict)]
    records: list[dict[str, Any]] = []
    samples = classification.get("summary", {}).get("samples_by_category", {})
    if isinstance(samples, dict):
        for items in samples.values():
            if isinstance(items, list):
                records.extend(item for item in items if isinstance(item, dict))
    return records


def protected_records(classification: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in flatten_samples(classification)
        if item.get("category") == "protected_final_chain_surface" and isinstance(item.get("path"), str)
    ]


def is_same_or_child(path: str, root: str) -> bool:
    path_norm = norm_path(path)
    root_norm = norm_path(root)
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


def reference_patterns(path: str) -> list[str]:
    normalized = norm_path(path)
    name = Path(normalized).name
    stem = Path(normalized).stem
    patterns = [normalized, normalized.replace("/", "\\"), name]
    if stem and stem != name:
        patterns.append(stem)
    return sorted(set(pattern for pattern in patterns if pattern))


def run_rg(target_root: Path, pattern: str, scan_roots: list[str], max_hits: int) -> list[str]:
    cmd = ["rg", "--fixed-strings", "--no-heading", "--line-number", "--color", "never", pattern, *scan_roots]
    try:
        proc = subprocess.run(
            cmd,
            cwd=target_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode not in {0, 1}:
        return []
    hits: list[str] = []
    for line in proc.stdout.splitlines():
        if line not in hits:
            hits.append(line)
        if len(hits) >= max_hits:
            break
    return hits


def find_references(target_root: Path, path: str, scan_roots: list[str], max_hits: int) -> list[str]:
    hits: list[str] = []
    for pattern in reference_patterns(path):
        for hit in run_rg(target_root, pattern, scan_roots, max_hits):
            normalized_hit = hit.replace("\\", "/")
            # Ignore self references when the scanned file is exactly the candidate.
            if normalized_hit.startswith(norm_path(path) + ":"):
                continue
            if hit not in hits:
                hits.append(hit)
            if len(hits) >= max_hits:
                return hits
    return hits


def proposed_action(record: dict[str, Any], references: list[str]) -> str:
    category = record["category"]
    kind = record.get("kind")
    path = str(record.get("path") or "")
    if category in NEVER_DELETE_CATEGORIES:
        return "do_not_touch"
    if references:
        return "needs_review_referenced"
    if kind == "file" and path.split("/", 1)[0] in {"tools", "tests", "config", "prompts", "schemas"}:
        return "needs_review_historical_code_or_test"
    if category == "known_non_final_legacy":
        return "archive_then_remove_entrypoint_after_compat_check"
    if category == "historical_or_probe_surface":
        return "archive_candidate"
    if category == "unregistered_output_surface" and kind == "directory":
        return "archive_candidate"
    if category == "finalish_name_needs_review":
        return "needs_review_finalish_name"
    return "needs_review"


def risk_level(action: str) -> str:
    if action == "do_not_touch":
        return "blocked"
    if action.startswith("archive_candidate"):
        return "low"
    if action.startswith("archive_then"):
        return "medium"
    return "review"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    classification = load_json(Path(args.classification))
    target_root = Path(args.target_root).resolve()
    scan_roots = args.scan_roots or DEFAULT_SCAN_ROOTS
    protected = protected_records(classification)
    candidates: list[dict[str, Any]] = []
    for record in flatten_samples(classification):
        category = record.get("category")
        if category not in CANDIDATE_CATEGORIES:
            continue
        path = str(record.get("path") or "")
        protected_children = [
            item["path"]
            for item in protected
            if path and item.get("path") and is_same_or_child(str(item["path"]), path) and norm_path(item["path"]) != norm_path(path)
        ]
        references = find_references(target_root, path, scan_roots, args.max_reference_hits) if args.scan_references else []
        action = "needs_review_contains_protected_surface" if protected_children else proposed_action(record, references)
        candidates.append({
            "path": path,
            "kind": record.get("kind"),
            "category": category,
            "chain_id": record.get("chain_id") or "",
            "reason": record.get("reason") or "",
            "proposed_action": action,
            "risk": risk_level(action),
            "reference_count_capped": len(references),
            "reference_samples": references,
            "protected_child_count_capped": min(len(protected_children), args.max_reference_hits),
            "protected_child_samples": protected_children[: args.max_reference_hits],
        })

    by_action = Counter(item["proposed_action"] for item in candidates)
    by_category = Counter(item["category"] for item in candidates)
    by_risk = Counter(item["risk"] for item in candidates)
    samples_by_action: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        bucket = samples_by_action[item["proposed_action"]]
        if len(bucket) < args.sample_limit:
            bucket.append(item)

    return {
        "schema_version": "cleanup_candidate_report.v0.1",
        "target_root_label": classification.get("target_root_label", "unknown"),
        "target_root_observed": str(target_root) if args.include_absolute_target_root else "",
        "classification_path": str(Path(args.classification)),
        "source_note": "Non-destructive candidate report. This does not authorize deletion.",
        "scan_references": bool(args.scan_references),
        "scan_roots": scan_roots,
        "candidate_source_categories": sorted(CANDIDATE_CATEGORIES),
        "candidate_count": len(candidates),
        "counts_by_action": dict(sorted(by_action.items())),
        "counts_by_category": dict(sorted(by_category.items())),
        "counts_by_risk": dict(sorted(by_risk.items())),
        "samples_by_action": dict(sorted(samples_by_action.items())),
    }


def write_markdown(report: dict[str, Any], output: Path) -> None:
    lines = [
        "# Cleanup Candidate Report",
        "",
        f"Target root label: `{report['target_root_label']}`",
        "",
        report["source_note"],
        "",
        "## Action Counts",
        "",
        "| Action | Count |",
        "| --- | ---: |",
    ]
    for action, count in report["counts_by_action"].items():
        lines.append(f"| `{action}` | {count} |")
    lines.extend(["", "## Risk Counts", "", "| Risk | Count |", "| --- | ---: |"])
    for risk, count in report["counts_by_risk"].items():
        lines.append(f"| `{risk}` | {count} |")
    lines.extend(["", "## Samples", ""])
    for action, items in report["samples_by_action"].items():
        lines.append(f"### `{action}`")
        lines.append("")
        for item in items:
            refs = f", refs={item['reference_count_capped']}" if item["reference_count_capped"] else ""
            chain = f", chain={item['chain_id']}" if item.get("chain_id") else ""
            lines.append(f"- `{item['path']}` ({item['category']}{chain}{refs}): {item['reason']}")
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a non-destructive cleanup candidate report from classification output.")
    parser.add_argument("--classification", required=True)
    parser.add_argument("--target-root", default=".")
    parser.add_argument("--scan-roots", nargs="*", default=None)
    parser.add_argument("--scan-references", action="store_true")
    parser.add_argument("--max-reference-hits", type=int, default=5)
    parser.add_argument("--sample-limit", type=int, default=30)
    parser.add_argument("--include-absolute-target-root", action="store_true")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    report = build_report(args)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        write_markdown(report, Path(args.output_md))
    if not args.output_json and not args.output_md:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({
            "schema_version": report["schema_version"],
            "target_root_label": report["target_root_label"],
            "candidate_count": report["candidate_count"],
            "counts_by_action": report["counts_by_action"],
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
