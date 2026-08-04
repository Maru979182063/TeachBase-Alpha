from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from teachbase.final_chains import (
    build_environment_interaction_contract,
    build_final_chain_control_contract,
    build_final_chain_control_dashboard,
    load_final_chain_registry,
)
from teachbase.infrastructure.artifact_store import write_json, write_text

from tools.build_final_chain_ready_sample_report import build_report as build_ready_sample_report
from tools.build_final_chain_batch_queue_report import (
    REPORT_JSON as BATCH_QUEUE_REPORT_JSON,
    REPORT_MD as BATCH_QUEUE_REPORT_MD,
    build_report as build_batch_queue_report,
    render_markdown as render_batch_queue_markdown,
)
from tools.build_pdf_english_recovery_source_audit import build_report as build_pdf_english_source_audit_report
from tools.validate_final_chain_batch_queue_report import (
    REPORT_JSON as BATCH_QUEUE_VALIDATION_JSON,
    REPORT_MD as BATCH_QUEUE_VALIDATION_MD,
    build_validation_report as build_batch_queue_validation_report,
    render_markdown as render_batch_queue_validation_markdown,
)
from tools.build_final_chain_orchestrator_handshake import (
    REPORT_JSON as ORCHESTRATOR_HANDSHAKE_JSON,
    REPORT_MD as ORCHESTRATOR_HANDSHAKE_MD,
    build_report as build_orchestrator_handshake_report,
    render_markdown as render_orchestrator_handshake_markdown,
)
from tools.validate_final_chain_orchestrator_handshake import (
    REPORT_JSON as ORCHESTRATOR_HANDSHAKE_VALIDATION_JSON,
    REPORT_MD as ORCHESTRATOR_HANDSHAKE_VALIDATION_MD,
    build_validation_report as build_orchestrator_handshake_validation_report,
    render_markdown as render_orchestrator_handshake_validation_markdown,
)
from tools.validate_pdf_english_recovery import build_report as build_pdf_english_recovery_report

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_ops_gate_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_ops_gate_20260804.md"


