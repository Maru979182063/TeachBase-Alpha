from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_manifest_recovery_audit_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_manifest_recovery_audit_20260804.md"

ARTIFACTS = (
    {
        "key": "active_manifest",
        "relative_path": "config/english_text_first_graph_first/active_manifest.json",
        "required_for_import": True,
    },
    {
        "key": "manifest_checker",
        "relative_path": "tools/english_text_first_graph_first_manifest_check.py",
        "required_for_import": True,
    },
    {
        "key": "prior_smoke_zip",
        "relative_path": "outputs/english_text_first_graph_first/final_chain_smoke_20260728.zip",
        "required_for_import": True,
    },
    {
        "key": "prior_smoke_dir",
        "relative_path": "outputs/english_text_first_graph_first/final_chain_smoke_20260728",
        "required_for_import": True,
    },
)


@dataclass(frozen=True)
class SourceRoot:
    label: str
    path: Path


def default_source_roots() -> tuple[SourceRoot, ...]:
    return (
        SourceRoot("cleanroom_current", ROOT),
        SourceRoot("old_local_d_projects_jiaoyan", Path("D:/Projects/教研基建")),
        SourceRoot("handoff_package_user_documents", Path("C:/Users/1/Documents/english_text_first_graph_first_handoff")),
    )


def build_report(source_roots: tuple[SourceRoot, ...] | None = None) -> dict[str, Any]:
    source_roots = source_roots or default_source_roots()
    source_candidates = [_source_candidate(source_root) for source_root in source_roots]
    importable_sources = [
        item["source_label"]
        for item in source_candidates
        if all(artifact["exists"] for artifact in item["required_artifacts"])
    ]
    recovery_status = (
        "candidate_found_needs_manifest_gate"
        if importable_sources
        else "blocked_missing_manifest_and_smoke_artifacts"
    )
    return {
        "schema_version": "pdf_english_manifest_recovery_audit.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "canonical_entrypoint": "config/english_text_first_graph_first/active_manifest.json",
        "search_method": "targeted_known_source_roots_by_label",
        "searched_location_labels": [source_root.label for source_root in source_roots],
        "searched_artifacts": [item["relative_path"] for item in ARTIFACTS],
        "source_candidates": source_candidates,
        "importable_source_labels": importable_sources,
        "source_audit_status": "importable_source_found" if importable_sources else "no_importable_source_found",
        "recovery_status": recovery_status,
        "safe_next_actions": _safe_next_actions(recovery_status),
        "unsafe_actions": [
            "do_not_create_synthetic_active_manifest",
            "do_not_select_latest_directory_by_timestamp",
            "do_not_mark_pdf_english_adapter_ready_without_manifest_check",
        ],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _source_candidate(source_root: SourceRoot) -> dict[str, Any]:
    artifacts = [_artifact_state(source_root.path, item) for item in ARTIFACTS]
    required = [item for item in artifacts if item["required_for_import"]]
    return {
        "source_label": source_root.label,
        "source_root_present": source_root.path.exists(),
        "required_artifacts_present": sum(1 for item in required if item["exists"]),
        "required_artifacts_total": len(required),
        "required_artifacts": required,
    }


def _artifact_state(source_root: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    relative_path = artifact["relative_path"]
    path = source_root / relative_path
    state = {
        "key": artifact["key"],
        "relative_path": relative_path,
        "required_for_import": artifact["required_for_import"],
        "exists": path.exists(),
        "kind": "directory" if path.is_dir() else "file" if path.is_file() else "missing",
    }
    if path.is_file():
        state["size_bytes"] = path.stat().st_size
        state["sha256"] = _file_sha256(path)
    if path.is_dir():
        state["direct_child_count"] = len(list(path.iterdir()))
    if path.is_file() and path.suffix.lower() == ".zip":
        state["zip_testzip"] = _zip_testzip(path)
    if artifact["key"] == "active_manifest" and path.is_file():
        state["manifest_checks"] = _manifest_checks(path)
    return state


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_testzip(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip()
    except zipfile.BadZipFile:
        return "bad_zip_file"


def _manifest_checks(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"json_object": False, "error": "manifest_invalid_json"}
    if not isinstance(payload, dict):
        return {"json_object": False, "error": "manifest_not_object"}
    run_maps = [payload.get(key) for key in ("runs", "branch_runs", "active_runs", "run_ids")]
    return {
        "json_object": True,
        "pipeline_name_matches": payload.get("pipeline_name") == "english_text_first_graph_first",
        "allow_only_manifest_runs_enabled": payload.get("allow_only_manifest_runs") is True,
        "timestamp_latest_selection_forbidden": payload.get("forbid_timestamp_latest_selection") is True,
        "four_branch_runs_declared": any(
            isinstance(run_map, dict)
            and all(run_map.get(key) for key in ("reading", "grammar", "writing", "cloze"))
            for run_map in run_maps
        ),
    }


def _safe_next_actions(recovery_status: str) -> list[str]:
    if recovery_status == "candidate_found_needs_manifest_gate":
        return [
            "copy_candidate_artifacts_with_preserved_relative_paths",
            "run_python_tools_english_text_first_graph_first_manifest_check",
            "run_small_smoke_before_claiming_adapter_ready",
        ]
    return [
        "restore_active_manifest_from_original_machine_or_backup",
        "restore_final_chain_smoke_20260728_artifacts_if_available",
        "otherwise_rerun_manifest_check_and_small_smoke_before_claiming_ready",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Manifest Recovery Audit 2026-08-04",
        "",
        f"Status: `{report['recovery_status']}`",
        f"Source audit status: `{report['source_audit_status']}`",
        "",
        "## Sources",
        "",
    ]
    for source in report["source_candidates"]:
        lines.append(
            f"- `{source['source_label']}`: "
            f"`{source['required_artifacts_present']}/{source['required_artifacts_total']}` required artifacts"
        )
    lines.extend(["", "## Safe Next Actions", ""])
    for action in report["safe_next_actions"]:
        lines.append(f"- `{action}`")
    lines.extend(["", "## Unsafe Actions", ""])
    for action in report["unsafe_actions"]:
        lines.append(f"- `{action}`")
    lines.append("")
    lines.append("All paths are relative git paths or location labels; no local absolute path is part of the reproducible input contract.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
