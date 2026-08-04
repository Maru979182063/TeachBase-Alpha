from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from teachbase.final_chains import build_final_chain_control_contract, build_final_chain_control_dashboard, load_final_chain_registry
from teachbase.infrastructure.artifact_store import write_json, write_text

from tools.build_final_chain_ready_sample_report import build_report as build_ready_sample_report
from tools.build_pdf_english_recovery_source_audit import build_report as build_pdf_english_source_audit_report
from tools.validate_pdf_english_recovery import build_report as build_pdf_english_recovery_report

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_ops_gate_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_ops_gate_20260804.md"


def build_gate_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    dashboard = build_final_chain_control_dashboard(registry, workspace_root=ROOT)
    control_contract = build_final_chain_control_contract(registry)
    ready_samples = build_ready_sample_report()
    pdf_english_blocker = build_pdf_english_source_audit_report()
    pdf_english_recovery = build_pdf_english_recovery_report()
    checks = [
        {
            "name": "dashboard_contract_ok",
            "ok": dashboard["contract_ok"] is True,
            "value": dashboard["contract_ok"],
        },
        {
            "name": "three_chains_need_only_sample_inputs",
            "ok": dashboard["lane_counts"].get("needs_sample_input") == 3,
            "value": dashboard["lane_counts"].get("needs_sample_input"),
        },
        {
            "name": "one_chain_requires_artifact_restore_or_smoke",
            "ok": dashboard["lane_counts"].get("needs_artifact_restore_or_smoke") == 1,
            "value": dashboard["lane_counts"].get("needs_artifact_restore_or_smoke"),
        },
        {
            "name": "ready_sample_dry_runs_cover_three_chains",
            "ok": ready_samples["ready_for_adapter_dry_run_count"] == 3,
            "value": ready_samples["ready_for_adapter_dry_run_count"],
        },
        {
            "name": "ready_sample_schedules_are_ready",
            "ok": all(row["schedule_status"] == "scheduled_ready" for row in ready_samples["rows"]),
            "value": [row["schedule_status"] for row in ready_samples["rows"]],
        },
        {
            "name": "ready_sample_adapters_do_not_invoke_entrypoints",
            "ok": all(row["adapter_invoked_entrypoint"] is False for row in ready_samples["rows"]),
            "value": [row["adapter_invoked_entrypoint"] for row in ready_samples["rows"]],
        },
        {
            "name": "control_contract_is_dry_run_only",
            "ok": control_contract["control_plane_contract"]["dry_run_only"] is True
            and control_contract["control_plane_contract"]["execute_intent_blocked"] is True,
            "value": control_contract["control_plane_contract"],
        },
        {
            "name": "control_contract_covers_four_chains",
            "ok": control_contract["chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"],
            "value": control_contract["chain_ids"],
        },
        {
            "name": "pdf_english_recovery_blocker_is_explicit",
            "ok": pdf_english_blocker["recovery_status"] == "blocked_missing_manifest_and_smoke_artifacts",
            "value": pdf_english_blocker["recovery_status"],
        },
        {
            "name": "pdf_english_recovery_source_audit_has_no_importable_source",
            "ok": pdf_english_blocker["source_audit_status"] == "no_importable_source_found",
            "value": pdf_english_blocker["source_audit_status"],
        },
        {
            "name": "pdf_english_recovery_validator_fails_closed",
            "ok": pdf_english_recovery["status"] == "blocked_missing_or_invalid_manifest",
            "value": pdf_english_recovery["status"],
        },
        {
            "name": "pdf_english_recovery_requires_four_branch_manifest",
            "ok": "four_branch_runs_declared" in pdf_english_recovery["required_manifest_check_failures"],
            "value": pdf_english_recovery["required_manifest_check_failures"],
        },
        {
            "name": "no_runtime_side_effects_reported",
            "ok": all_no_side_effects(dashboard, control_contract, ready_samples, pdf_english_blocker, pdf_english_recovery),
            "value": "model/database/runtime/secrets all false",
        },
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        "schema_version": "final_chain_ops_gate.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "dashboard_lane_counts": dashboard["lane_counts"],
        "control_contract_schema": control_contract["schema_version"],
        "ready_sample_count": ready_samples["ready_for_adapter_dry_run_count"],
        "pdf_english_recovery_status": pdf_english_blocker["recovery_status"],
        "pdf_english_recovery_source_audit_status": pdf_english_blocker["source_audit_status"],
        "pdf_english_recovery_validation_status": pdf_english_recovery["status"],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def all_no_side_effects(*reports: dict[str, Any]) -> bool:
    for report in reports:
        contract = report.get("execution_contract")
        if contract != {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        }:
            return False
    return True


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Ops Gate 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_gate_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
