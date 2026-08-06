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
from tools.build_pdf_english_raw_pdf_promotion_gate import build_report as build_pdf_english_raw_promotion_report
from tools.validate_pdf_english_recovery_intake import build_report as build_pdf_english_recovery_intake_report

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
PACKAGE_JSON = ROOT / "package.json"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_ops_health_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_ops_health_20260804.md"

EXPECTED_CHAIN_IDS = ["doc_math", "doc_english", "pdf_math", "pdf_english"]
EXPECTED_READY_CHAIN_IDS = ["doc_math", "doc_english", "pdf_math", "pdf_english"]
EXPECTED_BLOCKED_CHAIN_IDS: list[str] = []
REQUIRED_NPM_SCRIPTS = {
    "test:final-chain-ops",
    "test:cleanroom-hardening-status",
    "final-chain:list",
    "final-chain:plan",
    "final-chain:env-check",
    "final-chain:adapter-contracts",
    "final-chain:adapter-describe",
    "final-chain:adapter-dry-run",
    "final-chain:adapter-execution-preflight",
    "final-chain:readiness-matrix",
    "final-chain:dashboard",
    "final-chain:contract",
    "final-chain:env-contract",
    "final-chain:queue",
    "final-chain:job-inspect",
    "final-chain:job-validate",
    "final-chain:job-transition",
    "final-chain:job-recovery-plan",
    "final-chain:job-schedule-replacement",
    "audit:pdf-english-recovery-intake",
    "audit:pdf-english-rebuild-smoke",
    "audit:pdf-english-raw-pdf-promotion",
    "audit:final-chain-execution-gap",
}
REQUIRED_CONTROL_COMMANDS = {
    "contract",
    "env_contract",
    "list",
    "plan",
    "schedule",
    "queue",
    "adapter_dry_run",
    "adapter_execution_preflight",
    "job_inspect",
    "job_validate",
    "job_recovery_plan",
    "job_schedule_replacement",
    "job_transition",
}
NO_SIDE_EFFECT_CONTRACT = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


def build_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    control_contract = build_final_chain_control_contract(registry)
    environment_contract = build_environment_interaction_contract(registry, workspace_root=ROOT)
    dashboard = build_final_chain_control_dashboard(registry, workspace_root=ROOT)
    package_scripts = _package_scripts()
    intake = build_pdf_english_recovery_intake_report()
    raw_promotion = build_pdf_english_raw_promotion_report()
    checks = _build_checks(control_contract, environment_contract, dashboard, package_scripts, intake, raw_promotion)
    return {
        "schema_version": "final_chain_ops_health.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "chain_ids": [chain.chain_id for chain in registry.chains],
        "ready_chain_ids": environment_contract.get("ready_chain_ids", []),
        "blocked_chain_ids": environment_contract.get("blocked_chain_ids", []),
        "lane_counts": dashboard.get("lane_counts", {}),
        "required_npm_scripts": sorted(REQUIRED_NPM_SCRIPTS),
        "missing_npm_scripts": sorted(REQUIRED_NPM_SCRIPTS.difference(package_scripts.keys())),
        "pdf_english_intake_status": intake.get("status"),
        "pdf_english_raw_pdf_promotion_status": raw_promotion.get("status"),
        "pdf_english_java_shell_admission_allowed": raw_promotion.get("java_shell_admission", {}).get("allowed"),
        "checks": checks,
        "execution_contract": NO_SIDE_EFFECT_CONTRACT,
    }


