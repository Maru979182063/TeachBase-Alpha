from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

DEFAULT_SOURCE_ROOT = Path("D:/Projects") / "\u6559\u7814\u57fa\u5efa"
SOURCE_LABEL = "old_local_d_projects_jiaoyan"
REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_rebuild_source_import_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_rebuild_source_import_20260804.md"

SOURCE_FILES = (
    "tools/english_text_first_graph_first_manifest_check.py",
    "docs/english_text_first_graph_first_environment.md",
    "tools/english_text_first_full_chain_runner_v01.py",
    "tools/english_text_first_controlled_node1_vlm_transcriber.py",
    "tools/english_text_first_controlled_node1b_attribute_tagger.py",
    "tools/english_text_first_sliding_window_composer_v01.py",
    "tools/english_text_first_group_deduper_v01.py",
    "tools/english_text_first_group_normalizer_v01.py",
    "tools/english_text_first_group_relation_resolver_v01.py",
    "tools/english_text_first_group_ownership_reconciler_v01.py",
    "tools/english_text_first_source_backed_draft_builder_v01.py",
    "tools/english_text_first_node4b_field_role_resolver_v01.py",
    "tools/english_text_first_question_packet_builder_v01.py",
    "tools/english_text_first_candidate_continuation_repair_v01.py",
    "tools/english_text_first_question_packet_refiner_v01.py",
    "tools/english_text_first_runtime_projection_planner_v01.py",
    "tools/english_text_first_display_projection_planner_v01.py",
    "tools/english_text_first_question_render_normalizer_v01.py",
    "tools/english_text_first_render_verifier_repair_v01.py",
    "tools/english_text_first_render_gate_point_repair_v01.py",
    "tools/english_text_first_question_candidate_auditor_v01.py",
    "tools/english_text_first_review_pack_renderer_v01.py",
    "config/english_text_first_v02.yaml",
)

FORBIDDEN_FRAGMENTS = ("backup", ".bak", "probe", "outputs/", "active_manifest")
ALLOWED_PREFIXES = ("tools/", "config/", "docs/")


def build_report(source_root: Path, *, dry_run: bool = False, overwrite: bool = False) -> dict[str, Any]:
    records = []
    for relative_path in dict.fromkeys(SOURCE_FILES):
        records.append(_process_file(source_root, relative_path, dry_run=dry_run, overwrite=overwrite))
    checks = [
        {
            "name": "source_root_present",
            "ok": source_root.is_dir(),
            "value": {"source_label": SOURCE_LABEL, "present": source_root.is_dir()},
        },
        {
            "name": "all_paths_are_allowlisted",
            "ok": all(record["allowlisted"] for record in records),
            "value": [record["relative_path"] for record in records if not record["allowlisted"]],
        },
        {
            "name": "all_source_files_present",
            "ok": all(record["source_exists"] for record in records),
            "value": [record["relative_path"] for record in records if not record["source_exists"]],
        },
        {
            "name": "no_target_conflicts",
            "ok": all(record["target_action"] not in {"conflict"} for record in records),
            "value": [record["relative_path"] for record in records if record["target_action"] == "conflict"],
        },
        {
            "name": "all_written_files_match_source",
            "ok": dry_run or all(record["target_sha256"] == record["source_sha256"] for record in records),
            "value": "dry_run" if dry_run else [record["relative_path"] for record in records if record["target_sha256"] != record["source_sha256"]],
        },
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        "schema_version": "pdf_english_rebuild_source_import.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "source_label": SOURCE_LABEL,
        "source_root_recording": "label_only",
        "dry_run": dry_run,
        "overwrite": overwrite,
        "status": "pass" if not failed else "fail",
        "imported_file_count": sum(1 for record in records if record["target_action"] in {"copied", "already_present_same_hash"}),
        "records": records,
        "checks": checks,
        "unsafe_actions": [
            "do_not_import_outputs_or_smoke_artifacts_as_source",
            "do_not_import_active_manifest_without_fresh_rebuild_validation",
            "do_not_import_backup_probe_or_bak_files",
        ],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _process_file(source_root: Path, relative_path: str, *, dry_run: bool, overwrite: bool) -> dict[str, Any]:
    allowlisted = _allowlisted(relative_path)
    source = source_root / relative_path
    target = ROOT / relative_path
    source_exists = source.is_file()
    target_exists_before = target.is_file()
    source_sha = _file_sha256(source) if source_exists else ""
    before_sha = _file_sha256(target) if target_exists_before else ""
    action = "missing_source"
    if allowlisted and source_exists:
        if target_exists_before and before_sha == source_sha:
            action = "already_present_same_hash"
        elif target_exists_before and not overwrite:
            action = "conflict"
        elif dry_run:
            action = "would_copy"
        else:
            _atomic_copy(source, target)
            action = "copied"
    target_exists_after = target.is_file()
    target_sha = _file_sha256(target) if target_exists_after else ""
    return {
        "relative_path": relative_path,
        "allowlisted": allowlisted,
        "source_exists": source_exists,
        "source_sha256": source_sha,
        "target_exists_before": target_exists_before,
        "target_action": action,
        "target_exists_after": target_exists_after,
        "target_sha256": target_sha,
    }


def _allowlisted(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    return normalized.startswith(ALLOWED_PREFIXES) and not any(fragment in normalized for fragment in FORBIDDEN_FRAGMENTS)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as src, temp.open("xb") as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(chunk)
        os.replace(temp, target)
    except Exception:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Rebuild Source Import 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Dry run: `{str(report['dry_run']).lower()}`",
        f"Imported files: `{report['imported_file_count']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Records", ""])
    for record in report["records"]:
        lines.append(f"- `{record['target_action']}` `{record['relative_path']}`")
    lines.append("")
    lines.append("Source location is recorded by label only; no local absolute path is part of the reproducible input contract.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import surviving PDF English graph-first rebuild sources.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    report = build_report(Path(args.source_root), dry_run=args.dry_run, overwrite=args.overwrite)
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
