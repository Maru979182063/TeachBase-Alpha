from __future__ import annotations

import argparse
import json
import sys
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_recovery_intake_validation_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_recovery_intake_validation_20260804.md"

PIPELINE_NAME = "english_text_first_graph_first"
REQUIRED_RUN_KEYS = ("reading", "grammar", "writing", "cloze")

REQUIRED_ARTIFACTS = (
    {
        "key": "active_manifest",
        "relative_path": "config/english_text_first_graph_first/active_manifest.json",
        "kind": "file",
    },
    {
        "key": "manifest_checker",
        "relative_path": "tools/english_text_first_graph_first_manifest_check.py",
        "kind": "file",
    },
    {
        "key": "smoke_zip",
        "relative_path": "outputs/english_text_first_graph_first/final_chain_smoke_20260728.zip",
        "kind": "file",
    },
    {
        "key": "smoke_dir",
        "relative_path": "outputs/english_text_first_graph_first/final_chain_smoke_20260728",
        "kind": "directory",
    },
)


def build_report(candidate_root: Path | None = None) -> dict[str, Any]:
    candidate_root = candidate_root or ROOT
    root_state = _candidate_root_state(candidate_root)
    manifest_path = candidate_root / "config" / "english_text_first_graph_first" / "active_manifest.json"
    manifest_payload, manifest_error = _load_manifest(manifest_path)
    required_artifacts = _required_artifacts(manifest_payload)
    artifact_states = [_artifact_state(candidate_root, artifact) for artifact in required_artifacts]
    checks = _build_checks(root_state, artifact_states, manifest_payload, manifest_error)
    failed_required = [check["name"] for check in checks if check["required"] is True and check["ok"] is not True]
    status = "candidate_ready_for_quarantine_import" if not failed_required else "blocked_missing_or_invalid_recovery_candidate"
    return {
        "schema_version": "pdf_english_recovery_intake_validation.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "status": status,
        "candidate_root_contract": {
            "path_recording": "label_or_workspace_relative_only",
            "candidate_label": root_state["candidate_label"],
            "scope": root_state["scope"],
            "exists": root_state["exists"],
            "kind": root_state["kind"],
        },
        "required_relative_artifacts": [artifact["relative_path"] for artifact in required_artifacts],
        "artifact_states": artifact_states,
        "checks": checks,
        "required_check_failures": failed_required,
        "safe_next_actions": _safe_next_actions(status),
        "unsafe_actions": [
            "do_not_copy_candidate_into_config_until_this_report_is_ready",
            "do_not_create_synthetic_active_manifest",
            "do_not_select_latest_directory_by_timestamp",
            "do_not_mark_pdf_english_adapter_ready_without_manifest_check_and_smoke",
        ],
        "execution_contract": _no_side_effect_contract(),
    }


def _build_checks(
    root_state: dict[str, Any],
    artifact_states: list[dict[str, Any]],
    manifest_payload: dict[str, Any] | None,
    manifest_error: str,
) -> list[dict[str, Any]]:
    artifacts = {item["key"]: item for item in artifact_states}
    smoke_zip = artifacts["smoke_zip"]
    smoke_dir = artifacts["smoke_dir"]
    return [
        _check("candidate_root_exists", root_state["exists"] is True and root_state["kind"] == "directory"),
        _check("active_manifest_present", artifacts["active_manifest"]["exists"] is True),
        _check("active_manifest_json_object", isinstance(manifest_payload, dict), error=manifest_error),
        _check(
            "pipeline_name_matches",
            isinstance(manifest_payload, dict) and manifest_payload.get("pipeline_name") == PIPELINE_NAME,
            expected=PIPELINE_NAME,
            actual=manifest_payload.get("pipeline_name") if isinstance(manifest_payload, dict) else None,
        ),
        _check(
            "allow_only_manifest_runs_enabled",
            isinstance(manifest_payload, dict) and manifest_payload.get("allow_only_manifest_runs") is True,
        ),
        _check(
            "timestamp_latest_selection_forbidden",
            isinstance(manifest_payload, dict) and manifest_payload.get("forbid_timestamp_latest_selection") is True,
        ),
        _check(
            "four_branch_runs_declared",
            _has_four_branch_runs(manifest_payload),
            required_run_keys=list(REQUIRED_RUN_KEYS),
        ),
        _check("manifest_checker_present", artifacts["manifest_checker"]["exists"] is True),
        _check("smoke_zip_present", smoke_zip["exists"] is True),
        _check("smoke_zip_valid", smoke_zip.get("zip_testzip") is None and smoke_zip.get("zip_error") in {"", None}),
        _check("smoke_dir_present", smoke_dir["exists"] is True and smoke_dir["kind"] == "directory"),
        _check("smoke_dir_nonempty", int(smoke_dir.get("direct_child_count") or 0) > 0),
    ]


