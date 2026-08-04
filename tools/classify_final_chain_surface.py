from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_FILE_ROOTS = ["tools", "config", "prompts", "schemas", "docs", "tests"]
DEFAULT_DIRECTORY_ROOTS = ["outputs"]
IGNORED_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
HISTORICAL_MARKERS = {
    "backup",
    "archive",
    "probe",
    "smoke",
    "headcheck",
    "chaincheck",
    "badcase",
    "demo",
    ".bak",
    "legacy",
    "deprecated",
}
FINALISH_MARKERS = {"final", "full", "graph_first", "active"}
CHAIN_PREFIX_HINTS = {
    "doc_math": ("docx_math", "docx_native", "docx_question", "math_formula", "katex_validate", "mathml_to_latex", "ruby_mtef"),
    "doc_english": ("english_docx",),
    "pdf_math": (
        "run_question_ingest",
        "model_image_need",
        "build_figure_candidate",
        "teacher_handout_visual",
        "prepare_option_visual",
        "assetize_question",
        "consolidate_visual",
        "reconcile_and_refine",
        "audit_question_asset",
    ),
    "pdf_english": ("english_text_first", "english_question_packet", "english_group_relation", "english_render"),
}


def load_json_yaml(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm_path(path: str | Path) -> str:
    value = str(path).replace("\\", "/").strip().strip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def is_same_or_child(path: str, root: str) -> bool:
    path_norm = norm_path(path)
    root_norm = norm_path(root)
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


def walk_files(target_root: Path, roots: list[str]) -> list[str]:
    files: list[str] = []
    for raw_root in roots:
        root = target_root / raw_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if any(part in IGNORED_DIR_NAMES for part in path.relative_to(target_root).parts):
                continue
            if path.is_file():
                files.append(norm_path(path.relative_to(target_root)))
    return sorted(set(files))


def walk_directories(target_root: Path, roots: list[str], max_depth: int) -> list[str]:
    dirs: list[str] = []
    for raw_root in roots:
        root = target_root / raw_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_dir():
                continue
            rel = path.relative_to(target_root)
            if any(part in IGNORED_DIR_NAMES for part in rel.parts):
                continue
            if len(rel.parts) <= max_depth + 1:
                dirs.append(norm_path(rel))
    return sorted(set(dirs))


def collect_registry_paths(registry: dict[str, Any], docx_math_inventory: Path | None) -> tuple[dict[str, set[str]], dict[str, str]]:
    protected: dict[str, set[str]] = defaultdict(set)
    do_not_use: dict[str, str] = {}
    for chain in registry.get("chains") or []:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("chain_id") or "")
        for field in [
            "canonical_entrypoint",
            "protected_segment_entrypoint",
        ]:
            value = chain.get(field)
            if isinstance(value, str) and value:
                protected[chain_id].add(norm_path(value))
        for field in [
            "canonical_config_paths",
            "supporting_entrypoints",
            "protected_paths",
            "declared_prior_smoke_artifacts",
        ]:
            for value in chain.get(field) or []:
                if isinstance(value, str) and value:
                    protected[chain_id].add(norm_path(value))
        retained = chain.get("strongest_retained_package")
        if isinstance(retained, dict) and isinstance(retained.get("path"), str):
            protected[chain_id].add(norm_path(retained["path"]))
        for value in chain.get("do_not_use_as_final") or []:
            if isinstance(value, str) and value:
                do_not_use[norm_path(value)] = chain_id

    if docx_math_inventory and docx_math_inventory.exists():
        inventory = load_json_yaml(docx_math_inventory)
        for item in inventory.get("files") or []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                protected["doc_math"].add(norm_path(item["path"]))
    return protected, do_not_use


def marker_hits(path: str, markers: set[str]) -> list[str]:
    lower = path.lower()
    return sorted(marker for marker in markers if marker in lower)


def chain_hint_for(path: str) -> str:
    lower_name = Path(path).name.lower()
    lower_path = path.lower()
    for chain_id, hints in CHAIN_PREFIX_HINTS.items():
        if any(lower_name.startswith(hint) or f"/{hint}" in lower_path for hint in hints):
            return chain_id
    return ""