def build_gate_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    dashboard = build_final_chain_control_dashboard(registry, workspace_root=ROOT)
    control_contract = build_final_chain_control_contract(registry)
    environment_contract = build_environment_interaction_contract(registry, workspace_root=ROOT)
    ready_samples = build_ready_sample_report()
    batch_queue = build_batch_queue_report()
    write_json(BATCH_QUEUE_REPORT_JSON, batch_queue)
    write_text(BATCH_QUEUE_REPORT_MD, render_batch_queue_markdown(batch_queue))
    batch_queue_validation = build_batch_queue_validation_report()
    write_json(BATCH_QUEUE_VALIDATION_JSON, batch_queue_validation)
    write_text(BATCH_QUEUE_VALIDATION_MD, render_batch_queue_validation_markdown(batch_queue_validation))
    orchestrator_handshake = build_orchestrator_handshake_report()
    write_json(ORCHESTRATOR_HANDSHAKE_JSON, orchestrator_handshake)
    write_text(ORCHESTRATOR_HANDSHAKE_MD, render_orchestrator_handshake_markdown(orchestrator_handshake))
    orchestrator_handshake_validation = build_orchestrator_handshake_validation_report()
    write_json(ORCHESTRATOR_HANDSHAKE_VALIDATION_JSON, orchestrator_handshake_validation)
    write_text(ORCHESTRATOR_HANDSHAKE_VALIDATION_MD, render_orchestrator_handshake_validation_markdown(orchestrator_handshake_validation))
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
            "name": "ready_sample_job_records_validate",
            "ok": all(
                row["job_record_self_validation_ok"] is True and row["job_record_validation_ok"] is True
                for row in ready_samples["rows"]
            ),
            "value": {
                "self_validation_error_counts": [
                    row["job_record_self_validation_error_count"] for row in ready_samples["rows"]
                ],
                "external_validation_error_counts": [row["job_record_validation_error_count"] for row in ready_samples["rows"]],
            },
        },
        {
            "name": "batch_queue_covers_four_chains",
            "ok": batch_queue["chain_count"] == 4,
            "value": [row["chain_id"] for row in batch_queue["rows"]],
        },
        {
            "name": "batch_queue_schedules_three_ready_one_blocked",
            "ok": batch_queue["scheduled_ready_count"] == 3
            and batch_queue["scheduled_blocked_count"] == 1
            and batch_queue["rejected_count"] == 0,
            "value": {
                "ready": batch_queue["scheduled_ready_count"],
                "blocked": batch_queue["scheduled_blocked_count"],
                "rejected": batch_queue["rejected_count"],
            },
        },
        {
            "name": "batch_queue_job_records_validate",
            "ok": all(row["record_validation_ok"] and row["self_validation_ok"] for row in batch_queue["rows"]),
            "value": {
                "external": [row["record_validation_error_count"] for row in batch_queue["rows"]],
                "self": [row["self_validation_error_count"] for row in batch_queue["rows"]],
            },
        },
        {
            "name": "batch_queue_report_validation_passes",
            "ok": batch_queue_validation["status"] == "pass",
            "value": batch_queue_validation["status"],
        },
        {
            "name": "orchestrator_handshake_passes",
            "ok": orchestrator_handshake["status"] == "pass",
            "value": orchestrator_handshake["status"],
        },
        {
            "name": "orchestrator_handshake_validation_passes",
            "ok": orchestrator_handshake_validation["status"] == "pass",
            "value": orchestrator_handshake_validation["status"],
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
            "name": "control_contract_declares_non_executing_recovery_plan",
            "ok": _control_contract_declares_recovery_plan(control_contract),
            "value": control_contract["job_lifecycle_policy"].get("recovery_plan"),
        },
        {
            "name": "environment_contract_passes",
            "ok": environment_contract["status"] == "pass",
            "value": environment_contract["status"],
        },
        {
            "name": "environment_contract_covers_four_profiles",
            "ok": environment_contract["chain_count"] == 4,
            "value": [item["chain_id"] for item in environment_contract["profiles"]],
        },
        {
            "name": "environment_contract_keeps_pdf_english_fail_closed",
            "ok": environment_contract["blocked_chain_ids"] == ["pdf_english"],
            "value": environment_contract["blocked_chain_ids"],
        },
        {
            "name": "environment_contract_limits_writes_to_outputs",
            "ok": environment_contract["filesystem_contract"]["write_scope"] == ["outputs/"],
            "value": environment_contract["filesystem_contract"]["write_scope"],
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
            "ok": all_no_side_effects(
                dashboard,
                control_contract,
                environment_contract,
                ready_samples,
                batch_queue,
                batch_queue_validation,
                orchestrator_handshake,
                orchestrator_handshake_validation,
                pdf_english_blocker,
                pdf_english_recovery,
            ),
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
        "environment_contract_schema": environment_contract["schema_version"],
        "environment_ready_chain_ids": environment_contract["ready_chain_ids"],
        "environment_blocked_chain_ids": environment_contract["blocked_chain_ids"],
        "ready_sample_count": ready_samples["ready_for_adapter_dry_run_count"],
        "batch_queue_schema": batch_queue["schema_version"],
        "batch_queue_validation_schema": batch_queue_validation["schema_version"],
        "orchestrator_handshake_schema": orchestrator_handshake["schema_version"],
        "orchestrator_handshake_validation_schema": orchestrator_handshake_validation["schema_version"],
        "batch_queue_ready_count": batch_queue["scheduled_ready_count"],
        "batch_queue_blocked_count": batch_queue["scheduled_blocked_count"],
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


def _control_contract_declares_recovery_plan(control_contract: dict[str, Any]) -> bool:
    commands = control_contract.get("commands")
    lifecycle = control_contract.get("job_lifecycle_policy")
    if not isinstance(commands, dict) or not isinstance(lifecycle, dict):
        return False
    recovery = lifecycle.get("recovery_plan")
    return (
        isinstance(commands.get("job_recovery_plan"), str)
        and commands["job_recovery_plan"].startswith("tools/final_chain_control.py job-recovery-plan ")
        and isinstance(commands.get("job_schedule_replacement"), str)
        and commands["job_schedule_replacement"].startswith("tools/final_chain_control.py job-schedule-replacement ")
        and isinstance(recovery, dict)
        and recovery.get("schema_version") == "final_chain_job_recovery_plan.v0.1"
        and recovery.get("non_executing") is True
        and recovery.get("replacement_job_required_for_retry") is True
        and recovery.get("replacement_inherits_request_snapshot") is True
        and recovery.get("replacement_records_parent_job") is True
        and recovery.get("retry_budget_default_max_attempts") == 3
    )


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
