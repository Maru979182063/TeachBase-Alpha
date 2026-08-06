from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from teachbase.final_chains import ChainRunRequest, build_final_chain_adapters, load_final_chain_registry
from teachbase.infrastructure.artifact_store import write_json, write_text

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_execution_gap_20260806.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_execution_gap_20260806.md"

SAMPLE_INPUTS = {
    "doc_math": "tests/fixtures/final_chain_samples/doc_math_sample.docx",
    "doc_english": "tests/fixtures/final_chain_samples/doc_english_sample.docx",
    "pdf_math": "tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
    "pdf_english": "tests/fixtures/final_chain_samples/pdf_english_sample.pdf",
}

NO_SIDE_EFFECT_CONTRACT = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


def build_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    adapters = build_final_chain_adapters(registry, workspace_root=ROOT)
    rows = []
    for chain in registry.chains:
        request = ChainRunRequest(
            chain_id=chain.chain_id,
            input_path=SAMPLE_INPUTS[chain.chain_id],
            output_root="outputs/final_chain_runs",
            dry_run=True,
        )
        preflight = adapters[chain.chain_id].execution_preflight(request)
        rows.append(_row_from_preflight(preflight))
    missing_for_continuous_production = sorted(
        {
            reason.split(":", 1)[0] if reason.startswith("standard_cli_arg_missing:") else reason
            for row in rows
            for reason in row["blocked_reasons"]
        }
        | {
            "real_worker_runtime_missing",
            "worker_heartbeat_and_timeout_recovery_missing",
            "database_queue_contract_missing",
        }
    )
    return {
        "schema_version": "final_chain_execution_gap_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "blocked_missing_execution_contracts",
        "continuous_production_ready": False,
        "chain_count": len(rows),
        "chain_ids": [row["chain_id"] for row in rows],
        "execution_preflight_ready_count": sum(1 for row in rows if row["status"] == "execution_preflight_ready"),
        "execution_preflight_blocked_count": sum(
            1 for row in rows if row["status"] == "execution_preflight_blocked"
        ),
        "missing_for_continuous_production": missing_for_continuous_production,
        "rows": rows,
        "execution_contract": NO_SIDE_EFFECT_CONTRACT,
    }


def _row_from_preflight(preflight: dict[str, Any]) -> dict[str, Any]:
    command_contract = preflight.get("command_contract") if isinstance(preflight.get("command_contract"), dict) else {}
    plan = preflight.get("plan") if isinstance(preflight.get("plan"), dict) else {}
    return {
        "chain_id": preflight["chain_id"],
        "status": preflight["status"],
        "blocked_reasons": list(preflight.get("blocked_reasons") or []),
        "plan_status": plan.get("status"),
        "canonical_entrypoint": command_contract.get("canonical_entrypoint"),
        "standard_args_supported": command_contract.get("standard_args_supported") is True,
        "emits_job_result": command_contract.get("emits_job_result") is True,
        "resume_from_checkpoint": command_contract.get("resume_from_checkpoint") is True,
        "adapter_invoked_entrypoint": preflight.get("adapter_invoked_entrypoint") is True,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Execution Gap 2026-08-06",
        "",
        f"Status: `{report['status']}`",
        f"Continuous production ready: `{report['continuous_production_ready']}`",
        "",
        "## Missing",
        "",
    ]
    for item in report["missing_for_continuous_production"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Chains", ""])
    for row in report["rows"]:
        reasons = ", ".join(f"`{reason}`" for reason in row["blocked_reasons"])
        lines.append(f"- `{row['chain_id']}` `{row['status']}` {reasons}")
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