def _build_checks(
    control_contract: dict[str, Any],
    environment_contract: dict[str, Any],
    dashboard: dict[str, Any],
    package_scripts: dict[str, str],
    intake: dict[str, Any],
    raw_promotion: dict[str, Any],
) -> list[dict[str, Any]]:
    commands = control_contract.get("commands") if isinstance(control_contract.get("commands"), dict) else {}
    lifecycle = (
        control_contract.get("job_lifecycle_policy")
        if isinstance(control_contract.get("job_lifecycle_policy"), dict)
        else {}
    )
    recovery_plan = lifecycle.get("recovery_plan") if isinstance(lifecycle.get("recovery_plan"), dict) else {}
    transition_guard = lifecycle.get("transition_guard") if isinstance(lifecycle.get("transition_guard"), dict) else {}
    filesystem_contract = (
        environment_contract.get("filesystem_contract")
        if isinstance(environment_contract.get("filesystem_contract"), dict)
        else {}
    )
    return [
        {
            "name": "four_final_chains_split_is_stable",
            "ok": control_contract.get("chain_ids") == EXPECTED_CHAIN_IDS
            and environment_contract.get("ready_chain_ids") == EXPECTED_READY_CHAIN_IDS
            and environment_contract.get("blocked_chain_ids") == EXPECTED_BLOCKED_CHAIN_IDS,
            "value": {
                "chain_ids": control_contract.get("chain_ids"),
                "ready": environment_contract.get("ready_chain_ids"),
                "blocked": environment_contract.get("blocked_chain_ids"),
            },
        },
        {
            "name": "control_cli_commands_declared",
            "ok": REQUIRED_CONTROL_COMMANDS.issubset(commands.keys()),
            "value": sorted(commands.keys()),
        },
        {
            "name": "npm_operator_scripts_expose_control_surface",
            "ok": REQUIRED_NPM_SCRIPTS.issubset(package_scripts.keys()),
            "value": sorted(REQUIRED_NPM_SCRIPTS.difference(package_scripts.keys())),
        },
        {
            "name": "job_recovery_and_replacement_are_non_executing",
            "ok": recovery_plan.get("schema_version") == "final_chain_job_recovery_plan.v0.1"
            and recovery_plan.get("non_executing") is True
            and recovery_plan.get("replacement_job_required_for_retry") is True
            and recovery_plan.get("replacement_inherits_request_snapshot") is True
            and recovery_plan.get("replacement_records_parent_job") is True,
            "value": recovery_plan,
        },
        {
            "name": "job_transition_guard_is_locked_and_versioned",
            "ok": transition_guard.get("same_directory_lock") is True
            and transition_guard.get("expected_status_supported") is True
            and transition_guard.get("expected_state_version_supported") is True
            and transition_guard.get("stale_transition_error") == "final_chain_job_stale_transition",
            "value": transition_guard,
        },
        {
            "name": "filesystem_and_runtime_policy_are_closed",
            "ok": filesystem_contract.get("write_scope") == ["outputs/"]
            and environment_contract.get("execution_contract") == NO_SIDE_EFFECT_CONTRACT
            and control_contract.get("execution_contract") == NO_SIDE_EFFECT_CONTRACT,
            "value": {
                "write_scope": filesystem_contract.get("write_scope"),
                "environment_execution_contract": environment_contract.get("execution_contract"),
                "control_execution_contract": control_contract.get("execution_contract"),
            },
        },
        {
            "name": "dashboard_lanes_match_current_recovery_state",
            "ok": dashboard.get("lane_counts") == {"needs_sample_input": 4},
            "value": dashboard.get("lane_counts"),
        },
        {
            "name": "pdf_english_intake_gate_has_fresh_candidate",
            "ok": intake.get("status") == "candidate_ready_for_quarantine_import"
            and intake.get("execution_contract") == NO_SIDE_EFFECT_CONTRACT,
            "value": {
                "status": intake.get("status"),
                "required_check_failures": intake.get("required_check_failures"),
            },
        },
        {
            "name": "pdf_english_raw_pdf_promotion_admits_java_shell_without_model_execution",
            "ok": raw_promotion.get("status") == "pass"
            and raw_promotion.get("java_shell_admission", {}).get("allowed") is True
            and raw_promotion.get("production_model_execution_policy", {}).get("model_calls_default_enabled") is False
            and raw_promotion.get("execution_contract") == NO_SIDE_EFFECT_CONTRACT,
            "value": {
                "status": raw_promotion.get("status"),
                "java_shell_admission": raw_promotion.get("java_shell_admission"),
                "production_model_execution_policy": raw_promotion.get("production_model_execution_policy"),
            },
        },
    ]


def _package_scripts() -> dict[str, str]:
    payload = json.loads(PACKAGE_JSON.read_text(encoding="utf-8-sig"))
    scripts = payload.get("scripts") if isinstance(payload, dict) else {}
    return {str(key): str(value) for key, value in scripts.items()} if isinstance(scripts, dict) else {}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Ops Health 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        "",
        "## Split",
        "",
        f"- Ready: `{', '.join(report['ready_chain_ids'])}`",
        f"- Blocked: `{', '.join(report['blocked_chain_ids'])}`",
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
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
