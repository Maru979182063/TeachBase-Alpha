from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "docs" / "reports" / "worktree_compartments_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "worktree_compartments_20260804.md"

FOUNDATION_PATHS = {
    "src/teachbase/infrastructure/artifact_store.py",
    "src/teachbase/infrastructure/model_call_guard.py",
    "tests/test_artifact_store.py",
    "tests/test_model_call_guard.py",
    "tests/test_docx_native_text_repair_model_node_v01.py",
    "tests/test_visual_model_checkpoint_integration.py",
    "tools/docx_native_text_repair_model_node_v01.py",
    "tools/teacher_handout_visual_transcribe_doubao.py",
    "tools/visual_transcription_pipeline.py",
    "tools/run_foundation_hardening_gate.py",
    "docs/reports/foundation_hardening_test_report_20260803.json",
}

FINAL_CHAIN_PATHS = {
    "config/final_chain_registry.yaml",
    "docs/reports/cleanup_candidates_cleanroom_20260731.json",
    "docs/reports/cleanup_candidates_cleanroom_20260731.md",
    "docs/reports/cleanup_candidates_old_local_20260731.json",
    "docs/reports/cleanup_candidates_old_local_20260731.md",
    "docs/reports/final_chain_inventory_20260731.json",
    "docs/reports/final_chain_inventory_20260731.md",
    "docs/reports/final_chain_control_dashboard_20260804.json",
    "docs/reports/final_chain_control_dashboard_20260804.md",
    "docs/reports/final_chain_cleanroom_import_audit_20260804.json",
    "docs/reports/final_chain_cleanroom_import_audit_20260804.md",
    "docs/reports/docx_math_final_import_20260804.json",
    "docs/reports/docx_math_final_import_20260804.md",
    "docs/reports/doc_english_code_import_20260804.json",
    "docs/reports/doc_english_code_import_20260804.md",
    "docs/reports/pdf_english_manifest_recovery_audit_20260804.json",
    "docs/reports/pdf_english_manifest_recovery_audit_20260804.md",
    "docs/reports/final_chain_ready_sample_dry_run_20260804.json",
    "docs/reports/final_chain_ready_sample_dry_run_20260804.md",
    "docs/reports/final_chain_ops_gate_20260804.json",
    "docs/reports/final_chain_ops_gate_20260804.md",
    "docs/reports/pdf_english_recovery_validation_20260804.json",
    "docs/reports/pdf_english_recovery_validation_20260804.md",
    "docs/reports/cleanroom_hardening_status_20260804.json",
    "docs/reports/cleanroom_hardening_status_20260804.md",
    "docs/reports/final_chain_surface_classification_cleanroom_20260731.json",
    "docs/reports/final_chain_surface_classification_cleanroom_20260731.md",
    "docs/reports/final_chain_surface_classification_old_local_20260731.json",
    "docs/reports/final_chain_surface_classification_old_local_20260731.md",
    "tests/test_cleanup_candidate_report.py",
    "tests/test_final_chain_registry.py",
    "tests/test_final_chain_surface_classifier.py",
    "tests/test_final_chain_control.py",
    "tools/build_cleanup_candidate_report.py",
    "tools/classify_final_chain_surface.py",
    "tools/final_chain_control.py",
    "tools/build_final_chain_control_dashboard.py",
    "tools/audit_final_chain_cleanroom_imports.py",
    "tools/build_docx_math_final_import_report.py",
    "tools/build_doc_english_code_import_report.py",
    "tools/build_final_chain_ready_sample_report.py",
    "tools/build_pdf_english_recovery_source_audit.py",
    "tools/run_final_chain_ops_gate.py",
    "tools/validate_pdf_english_recovery.py",
    "tools/run_cleanroom_hardening_status_gate.py",
    "tools/validate_final_chain_registry.py",
    "src/teachbase/final_chains/__init__.py",
    "src/teachbase/final_chains/adapters.py",
    "src/teachbase/final_chains/control.py",
    "src/teachbase/final_chains/dashboard.py",
    "src/teachbase/final_chains/environment.py",
    "src/teachbase/final_chains/import_audit.py",
    "src/teachbase/final_chains/jobs.py",
    "src/teachbase/final_chains/readiness.py",
    "tests/fixtures/final_chain_samples/doc_math_sample.docx",
    "tests/fixtures/final_chain_samples/doc_english_sample.docx",
    "tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
}

VALIDATION_NOISE_PATHS = {
    "docs/reports/modularization_phase2a_test_report_20260715.json",
    "docs/reports/repository_rescue_phase1_test_report_20260715.json",
}

WORKTREE_COMPARTMENT_PATHS = {
    "docs/reports/foundation_hardening_architecture_20260804.md",
    "docs/reports/worktree_compartments_20260804.json",
    "docs/reports/worktree_compartments_20260804.md",
    "tools/build_worktree_compartment_report.py",
}

