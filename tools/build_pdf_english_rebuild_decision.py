from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_rebuild_decision_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_rebuild_decision_20260804.md"

NO_SIDE_EFFECTS = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


@dataclass(frozen=True)
class SourceRoot:
    label: str
    path: Path


def build_report(source_roots: tuple[SourceRoot, ...], *, run_regression: bool = True) -> dict[str, Any]:
    recovery_validation = _load_json("docs/reports/pdf_english_recovery_validation_20260804.json")
    source_audit = _load_json("docs/reports/pdf_english_manifest_recovery_audit_20260804.json")
    intake_validation = _load_json("docs/reports/pdf_english_recovery_intake_validation_20260804.json")
    user_zip_intake = _load_json("docs/reports/pdf_english_user_zip_intake_20260804.json")
    rebuild_smoke = _load_json("docs/reports/pdf_english_graph_first_rebuild_smoke_20260806.json")
    raw_promotion = _load_json("docs/reports/pdf_english_raw_pdf_promotion_20260806.json")
    source_code_state = [_source_code_state(source_root) for source_root in source_roots]
    cleanroom_state = _cleanroom_rebuild_state()
    regression = _run_portable_regression() if run_regression else {"status": "not_run", "exit_code": None}
    checks = [
        {
            "name": "fresh_rebuild_candidate_replaces_missing_legacy_artifacts",
            "ok": recovery_validation.get("status") == "ready_for_manifest_gate"
            and source_audit.get("source_audit_status") == "fresh_rebuild_candidate_found"
            and intake_validation.get("status") == "candidate_ready_for_quarantine_import",
            "value": {
                "validation": recovery_validation.get("status"),
                "source_audit": source_audit.get("source_audit_status"),
                "intake": intake_validation.get("status"),
            },
        },
        {
            "name": "cleanroom_v05_rebuild_scaffold_present",
            "ok": cleanroom_state["required_present"] is True,
            "value": cleanroom_state,
        },
        {
            "name": "old_local_graph_first_source_code_available_if_present",
            "ok": any(item["graph_first_source_code_present"] for item in source_code_state)
            or cleanroom_state["v05_source_present"] is True,
            "value": _public_source_states(source_code_state),
        },
        {
            "name": "portable_regression_passes_without_model_or_runtime",
            "ok": regression["status"] == "pass" and regression["execution_contract"] == NO_SIDE_EFFECTS,
            "value": regression,
        },
        {
            "name": "user_supplied_downstream_review_evidence_if_present",
            "ok": not user_zip_intake
            or (
                user_zip_intake.get("status") == "downstream_review_evidence_received"
                and user_zip_intake.get("ready_claim_allowed") is False
                and user_zip_intake.get("old_identity_claim_allowed") is False
            ),
            "value": {
                "status": user_zip_intake.get("status") if user_zip_intake else "not_provided",
                "received_branch_evidence": user_zip_intake.get("received_branch_evidence", [])
                if user_zip_intake
                else [],
                "ready_claim_allowed": user_zip_intake.get("ready_claim_allowed") if user_zip_intake else False,
            },
        },
        {
            "name": "cleanroom_graph_first_source_import_is_sealed",
            "ok": cleanroom_state["graph_first_source_file_count"] >= 23,
            "value": {
                "source": "repository_head",
                "graph_first_source_file_count": cleanroom_state["graph_first_source_file_count"],
            },
        },
        {
            "name": "fresh_rebuild_smoke_manifest_gate_passes",
            "ok": rebuild_smoke.get("status") == "pass"
            and rebuild_smoke.get("smoke_zip_testzip") is None
            and rebuild_smoke.get("ready_claim_allowed") is False,
            "value": {
                "status": rebuild_smoke.get("status"),
                "active_manifest": rebuild_smoke.get("active_manifest"),
                "smoke_zip": rebuild_smoke.get("smoke_zip"),
                "branch_page_counts": rebuild_smoke.get("branch_page_counts"),
                "ready_claim_allowed": rebuild_smoke.get("ready_claim_allowed"),
            },
        },
        {
            "name": "raw_pdf_graph_first_promotion_passes",
            "ok": raw_promotion.get("status") == "pass"
            and raw_promotion.get("java_shell_admission", {}).get("allowed") is True
            and raw_promotion.get("production_model_execution_policy", {}).get("model_calls_default_enabled") is False,
            "value": {
                "status": raw_promotion.get("status"),
                "java_shell_admission": raw_promotion.get("java_shell_admission"),
                "production_model_execution_policy": raw_promotion.get("production_model_execution_policy"),
            },
        },
    ]
    rebuild_allowed = (
        checks[0]["ok"] is True
        and
        cleanroom_state["required_present"] is True
        and checks[2]["ok"] is True
        and checks[3]["ok"] is True
        and checks[5]["ok"] is True
        and checks[6]["ok"] is True
        and checks[7]["ok"] is True
    )
    ready_claim_allowed = False
    status = "rebuild_track_allowed" if rebuild_allowed and not ready_claim_allowed else "fail"
    return {
        "schema_version": "pdf_english_rebuild_decision.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "canonical_pipeline_name": "english_text_first_graph_first",
        "status": status,
        "legacy_artifact_wait_required": False,
        "rebuild_track_allowed": rebuild_allowed,
        "ready_claim_allowed": ready_claim_allowed,
        "old_identity_claim_allowed": False,
        "completed_rebuild_evidence": [
            "cleanroom_import_of_required_graph_first_source_files",
            "user_supplied_four_branch_downstream_review_evidence",
            "new_active_manifest_generated_from_fresh_rebuild_outputs",
            "english_text_first_graph_first_manifest_check_passes",
            "new_small_pdf_smoke_package_zip_testzip_is_none",
            "raw_pdf_graph_first_promotion_passes_for_java_shell_admission",
        ]
        if checks[4]["ok"] and checks[5]["ok"] and checks[6]["ok"] and checks[7]["ok"]
        else [],
        "decision": (
            "If the 2026-07-28 graph-first smoke package is permanently unavailable, keep the old identity "
            "fail-closed and rebuild a new candidate from surviving source, fixtures, and fresh smoke evidence."
        ),
        "checks": checks,
        "required_promotion_evidence": [
            "final_chain_registry_pdf_english_readiness_updated_only_after_smoke",
            "java_worker_and_database_contract_before_unattended_production_ready_claim",
        ],
        "unsafe_actions": [
            "do_not_synthesize_old_active_manifest",
            "do_not_claim_20260728_smoke_recovered_without_artifacts",
            "do_not_mark_pdf_english_ready_from_v05_fixture_tests_only",
            "do_not_select_latest_outputs_by_timestamp",
        ],
        "execution_contract": NO_SIDE_EFFECTS,
    }


