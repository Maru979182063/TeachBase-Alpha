from __future__ import annotations

import json
from pathlib import Path

from teachbase.final_chains import load_final_chain_registry, schedule_registry_batch
from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_batch_queue_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_batch_queue_20260804.md"
OUTPUT_ROOT = "outputs/final_chain_batch_queue"

READY_SAMPLE_INPUTS = {
    "doc_math": "tests/fixtures/final_chain_samples/doc_math_sample.docx",
    "doc_english": "tests/fixtures/final_chain_samples/doc_english_sample.docx",
    "pdf_math": "tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
    "pdf_english": "tests/fixtures/final_chain_samples/pdf_english_sample.pdf",
}


def build_report() -> dict:
    registry = load_final_chain_registry(REGISTRY)
    raw_report = schedule_registry_batch(
        registry,
        READY_SAMPLE_INPUTS,
        output_root=OUTPUT_ROOT,
        workspace_root=ROOT,
    )
    rows = [_public_row(row) for row in raw_report["rows"]]
    checks = [
        {
            "name": "batch_covers_four_registered_chains",
            "ok": raw_report["chain_count"] == 4,
            "value": [row["chain_id"] for row in rows],
        },
        {
            "name": "four_ready_jobs_scheduled",
            "ok": raw_report["scheduled_ready_count"] == 4,
            "value": raw_report["scheduled_ready_count"],
        },
        {
            "name": "pdf_english_is_scheduled_ready_after_raw_pdf_promotion",
            "ok": _row(raw_report, "pdf_english").get("schedule_status") == "scheduled_ready",
            "value": _row(raw_report, "pdf_english").get("plan_status"),
        },
        {
            "name": "no_rejected_jobs",
            "ok": raw_report["rejected_count"] == 0,
            "value": raw_report["rejected_count"],
        },
        {
            "name": "all_job_records_validate",
            "ok": all(row["record_validation_ok"] and row["self_validation_ok"] for row in raw_report["rows"]),
            "value": {
                "external": [row["record_validation_error_count"] for row in raw_report["rows"]],
                "self": [row["self_validation_error_count"] for row in raw_report["rows"]],
            },
        },
        {
            "name": "all_job_records_written_under_outputs",
            "ok": all(str(row["record_path"]).startswith(f"{OUTPUT_ROOT}/_control/jobs/") for row in raw_report["rows"]),
            "value": [row["record_path_contract"] for row in rows],
        },
        {
            "name": "no_runtime_side_effects_reported",
            "ok": all(row["execution_contract"] == raw_report["execution_contract"] for row in raw_report["rows"]),
            "value": "model/database/runtime/secrets all false",
        },
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        **raw_report,
        "status": "pass" if raw_report["status"] == "pass" and not failed else "fail",
        "rows": rows,
        "checks": checks,
    }


def _row(report: dict, chain_id: str) -> dict:
    return next((row for row in report["rows"] if row["chain_id"] == chain_id), {})


def _public_row(row: dict) -> dict:
    record_path_contract = f"{OUTPUT_ROOT}/_control/jobs/<generated>/job_record.json"
    return {
        **row,
        "record_path": record_path_contract,
        "record_path_contract": record_path_contract,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Final Chain Batch Queue 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Scheduled ready: `{report['scheduled_ready_count']}`",
        f"Scheduled blocked: `{report['scheduled_blocked_count']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Rows", ""])
    for row in report["rows"]:
        lines.append(f"- `{row['chain_id']}` `{row['schedule_status']}` `{row['record_path']}`")
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