PRECLEANUP_SAFETY_PATHS = {
    "docs/reports/precleanup_archive_execution_20260804.json",
    "docs/reports/precleanup_archive_execution_20260804.md",
    "docs/reports/precleanup_deep_audit_20260804.json",
    "docs/reports/precleanup_deep_audit_20260804.md",
    "docs/reports/precleanup_post_archive_state_20260804.json",
    "docs/reports/precleanup_post_archive_state_20260804.md",
    "docs/reports/precleanup_safety_gate_20260804.json",
    "tests/test_precleanup_archive_safety.py",
    "tests/test_precleanup_post_archive_report.py",
    "tools/build_precleanup_deep_audit.py",
    "tools/build_precleanup_post_archive_report.py",
    "tools/execute_precleanup_archive.py",
    "tools/run_precleanup_safety_gate.py",
}

PRECLEANUP_ARCHIVE_SOURCE_PATHS = {
    "docs/backup_restore_runbook.md",
    "docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md",
}

MIXED_PATHS = {
    "package.json": [
        "foundation_hardening npm script",
        "final_chain_registry npm scripts",
        "precleanup_archive npm scripts",
        "precleanup_deep_audit npm script",
        "precleanup_safety npm script",
    ],
}


def is_archive_payload(path: str) -> bool:
    return path in {"_archive", "_archive/"} or path.startswith("_archive/precleanup_20260804/")


def is_docx_math_final_import(path: str) -> bool:
    return (
        path in {"prompts/", "schemas/", "docs/docx_math_pipeline_final_repro.md"}
        or path.startswith("config/docx_")
        or path.startswith("prompts/docx_")
        or path.startswith("schemas/docx_math_")
        or path.startswith("tools/docx_")
        or path
        in {
            "tools/katex_validate_math.cjs",
            "tools/mathml_to_latex_batch.cjs",
            "tools/ruby_mtef_to_mathml_batch.rb",
        }
    )


def is_doc_english_code_import(path: str) -> bool:
    return (
        path.startswith("config/english_docx_native_md/")
        or path.startswith("prompts/english_docx_")
        or path.startswith("tools/english_docx_")
    )


def is_final_chain_sample_fixture(path: str) -> bool:
    return path == "tests/fixtures/final_chain_samples/" or path.startswith("tests/fixtures/final_chain_samples/")


def git_status_porcelain() -> list[dict[str, str]]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    records: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:].replace("\\", "/")
        records.append({"status": status, "path": path})
    return records


def classify(path: str) -> tuple[str, list[str]]:
    if path in MIXED_PATHS:
        return "mixed_control_file", MIXED_PATHS[path]
    if path in FOUNDATION_PATHS:
        return "foundation_hardening", ["artifact atomicity or model retry/checkpoint hardening"]
    if path in FINAL_CHAIN_PATHS:
        return "final_chain_registry", ["protected-chain inventory, classifier, or cleanup candidate audit"]
    if path in VALIDATION_NOISE_PATHS:
        return "validation_report_refresh", ["generated by local gate execution; not architecture source"]
    if path in WORKTREE_COMPARTMENT_PATHS:
        return "worktree_compartment_report", ["review compartment documentation and report generator"]
    if path in PRECLEANUP_SAFETY_PATHS:
        return "precleanup_safety_gate", ["combined guard for protected-chain cleanup work"]
    if path in PRECLEANUP_ARCHIVE_SOURCE_PATHS:
        return "precleanup_archive_payload", ["source path moved into precleanup archive"]
    if is_archive_payload(path):
        return "precleanup_archive_payload", ["archived by precleanup archive execution"]
    if is_docx_math_final_import(path):
        return "docx_math_final_import", ["copied from verified DOCX math final-chain handoff inventory"]
    if is_doc_english_code_import(path):
        return "doc_english_code_import", ["copied from DOCX English protected code/config/prompt paths"]
    if is_final_chain_sample_fixture(path):
        return "final_chain_registry", ["repository-relative samples for protected final-chain control dry-runs"]
    return "unclassified", ["needs review before commit"]


def build_report() -> dict[str, Any]:
    records = []
    counts: dict[str, int] = {}
    for item in git_status_porcelain():
        bucket, reasons = classify(item["path"])
        counts[bucket] = counts.get(bucket, 0) + 1
        records.append({**item, "bucket": bucket, "reasons": reasons})
    return {
        "schema_version": "worktree_compartment_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "commit_recommendation": [
            "commit final_chain_registry files separately from foundation_hardening files",
            "do not include validation_report_refresh files unless intentionally updating generated reports",
            "review mixed_control_file changes line-by-line before staging",
        ],
        "counts": counts,
        "records": records,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Worktree Compartments 2026-08-04",
        "",
        "This report separates current dirty worktree changes into review compartments.",
        "All paths are relative git paths; no local absolute path is part of the reproducible input contract.",
        "",
        "## Counts",
        "",
    ]
    for bucket, count in sorted(report["counts"].items()):
        lines.append(f"- `{bucket}`: {count}")
    lines.extend(["", "## Commit Handling", ""])
    for item in report["commit_recommendation"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Records", ""])
    for item in report["records"]:
        reasons = "; ".join(item["reasons"])
        lines.append(f"- `{item['status']}` `{item['bucket']}` `{item['path']}`: {reasons}")
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
