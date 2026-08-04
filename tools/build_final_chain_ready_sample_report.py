from __future__ import annotations

import json
from pathlib import Path

from teachbase.final_chains import (
    ChainRunRequest,
    build_final_chain_adapters,
    build_readiness_matrix,
    load_final_chain_registry,
    schedule_chain_run,
    validate_job_record,
)
from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_ready_sample_dry_run_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_ready_sample_dry_run_20260804.md"
OUTPUT_ROOT = "outputs/final_chain_sample_dry_runs"

READY_SAMPLE_INPUTS = {
    "doc_math": "tests/fixtures/final_chain_samples/doc_math_sample.docx",
    "doc_english": "tests/fixtures/final_chain_samples/doc_english_sample.docx",
    "pdf_math": "tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
}


def build_report() -> dict:
    registry = load_final_chain_registry(REGISTRY)
    readiness = build_readiness_matrix(registry, workspace_root=ROOT, sample_inputs=READY_SAMPLE_INPUTS)
    adapters = build_final_chain_adapters(registry, workspace_root=ROOT)
    rows = []
    for chain_id, sample_path in READY_SAMPLE_INPUTS.items():
        request = ChainRunRequest(chain_id=chain_id, input_path=sample_path, output_root=OUTPUT_ROOT)
        dry_run = adapters[chain_id].dry_run(request)
        job_record = schedule_chain_run(registry, request, workspace_root=ROOT)
        job_validation = validate_job_record(job_record)
        rows.append(
            {
                "chain_id": chain_id,
                "sample_input": sample_path,
                "adapter_dry_run_status": dry_run["status"],
                "plan_status": dry_run["plan"]["status"],
                "schedule_status": job_record["status"],
                "job_record_self_validation_ok": job_record["record_validation"]["ok"],
                "job_record_self_validation_error_count": job_record["record_validation"]["error_count"],
                "job_record_validation_ok": job_validation["ok"],
                "job_record_validation_error_count": job_validation["error_count"],
                "job_record_written": bool(job_record.get("record_path")),
                "job_record_path_contract": "outputs/final_chain_sample_dry_runs/_control/jobs/<generated>/job_record.json",
                "adapter_invoked_entrypoint": dry_run["adapter_invoked_entrypoint"],
                "execution_contract": dry_run["execution_contract"],
            }
        )
    pdf_english_row = next(row for row in readiness["rows"] if row["chain_id"] == "pdf_english")
    return {
        "schema_version": "final_chain_ready_sample_dry_run_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "sample_count": len(READY_SAMPLE_INPUTS),
        "ready_for_adapter_dry_run_count": readiness["ready_for_adapter_dry_run_count"],
        "pdf_english_recovery_status": pdf_english_row["readiness_tier"],
        "rows": rows,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Final Chain Ready Sample Dry Run 2026-08-04",
        "",
        "This report verifies the currently ready final-chain control adapters with repository-relative sample inputs.",
        "It does not execute production chain entrypoints, call models, write databases, or import Runtime.",
        "",
        "## Summary",
        "",
        f"- `ready_for_adapter_dry_run_count`: {report['ready_for_adapter_dry_run_count']}",
        f"- `pdf_english_recovery_status`: `{report['pdf_english_recovery_status']}`",
        "",
        "## Rows",
        "",
    ]
    for row in report["rows"]:
        lines.append(
            f"- `{row['chain_id']}` `{row['sample_input']}`: "
            f"adapter `{row['adapter_dry_run_status']}`, schedule `{row['schedule_status']}`"
        )
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
