from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "english_text_first_graph_first" / "active_manifest.json"
SMOKE_ZIP = ROOT / "outputs" / "english_text_first_graph_first" / "final_chain_smoke_20260728.zip"
SMOKE_DIR = ROOT / "outputs" / "english_text_first_graph_first" / "final_chain_smoke_20260728"
REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_recovery_validation_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_recovery_validation_20260804.md"

REQUIRED_RUN_KEYS = ("reading", "grammar", "writing", "cloze")


def build_report() -> dict[str, Any]:
    manifest_payload, manifest_error = _load_manifest()
    checks = [
        _check("active_manifest_exists", MANIFEST.is_file(), path=_relative(MANIFEST)),
        _check("active_manifest_json_object", isinstance(manifest_payload, dict), error=manifest_error),
        _check(
            "pipeline_name_matches",
            isinstance(manifest_payload, dict) and manifest_payload.get("pipeline_name") == "english_text_first_graph_first",
            expected="english_text_first_graph_first",
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
            required=list(REQUIRED_RUN_KEYS),
        ),
        _check("prior_smoke_zip_present", SMOKE_ZIP.is_file(), path=_relative(SMOKE_ZIP)),
        _check("prior_smoke_dir_present", SMOKE_DIR.is_dir(), path=_relative(SMOKE_DIR)),
    ]
    missing_required = [
        check["name"]
        for check in checks
        if check["name"]
        in {
            "active_manifest_exists",
            "active_manifest_json_object",
            "pipeline_name_matches",
            "allow_only_manifest_runs_enabled",
            "timestamp_latest_selection_forbidden",
            "four_branch_runs_declared",
        }
        and not check["ok"]
    ]
    status = "ready_for_manifest_gate" if not missing_required else "blocked_missing_or_invalid_manifest"
    return {
        "schema_version": "pdf_english_recovery_validation.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "status": status,
        "checks": checks,
        "required_manifest_check_failures": missing_required,
        "manifest_gate": "python tools/english_text_first_graph_first_manifest_check.py",
        "manifest_success_marker": "english_text_first_graph_first_manifest_valid",
        "safe_next_actions": _safe_next_actions(status),
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _load_manifest() -> tuple[dict[str, Any] | None, str]:
    if not MANIFEST.is_file():
        return None, "manifest_missing"
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None, "manifest_invalid_json"
    if not isinstance(payload, dict):
        return None, "manifest_not_object"
    return payload, ""


def _has_four_branch_runs(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    candidates = []
    for key in ("runs", "branch_runs", "active_runs", "run_ids"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    return any(all(key in candidate and candidate[key] for key in REQUIRED_RUN_KEYS) for candidate in candidates)


def _check(name: str, ok: bool, **extra: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, **extra}


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _safe_next_actions(status: str) -> list[str]:
    if status == "ready_for_manifest_gate":
        return [
            "run_python_tools_english_text_first_graph_first_manifest_check",
            "run_small_smoke_before_adapter_ready_claim",
        ]
    return [
        "restore_active_manifest_from_original_machine_or_backup",
        "restore_or_rerun_small_smoke_artifacts",
        "do_not_create_synthetic_active_manifest",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Recovery Validation 2026-08-04",
        "",
        f"Status: `{report['status']}`",
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
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PDF English graph-first manifest recovery state.")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ready and report["status"] != "ready_for_manifest_gate":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