def _required_artifacts(manifest_payload: dict[str, Any] | None) -> tuple[dict[str, str], ...]:
    artifacts = [dict(REQUIRED_ARTIFACTS[0]), dict(REQUIRED_ARTIFACTS[1])]
    smoke_zip = "outputs/english_text_first_graph_first/final_chain_smoke_20260728.zip"
    smoke_dir = "outputs/english_text_first_graph_first/final_chain_smoke_20260728"
    if isinstance(manifest_payload, dict):
        smoke = manifest_payload.get("fresh_smoke_artifacts")
        if isinstance(smoke, dict):
            if isinstance(smoke.get("smoke_zip"), str):
                smoke_zip = str(smoke["smoke_zip"])
            if isinstance(smoke.get("smoke_dir"), str):
                smoke_dir = str(smoke["smoke_dir"])
    artifacts.extend(
        [
            {"key": "smoke_zip", "relative_path": smoke_zip, "kind": "file"},
            {"key": "smoke_dir", "relative_path": smoke_dir, "kind": "directory"},
        ]
    )
    return tuple(artifacts)


def _candidate_root_state(candidate_root: Path) -> dict[str, Any]:
    return {
        "candidate_label": _candidate_label(candidate_root),
        "scope": _candidate_scope(candidate_root),
        "exists": candidate_root.exists(),
        "kind": "directory" if candidate_root.is_dir() else "file" if candidate_root.is_file() else "missing",
    }


def _candidate_label(candidate_root: Path) -> str:
    try:
        resolved = candidate_root.resolve()
        root = ROOT.resolve()
        if resolved == root:
            return "current_cleanroom_workspace"
        if root in resolved.parents:
            return str(resolved.relative_to(root)).replace("\\", "/")
    except OSError:
        pass
    return "provided_candidate_root"


def _candidate_scope(candidate_root: Path) -> str:
    try:
        resolved = candidate_root.resolve()
        root = ROOT.resolve()
        if resolved == root or root in resolved.parents:
            return "inside_workspace"
    except OSError:
        pass
    return "external_candidate_redacted"


def _artifact_state(candidate_root: Path, artifact: dict[str, str]) -> dict[str, Any]:
    path = candidate_root / artifact["relative_path"]
    state: dict[str, Any] = {
        "key": artifact["key"],
        "relative_path": artifact["relative_path"],
        "expected_kind": artifact["kind"],
        "exists": path.exists(),
        "kind": "directory" if path.is_dir() else "file" if path.is_file() else "missing",
    }
    if path.is_file():
        state["size_bytes"] = path.stat().st_size
        state["sha256"] = _file_sha256(path)
    if path.is_dir():
        state["direct_child_count"] = len(list(path.iterdir()))
    if artifact["key"] == "smoke_zip":
        state.update(_zip_state(path))
    return state


def _zip_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"zip_error": "zip_missing", "zip_testzip": ""}
    try:
        with zipfile.ZipFile(path) as archive:
            return {"zip_error": "", "zip_testzip": archive.testzip(), "zip_entry_count": len(archive.namelist())}
    except zipfile.BadZipFile:
        return {"zip_error": "bad_zip_file", "zip_testzip": "bad_zip_file", "zip_entry_count": 0}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, "manifest_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None, "manifest_invalid_json"
    if not isinstance(payload, dict):
        return None, "manifest_not_object"
    return payload, ""


def _has_four_branch_runs(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("runs", "branch_runs", "active_runs", "run_ids"):
        run_map = payload.get(key)
        if isinstance(run_map, dict) and all(run_map.get(run_key) for run_key in REQUIRED_RUN_KEYS):
            return True
    return False


def _check(name: str, ok: bool, **extra: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, "required": True, **extra}


def _safe_next_actions(status: str) -> list[str]:
    if status == "candidate_ready_for_quarantine_import":
        return [
            "copy_candidate_artifacts_with_preserved_relative_paths_into_quarantine_branch",
            "run_python_tools_english_text_first_graph_first_manifest_check",
            "run_small_smoke_before_claiming_pdf_english_ready",
        ]
    return [
        "stage_recovered_artifacts_under_a_candidate_root",
        "preserve_relative_paths_from_config_tools_outputs",
        "rerun_this_intake_gate_before_copying_into_protected_paths",
    ]


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Recovery Intake Validation 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Candidate: `{report['candidate_root_contract']['candidate_label']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Safe Next Actions", ""])
    for action in report["safe_next_actions"]:
        lines.append(f"- `{action}`")
    lines.extend(["", "## Unsafe Actions", ""])
    for action in report["unsafe_actions"]:
        lines.append(f"- `{action}`")
    lines.append("")
    lines.append("Candidate roots outside the workspace are reported by label only; absolute local paths are not a reproducible input contract.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a staged PDF English recovery candidate before import.")
    parser.add_argument("--candidate-root", default="", help="Directory containing preserved relative config/tools/outputs paths.")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    candidate_root = Path(args.candidate_root) if args.candidate_root else None
    report = build_report(candidate_root)
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ready and report["status"] != "candidate_ready_for_quarantine_import":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
