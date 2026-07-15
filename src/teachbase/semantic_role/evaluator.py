from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from teachbase.core.run_context import generate_run_id
from teachbase.infrastructure.artifact_store import read_json, write_json
from teachbase.infrastructure.clock import utc_now_iso
from teachbase.infrastructure.hashing import sha256_file
from teachbase.semantic_role.candidate_manifest import candidate_manifest_to_cases
from teachbase.semantic_role.contracts import (
    EVALUATION_TIERS,
    GOLD_SOURCES,
    GOLD_STATUSES,
    OUTPUT_FILES,
    REAL_GOLD_SOURCES,
    REQUIRED_FIELDS,
    schema_path,
)
from teachbase.semantic_role.metrics import compute_metrics, dataset_coverage
from teachbase.semantic_role.review_pack import write_review_pack

PredictCase = Callable[[dict[str, Any], str, Path], dict[str, Any]]


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"case_file_must_be_list:{path}")
    return payload


def _read_json_yaml(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_semantic_profile_configs(workspace_root: Path) -> dict[str, Any]:
    config_dir = workspace_root / "config" / "semantic_profiles"
    required = [
        "common.yaml",
        "content_blocks.yaml",
        "document_types.yaml",
        "route_availability.yaml",
        "thresholds.yaml",
        "math.yaml",
        "english.yaml",
        "biology.yaml",
    ]
    configs: dict[str, Any] = {}
    for name in required:
        path = config_dir / name
        if not path.exists():
            raise ValueError(f"missing_semantic_profile_config:{path}")
        configs[name] = _read_json_yaml(path)
    return configs


def semantic_enums(configs: dict[str, Any]) -> dict[str, set[str]]:
    content = configs["content_blocks.yaml"]
    return {
        "semantic_roles": set((content.get("semantic_roles") or {}).keys()),
        "presentation_kinds": set((content.get("presentation_kinds") or {}).keys()),
        "dispositions": set((content.get("dispositions") or {}).keys()),
        "relation_types": set((content.get("relation_types") or {}).keys()),
        "routes": set((content.get("routes") or {}).keys()),
    }


def validate_cases(cases: list[dict[str, Any]], workspace_root: Path) -> list[str]:
    configs = load_semantic_profile_configs(workspace_root)
    enums = semantic_enums(configs)
    errors: list[str] = []
    seen: set[str] = set()
    for idx, case in enumerate(cases):
        prefix = f"case[{idx}]"
        for field in REQUIRED_FIELDS:
            if field not in case:
                errors.append(f"{prefix}.missing_field:{field}")
        case_id = str(case.get("case_id") or "")
        if not case_id:
            errors.append(f"{prefix}.empty_case_id")
        if case_id in seen:
            errors.append(f"{prefix}.duplicate_case_id:{case_id}")
        seen.add(case_id)
        tier = str(case.get("evaluation_tier") or "")
        if tier not in EVALUATION_TIERS:
            errors.append(f"{case_id}.invalid_evaluation_tier:{case.get('evaluation_tier')}")
        if case.get("gold_status") not in GOLD_STATUSES:
            errors.append(f"{case_id}.invalid_gold_status:{case.get('gold_status')}")
        if case.get("gold_source") not in GOLD_SOURCES:
            errors.append(f"{case_id}.invalid_gold_source:{case.get('gold_source')}")
        if tier == "CONTRACT_FIXTURE":
            if case.get("gold_source") != "fixture_contract":
                errors.append(f"{case_id}.contract_fixture_requires_fixture_contract_source:{case.get('gold_source')}")
            if case.get("source_artifact_ref") != "synthetic_fixture":
                errors.append(f"{case_id}.contract_fixture_requires_synthetic_artifact:{case.get('source_artifact_ref')}")
        if tier == "VERIFIED_REAL_GOLD":
            source_ref = str(case.get("source_artifact_ref") or "")
            source_path = (workspace_root / source_ref).resolve()
            expected_hash = str(case.get("source_document_sha256") or "")
            if case.get("gold_status") != "VERIFIED":
                errors.append(f"{case_id}.real_gold_requires_verified_status:{case.get('gold_status')}")
            if case.get("gold_source") not in REAL_GOLD_SOURCES:
                errors.append(f"{case_id}.real_gold_requires_human_source:{case.get('gold_source')}")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
                errors.append(f"{case_id}.real_gold_requires_sha256:{expected_hash}")
            if not source_path.exists() or not source_path.is_file():
                errors.append(f"{case_id}.real_gold_source_artifact_missing:{source_ref}")
            elif re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) and sha256_file(source_path).lower() != expected_hash.lower():
                errors.append(f"{case_id}.real_gold_source_artifact_hash_mismatch:{source_ref}")
            if not case.get("gold_evidence"):
                errors.append(f"{case_id}.real_gold_requires_audit_evidence")
            image_ref = str(case.get("source_image_ref") or "")
            if image_ref and not (workspace_root / image_ref).exists():
                errors.append(f"{case_id}.real_gold_source_image_missing:{image_ref}")
        if case.get("gold_status") == "VERIFIED":
            if not case.get("gold_evidence"):
                errors.append(f"{case_id}.verified_requires_gold_evidence")
            if case.get("expected_semantic_role") not in enums["semantic_roles"]:
                errors.append(f"{case_id}.invalid_expected_semantic_role:{case.get('expected_semantic_role')}")
            if case.get("expected_presentation_kind") not in enums["presentation_kinds"]:
                errors.append(f"{case_id}.invalid_expected_presentation_kind:{case.get('expected_presentation_kind')}")
            if case.get("expected_disposition") not in enums["dispositions"]:
                errors.append(f"{case_id}.invalid_expected_disposition:{case.get('expected_disposition')}")
            if case.get("expected_route_candidate") not in enums["routes"]:
                errors.append(f"{case_id}.invalid_expected_route_candidate:{case.get('expected_route_candidate')}")
            for rel in case.get("expected_relations") or []:
                if rel.get("type") not in enums["relation_types"]:
                    errors.append(f"{case_id}.invalid_relation_type:{rel.get('type')}")
        elif case.get("gold_source") in {"fixture_contract", "human_review", "existing_manual_audit"}:
            errors.append(f"{case_id}.non_verified_cannot_use_verified_gold_source:{case.get('gold_source')}")
    return errors