def _load_json(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _source_code_state(source_root: SourceRoot) -> dict[str, Any]:
    required_graph_first = [
        "tools/english_text_first_graph_first_manifest_check.py",
        "docs/english_text_first_graph_first_environment.md",
    ]
    graph_node_files = [
        "tools/english_text_first_full_chain_runner_v01.py",
        "tools/english_text_first_controlled_node1_vlm_transcriber.py",
        "tools/english_text_first_controlled_node1b_attribute_tagger.py",
        "tools/english_text_first_sliding_window_composer_v01.py",
        "tools/english_text_first_group_normalizer_v01.py",
        "tools/english_text_first_question_packet_builder_v01.py",
        "tools/english_text_first_question_render_normalizer_v01.py",
    ]
    required = [_path_state(source_root.path, item) for item in required_graph_first]
    graph_nodes = [_path_state(source_root.path, item) for item in graph_node_files]
    return {
        "source_label": source_root.label,
        "source_root_present": source_root.path.exists(),
        "graph_first_source_code_present": all(item["exists"] for item in required),
        "graph_node_file_count": sum(1 for item in graph_nodes if item["exists"]),
        "required_graph_first_files": required,
    }


def _path_state(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    return {
        "relative_path": relative_path,
        "exists": path.exists(),
        "kind": "directory" if path.is_dir() else "file" if path.is_file() else "missing",
    }


def _cleanroom_rebuild_state() -> dict[str, Any]:
    required = [
        "tools/english_text_first_v05_pipeline.py",
        "tools/english_text_first_sidecar_graph_v01.py",
        "config/english_text_first_v05.yaml",
        "tests/test_english_text_first_v05_pipeline.py",
        "tests/test_english_text_first_sidecar_graph_v01.py",
        "tests/fixtures/english_text_first_v05",
    ]
    states = [_path_state(ROOT, item) for item in required]
    graph_first_source_file_count = len(list((ROOT / "tools").glob("english_text_first_*.py")))
    return {
        "required_present": all(item["exists"] for item in states),
        "v05_source_present": all(item["exists"] for item in states[:3]),
        "portable_fixture_present": states[-1]["exists"],
        "required_paths": states,
        "graph_first_source_file_count": graph_first_source_file_count,
    }


def _run_portable_regression() -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_english_text_first_v05_pipeline.py",
            "tests/test_english_text_first_sidecar_graph_v01.py",
            "-q",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "exit_code": completed.returncode,
        "command": [
            "python",
            "-m",
            "pytest",
            "tests/test_english_text_first_v05_pipeline.py",
            "tests/test_english_text_first_sidecar_graph_v01.py",
            "-q",
        ],
        "output_tail": completed.stdout[-1200:],
        "execution_contract": NO_SIDE_EFFECTS,
    }


def _public_source_states(source_states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_label": item["source_label"],
            "source_root_present": item["source_root_present"],
            "graph_first_source_code_present": item["graph_first_source_code_present"],
            "graph_node_file_count": item["graph_node_file_count"],
            "required_graph_first_files": item["required_graph_first_files"],
        }
        for item in source_states
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Rebuild Decision 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Rebuild track allowed: `{str(report['rebuild_track_allowed']).lower()}`",
        f"Ready claim allowed: `{str(report['ready_claim_allowed']).lower()}`",
        "",
        "## Completed Rebuild Evidence",
        "",
    ]
    for item in report["completed_rebuild_evidence"]:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "## Checks",
            "",
        ]
    )
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Required Promotion Evidence", ""])
    for item in report["required_promotion_evidence"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Unsafe Actions", ""])
    for item in report["unsafe_actions"]:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("All source roots are recorded by label only; no local absolute path is part of the reproducible input contract.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a PDF English rebuild decision from explicit controlled roots.")
    parser.add_argument(
        "--source-root",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="Explicit source root. Repeat for additional controlled roots.",
    )
    args = parser.parse_args()
    try:
        source_roots = tuple(_parse_source_root(value) for value in args.source_root)
    except ValueError as exc:
        parser.error(str(exc))
    report = build_report(source_roots)
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "rebuild_track_allowed" else 2


def _parse_source_root(value: str) -> SourceRoot:
    label, separator, raw_path = value.partition("=")
    if not separator or not label.strip() or not raw_path.strip():
        raise ValueError("--source-root must use LABEL=PATH")
    return SourceRoot(label.strip(), Path(raw_path))


if __name__ == "__main__":
    raise SystemExit(main())