def classify_path(path: str, kind: str, protected: dict[str, set[str]], do_not_use: dict[str, str]) -> dict[str, Any]:
    for chain_id, paths in protected.items():
        for protected_path in paths:
            if is_same_or_child(path, protected_path):
                return {
                    "path": path,
                    "kind": kind,
                    "category": "protected_final_chain_surface",
                    "chain_id": chain_id,
                    "reason": f"matches protected path {protected_path}",
                }
    for legacy_path, chain_id in do_not_use.items():
        if is_same_or_child(path, legacy_path):
            return {
                "path": path,
                "kind": kind,
                "category": "known_non_final_legacy",
                "chain_id": chain_id,
                "reason": f"listed as do_not_use_as_final for {chain_id}",
            }

    historical = marker_hits(path, HISTORICAL_MARKERS)
    if historical:
        return {
            "path": path,
            "kind": kind,
            "category": "historical_or_probe_surface",
            "chain_id": chain_hint_for(path),
            "reason": "name contains historical marker(s): " + ", ".join(historical),
        }

    chain_hint = chain_hint_for(path)
    finalish = marker_hits(path, FINALISH_MARKERS)
    if chain_hint:
        return {
            "path": path,
            "kind": kind,
            "category": "chain_adjacent_needs_review",
            "chain_id": chain_hint,
            "reason": "matches chain naming hints but is not protected by registry",
        }
    if finalish:
        return {
            "path": path,
            "kind": kind,
            "category": "finalish_name_needs_review",
            "chain_id": "",
            "reason": "name contains final-like marker(s): " + ", ".join(finalish),
        }
    if path.startswith("outputs/"):
        return {
            "path": path,
            "kind": kind,
            "category": "unregistered_output_surface",
            "chain_id": "",
            "reason": "output surface not protected by final-chain registry",
        }
    return {
        "path": path,
        "kind": kind,
        "category": "unclassified_non_chain_surface",
        "chain_id": "",
        "reason": "no protected, legacy, historical, or chain-adjacent signal",
    }


def summarize(records: list[dict[str, Any]], sample_limit: int) -> dict[str, Any]:
    by_category = Counter(record["category"] for record in records)
    by_chain = Counter(record["chain_id"] for record in records if record.get("chain_id"))
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        bucket = samples[record["category"]]
        if len(bucket) < sample_limit:
            bucket.append(record)
    return {
        "total_records": len(records),
        "counts_by_category": dict(sorted(by_category.items())),
        "counts_by_chain": dict(sorted(by_chain.items())),
        "samples_by_category": dict(sorted(samples.items())),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Final Chain Surface Classification",
        "",
        f"Target root label: `{report['target_root_label']}`",
        "",
        "This is a non-destructive classification report. It does not authorize deletion.",
        "",
        "## Summary",
        "",
        "| Category | Count |",
        "| --- | ---: |",
    ]
    for category, count in report["summary"]["counts_by_category"].items():
        lines.append(f"| `{category}` | {count} |")
    lines.extend(["", "## Chain Counts", "", "| Chain | Count |", "| --- | ---: |"])
    for chain_id, count in report["summary"]["counts_by_chain"].items():
        lines.append(f"| `{chain_id}` | {count} |")
    lines.extend(["", "## Samples", ""])
    for category, records in report["summary"]["samples_by_category"].items():
        lines.append(f"### `{category}`")
        lines.append("")
        for record in records:
            chain = f" `{record['chain_id']}`" if record.get("chain_id") else ""
            lines.append(f"- `{record['path']}` ({record['kind']}){chain}: {record['reason']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    target_root = Path(args.target_root).resolve()
    registry = load_json_yaml(Path(args.registry))
    docx_inventory = Path(args.docx_math_inventory) if args.docx_math_inventory else None
    protected, do_not_use = collect_registry_paths(registry, docx_inventory)

    file_roots = args.file_roots or DEFAULT_FILE_ROOTS
    directory_roots = args.directory_roots or DEFAULT_DIRECTORY_ROOTS
    files = walk_files(target_root, file_roots)
    dirs = walk_directories(target_root, directory_roots, args.directory_depth)
    records = [classify_path(path, "file", protected, do_not_use) for path in files]
    records.extend(classify_path(path, "directory", protected, do_not_use) for path in dirs)
    records.sort(key=lambda record: (record["category"], record["chain_id"], record["path"]))

    protected_counts = {chain_id: len(paths) for chain_id, paths in protected.items()}
    return {
        "schema_version": "final_chain_surface_classification.v0.1",
        "target_root_label": args.target_root_label,
        "target_root_observed": str(target_root) if getattr(args, "include_absolute_target_root", False) else "",
        "registry_path": str(Path(args.registry)),
        "file_roots": file_roots,
        "directory_roots": directory_roots,
        "directory_depth": args.directory_depth,
        "protected_path_count_by_chain": dict(sorted(protected_counts.items())),
        "do_not_use_path_count": len(do_not_use),
        "records": records,
        "summary": summarize(records, args.sample_limit),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify final-chain, legacy, and cleanup surface without deleting files.")
    parser.add_argument("--target-root", default=".")
    parser.add_argument("--target-root-label", default="workspace")
    parser.add_argument("--registry", default="config/final_chain_registry.yaml")
    parser.add_argument("--docx-math-inventory", default="")
    parser.add_argument("--file-roots", nargs="*", default=None)
    parser.add_argument("--directory-roots", nargs="*", default=None)
    parser.add_argument("--directory-depth", type=int, default=2)
    parser.add_argument("--sample-limit", type=int, default=25)
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
            "total_records": report["summary"]["total_records"],
            "counts_by_category": report["summary"]["counts_by_category"],
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