def fragment_for_case(case: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    if case.get("current_node_type") == "question":
        flags.append("possible_question_start")
    flags.extend(str(flag) for flag in (case.get("observed_fragment_flags") or []))
    if "cross-page" in (case.get("difficulty_tags") or []):
        flags.extend(["near_page_bottom", "page_top_continuation"])
    return {
        "page": (case.get("page_range") or [1])[0],
        "bbox_px": [0, 0, 100, 100],
        "role": "question_body" if case.get("current_node_type") == "question" else "content_block",
        "block_ids": [f"{case.get('case_id')}_block"],
        "flags": flags,
    }


def case_to_node(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": case["node_id"],
        "node_type": case["current_node_type"],
        "source": "semantic_role_effectiveness_eval",
        "fragments": [fragment_for_case(case)],
        "review_status": case["current_review_status"],
        "text_stub": case["source_text_stub"],
    }


def case_result(case: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    if case.get("evaluation_tier") != "VERIFIED_REAL_GOLD":
        return {
            "case_id": case["case_id"],
            "gold_status": case["gold_status"],
            "evaluation_tier": case.get("evaluation_tier"),
            "included_in_formal_metrics": False,
            "reason": "not_verified_real_gold",
        }
    if case.get("gold_status") != "VERIFIED":
        return {
            "case_id": case["case_id"],
            "gold_status": case["gold_status"],
            "evaluation_tier": case.get("evaluation_tier"),
            "included_in_formal_metrics": False,
            "reason": "gold_not_verified",
        }
    relation_expected = {(row.get("type"), row.get("target_node_id")) for row in case.get("expected_relations") or []}
    relation_predicted = {(row.get("type"), row.get("target_node_id")) for row in prediction.get("relations") or []}
    relation_ok = True if not relation_expected else relation_expected.issubset(relation_predicted)
    return {
        "case_id": case["case_id"],
        "gold_status": "VERIFIED",
        "evaluation_tier": case.get("evaluation_tier"),
        "included_in_formal_metrics": True,
        "role_ok": prediction.get("semantic_role") == case.get("expected_semantic_role"),
        "presentation_ok": prediction.get("presentation_kind") == case.get("expected_presentation_kind"),
        "disposition_ok": prediction.get("disposition") == case.get("expected_disposition"),
        "route_ok": prediction.get("route_candidate") == case.get("expected_route_candidate"),
        "relation_ok": relation_ok,
        "expected": {
            "semantic_role": case.get("expected_semantic_role"),
            "presentation_kind": case.get("expected_presentation_kind"),
            "disposition": case.get("expected_disposition"),
            "route_candidate": case.get("expected_route_candidate"),
            "needs_role_review": case.get("expected_needs_role_review"),
        },
        "prediction": {
            "semantic_role": prediction.get("semantic_role"),
            "presentation_kind": prediction.get("presentation_kind"),
            "disposition": prediction.get("disposition"),
            "route_candidate": prediction.get("route_candidate"),
            "needs_role_review": prediction.get("needs_role_review"),
            "confidence": prediction.get("confidence"),
        },
    }


def run_eval(
    *,
    cases_path: Path,
    out_root: Path,
    workspace_root: Path,
    predictor: PredictCase,
    run_id: str | None = None,
    candidate_manifest_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    run_id = run_id or generate_run_id("semantic_role_effectiveness_eval")
    out_dir = out_root / run_id
    if out_dir.exists():
        raise FileExistsError(f"effectiveness_eval_output_exists:{out_dir}")
    cases = load_cases(cases_path)
    if candidate_manifest_path is not None:
        cases.extend(candidate_manifest_to_cases(candidate_manifest_path))
    errors = validate_cases(cases, workspace_root)
    if errors:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {"status": "SEMANTIC_ROLE_EFFECTIVENESS_EVAL_NOT_READY", "errors": errors}
        write_json(out_dir / "run_summary.json", summary)
        return 2, summary

    predictions = [predictor(case, run_id, workspace_root) for case in cases]
    metrics = compute_metrics(cases, predictions)
    coverage = dataset_coverage(cases)
    case_results = [case_result(case, pred) for case, pred in zip(cases, predictions)]
    contract_fixture_cases = [case for case in cases if case.get("evaluation_tier") == "CONTRACT_FIXTURE"]
    real_gold_cases = [case for case in cases if case.get("evaluation_tier") == "VERIFIED_REAL_GOLD" and case.get("gold_status") == "VERIFIED"]
    hard_gate_passed = bool(metrics["hard_safety_gate"]["passed"])
    coverage_passed = bool(coverage["coverage_gate"]["passed"])

    if not hard_gate_passed:
        status = "SEMANTIC_ROLE_RULE_EFFECTIVENESS_BASELINE_NOT_ACCEPTABLE"
        exit_code = 10
    elif not coverage_passed:
        status = "SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED"
        exit_code = 20
    else:
        status = "SEMANTIC_ROLE_RULE_EFFECTIVENESS_BASELINE_READY"
        exit_code = 0

    manifest = {
        "schema_version": "semantic_role_effectiveness_eval_manifest_v0.1",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "cases_path": str(cases_path),
        "candidate_manifest_path": str(candidate_manifest_path) if candidate_manifest_path else "",
        "schema_path": str(schema_path(workspace_root)),
        "adapter_mode": "shadow_only",
        "business_mutation_allowed": False,
        "model_invoked": False,
        "paid_model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
        "semantic_role_logic_modified_by_this_runner": False,
        "status": status,
    }
    run_summary = {
        "status": status,
        "exit_code": exit_code,
        "run_id": run_id,
        "out_dir": str(out_dir),
        "verified_real_gold_case_count": len(real_gold_cases),
        "contract_fixture_count": len(contract_fixture_cases),
        "candidate_case_count": len(cases),
        "hard_safety_gate_passed": hard_gate_passed,
        "dataset_coverage_gate_passed": coverage_passed,
        "model_invoked": False,
        "paid_model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "evaluation_manifest.json", manifest)
    write_json(out_dir / "verified_cases_snapshot.json", real_gold_cases)
    write_json(out_dir / "real_gold_snapshot.json", real_gold_cases)
    write_json(out_dir / "contract_fixture_snapshot.json", contract_fixture_cases)
    write_json(out_dir / "predictions.json", predictions)
    write_json(out_dir / "case_level_results.json", case_results)
    write_json(
        out_dir / "metrics_summary.json",
        {
            key: value
            for key, value in metrics.items()
            if key
            not in {
                "per_role_metrics",
                "per_subject_metrics",
                "confusion_matrix",
                "critical_misroutes",
                "false_safe_cases",
                "bad_cases",
                "confidence_calibration",
                "review_capture_report",
            }
        },
    )
    write_json(out_dir / "per_role_metrics.json", metrics["per_role_metrics"])
    write_json(out_dir / "per_subject_metrics.json", metrics["per_subject_metrics"])
    write_json(out_dir / "confusion_matrix.json", metrics["confusion_matrix"])
    write_json(out_dir / "critical_misroutes.json", metrics["critical_misroutes"])
    write_json(out_dir / "false_safe_cases.json", metrics["false_safe_cases"])
    write_json(out_dir / "review_capture_report.json", metrics["review_capture_report"])
    write_json(out_dir / "confidence_calibration.json", metrics["confidence_calibration"])
    write_json(out_dir / "bad_cases.json", metrics["bad_cases"])
    write_json(out_dir / "dataset_coverage.json", coverage)
    write_review_pack(out_dir, cases, predictions, metrics["bad_cases"])
    write_json(out_dir / "run_summary.json", run_summary)
    return exit_code, run_summary
