from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.document_profile_resolver import resolve_document_profile
from tools.pipeline_run_context import generate_run_id
from tools.semantic_profile_config import load_semantic_profile_configs, semantic_enums
from tools.semantic_role_adapter import run_semantic_role_adapter_shadow
from tools.semantic_role_eval_metrics import compute_metrics, dataset_coverage


DEFAULT_CASES = ROOT / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "fixture_cases.json"
SCHEMA_PATH = ROOT / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "schema.json"
REQUIRED_FIELDS = [
    "case_id",
    "subject",
    "document_type",
    "source_document_ref",
    "source_document_sha256",
    "page_range",
    "node_id",
    "source_artifact_ref",
    "source_image_ref",
    "source_text_stub",
    "current_node_type",
    "current_review_status",
    "current_review_reasons",
    "expected_semantic_role",
    "expected_presentation_kind",
    "expected_disposition",
    "expected_route_candidate",
    "expected_relations",
    "expected_needs_role_review",
    "gold_status",
    "gold_source",
    "gold_evidence",
    "difficulty_tags",
    "notes",
]
GOLD_STATUSES = {"VERIFIED", "REVIEW_REQUIRED", "UNVERIFIED"}
GOLD_SOURCES = {"existing_manual_audit", "human_review", "fixture_contract", "candidate_discovery", "unverified"}
OUTPUT_FILES = [
    "evaluation_manifest.json",
    "verified_cases_snapshot.json",
    "predictions.json",
    "case_level_results.json",
    "metrics_summary.json",
    "per_role_metrics.json",
    "per_subject_metrics.json",
    "confusion_matrix.json",
    "critical_misroutes.json",
    "false_safe_cases.json",
    "review_capture_report.json",
    "confidence_calibration.json",
    "bad_cases.json",
    "dataset_coverage.json",
    "run_summary.json",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"case_file_must_be_list:{path}")
    return payload


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    configs = load_semantic_profile_configs()
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
        if case.get("gold_status") not in GOLD_STATUSES:
            errors.append(f"{case_id}.invalid_gold_status:{case.get('gold_status')}")
        if case.get("gold_source") not in GOLD_SOURCES:
            errors.append(f"{case_id}.invalid_gold_source:{case.get('gold_source')}")
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
        else:
            if case.get("gold_source") in {"fixture_contract", "human_review", "existing_manual_audit"}:
                errors.append(f"{case_id}.non_verified_cannot_use_verified_gold_source:{case.get('gold_source')}")
    return errors


def _fragment_for_case(case: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    if case.get("current_node_type") == "question":
        flags.append("possible_question_start")
    if case.get("expected_presentation_kind") == "table":
        flags.append("table_like")
    if case.get("expected_presentation_kind") == "diagram":
        flags.append("diagram_like")
    if "cross-page" in (case.get("difficulty_tags") or []):
        flags.extend(["near_page_bottom", "page_top_continuation"])
    return {
        "page": (case.get("page_range") or [1])[0],
        "bbox_px": [0, 0, 100, 100],
        "role": "question_body" if case.get("current_node_type") == "question" else "content_block",
        "block_ids": [f"{case.get('case_id')}_block"],
        "flags": flags,
    }


def _case_to_node(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": case["node_id"],
        "node_type": case["current_node_type"],
        "source": "semantic_role_effectiveness_eval",
        "fragments": [_fragment_for_case(case)],
        "review_status": case["current_review_status"],
        "text_stub": case["source_text_stub"],
    }


def predict_case(case: dict[str, Any], run_id: str) -> dict[str, Any]:
    node = _case_to_node(case)
    semantic_nodes = {"schema": "semantic_nodes_eval_v0.1", "nodes": [node]}
    audit_report = {
        "schema": "audit_report_eval_v0.1",
        "records": [
            {
                "node_id": case["node_id"],
                "status": case["current_review_status"],
                "reasons": list(case.get("current_review_reasons") or []),
            }
        ],
    }
    profile = resolve_document_profile(
        doc_root=ROOT / "tests" / "fixtures" / "semantic_role_effectiveness_v01",
        semantic_nodes=semantic_nodes,
        audit_report=audit_report,
        doc_key=str(case.get("subject") or "unknown"),
        source_run_id=run_id,
    )
    adapter_results = run_semantic_role_adapter_shadow(
        semantic_nodes=semantic_nodes,
        audit_report=audit_report,
        document_profile=profile,
    )
    observation = dict((adapter_results.get("observations") or [{}])[0])
    return {
        "case_id": case["case_id"],
        "node_id": case["node_id"],
        "semantic_role": observation.get("shadow_role", ""),
        "presentation_kind": observation.get("presentation_kind", ""),
        "disposition": observation.get("disposition_candidate", ""),
        "route_candidate": observation.get("route_candidate", ""),
        "effective_route_candidate": observation.get("effective_route_candidate", ""),
        "confidence": observation.get("confidence", 0.0),
        "needs_role_review": bool(observation.get("needs_role_review", False)),
        "relations": observation.get("relations", []),
        "hard_constraints_passed": bool(observation.get("hard_constraints_passed", False)),
        "review_reasons": observation.get("review_reasons", []),
        "evidence": observation.get("evidence", []),
        "model_invoked": False,
        "paid_model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
    }


def discover_candidate_cases(existing_case_ids: set[str], target_total: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    roots = [ROOT / "outputs", ROOT / "out", ROOT / "docs" / "reports", ROOT / "tests" / "fixtures"]
    for root in roots:
        if not root.exists():
            continue
        for semantic_nodes_path in root.rglob("semantic_nodes.json"):
            if "semantic_role_effectiveness_eval" in semantic_nodes_path.parts:
                continue
            try:
                payload = _load_json(semantic_nodes_path)
            except Exception:
                continue
            for node in payload.get("nodes", []) or []:
                if len(candidates) + len(existing_case_ids) >= target_total:
                    return candidates
                node_id = str(node.get("node_id") or "")
                if not node_id:
                    continue
                case_id = f"candidate_{len(candidates) + 1:03d}_{node_id}"
                if case_id in existing_case_ids:
                    continue
                fragments = node.get("fragments") or []
                pages = sorted({int(fragment.get("page")) for fragment in fragments if fragment.get("page") is not None})
                text_stub = str(node.get("text_stub") or "")[:200]
                candidates.append(
                    {
                        "case_id": case_id,
                        "subject": "unknown",
                        "document_type": "unknown",
                        "source_document_ref": str(semantic_nodes_path.relative_to(ROOT)).replace("\\", "/"),
                        "source_document_sha256": "candidate_requires_manual_source_hash",
                        "page_range": pages,
                        "node_id": node_id,
                        "source_artifact_ref": str(semantic_nodes_path.relative_to(ROOT)).replace("\\", "/"),
                        "source_image_ref": "",
                        "source_text_stub": text_stub,
                        "current_node_type": str(node.get("node_type") or ""),
                        "current_review_status": str(node.get("review_status") or ""),
                        "current_review_reasons": [],
                        "expected_semantic_role": "",
                        "expected_presentation_kind": "",
                        "expected_disposition": "",
                        "expected_route_candidate": "",
                        "expected_relations": [],
                        "expected_needs_role_review": False,
                        "gold_status": "REVIEW_REQUIRED",
                        "gold_source": "candidate_discovery",
                        "gold_evidence": [],
                        "difficulty_tags": ["candidate_discovery"],
                        "notes": "Automatically discovered candidate. It is excluded from formal metrics until human Gold is verified.",
                    }
                )
    return candidates


def _case_result(case: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    if case.get("gold_status") != "VERIFIED":
        return {
            "case_id": case["case_id"],
            "gold_status": case["gold_status"],
            "included_in_formal_metrics": False,
            "reason": "gold_not_verified",
        }
    relation_expected = {(row.get("type"), row.get("target_node_id")) for row in case.get("expected_relations") or []}
    relation_predicted = {(row.get("type"), row.get("target_node_id")) for row in prediction.get("relations") or []}
    relation_ok = True if not relation_expected else relation_expected.issubset(relation_predicted)
    return {
        "case_id": case["case_id"],
        "gold_status": "VERIFIED",
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


def _write_review_pack(out_dir: Path, cases: list[dict[str, Any]], predictions: list[dict[str, Any]], bad_cases: list[dict[str, Any]]) -> None:
    review_dir = out_dir / "review_pack"
    cases_dir = review_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    pred_by_id = {str(row.get("case_id")): row for row in predictions}
    bad_ids = {str(row.get("case_id")) for row in bad_cases}
    rows: list[str] = []
    for case in sorted(cases, key=lambda row: (str(row.get("case_id")) not in bad_ids, str(row.get("case_id")))):
        pred = pred_by_id.get(str(case.get("case_id")), {})
        case_html = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>"
            + html.escape(str(case.get("case_id")))
            + "</title></head><body>"
            + f"<h1>{html.escape(str(case.get('case_id')))}</h1>"
            + "<dl>"
            + f"<dt>subject</dt><dd>{html.escape(str(case.get('subject')))}</dd>"
            + f"<dt>page_range</dt><dd>{html.escape(str(case.get('page_range')))}</dd>"
            + f"<dt>current_node_type</dt><dd>{html.escape(str(case.get('current_node_type')))}</dd>"
            + f"<dt>current_review_status</dt><dd>{html.escape(str(case.get('current_review_status')))}</dd>"
            + f"<dt>source_text_stub</dt><dd>{html.escape(str(case.get('source_text_stub')))}</dd>"
            + f"<dt>gold_role</dt><dd>{html.escape(str(case.get('expected_semantic_role')))}</dd>"
            + f"<dt>predicted_role</dt><dd>{html.escape(str(pred.get('semantic_role')))}</dd>"
            + f"<dt>gold_route</dt><dd>{html.escape(str(case.get('expected_route_candidate')))}</dd>"
            + f"<dt>predicted_route</dt><dd>{html.escape(str(pred.get('route_candidate')))}</dd>"
            + f"<dt>gold_review</dt><dd>{html.escape(str(case.get('expected_needs_role_review')))}</dd>"
            + f"<dt>predicted_review</dt><dd>{html.escape(str(pred.get('needs_role_review')))}</dd>"
            + f"<dt>confidence</dt><dd>{html.escape(str(pred.get('confidence')))}</dd>"
            + f"<dt>evidence</dt><dd>{html.escape(str(pred.get('evidence')))}</dd>"
            + "<dt>manual_decision</dt><dd>pending</dd>"
            + "</dl></body></html>"
        )
        case_path = cases_dir / f"{case.get('case_id')}.html"
        case_path.write_text(case_html, encoding="utf-8")
        rows.append(
            "<tr>"
            f"<td><a href=\"cases/{html.escape(case_path.name)}\">{html.escape(str(case.get('case_id')))}</a></td>"
            f"<td>{html.escape(str(case.get('gold_status')))}</td>"
            f"<td>{html.escape(str(case.get('subject')))}</td>"
            f"<td>{html.escape(str(case.get('expected_semantic_role')))}</td>"
            f"<td>{html.escape(str(pred.get('semantic_role')))}</td>"
            f"<td>{html.escape(str(pred.get('confidence')))}</td>"
            "</tr>"
        )
    index = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Semantic Role Review Pack</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif}td,th{border:1px solid #ddd;padding:6px}"
        "table{border-collapse:collapse;width:100%;font-size:12px}</style></head><body>"
        "<table><thead><tr><th>case</th><th>gold</th><th>subject</th><th>expected role</th><th>predicted role</th><th>confidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )
    (review_dir / "index.html").write_text(index, encoding="utf-8")
    _write_json(review_dir / "review_decisions.json", {"schema_version": "semantic_role_review_decisions_v0.1", "decisions": []})


def run_eval(*, cases_path: Path, out_root: Path, run_id: str | None = None, candidate_target: int = 40) -> tuple[int, dict[str, Any]]:
    run_id = run_id or generate_run_id("semantic_role_effectiveness_eval")
    out_dir = out_root / run_id
    if out_dir.exists():
        raise FileExistsError(f"effectiveness_eval_output_exists:{out_dir}")
    cases = load_cases(cases_path)
    cases.extend(discover_candidate_cases({str(case.get("case_id")) for case in cases}, candidate_target))
    errors = validate_cases(cases)
    if errors:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {"status": "SEMANTIC_ROLE_EFFECTIVENESS_EVAL_NOT_READY", "errors": errors}
        _write_json(out_dir / "run_summary.json", summary)
        return 2, summary

    predictions = [predict_case(case, run_id) for case in cases]
    metrics = compute_metrics(cases, predictions)
    coverage = dataset_coverage(cases)
    case_results = [_case_result(case, pred) for case, pred in zip(cases, predictions)]
    verified_cases = [case for case in cases if case.get("gold_status") == "VERIFIED"]
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
        "created_at": _now(),
        "cases_path": str(cases_path),
        "schema_path": str(SCHEMA_PATH),
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
        "verified_case_count": len(verified_cases),
        "candidate_case_count": len(cases),
        "hard_safety_gate_passed": hard_gate_passed,
        "dataset_coverage_gate_passed": coverage_passed,
        "model_invoked": False,
        "paid_model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "evaluation_manifest.json", manifest)
    _write_json(out_dir / "verified_cases_snapshot.json", verified_cases)
    _write_json(out_dir / "predictions.json", predictions)
    _write_json(out_dir / "case_level_results.json", case_results)
    _write_json(
        out_dir / "metrics_summary.json",
        {key: value for key, value in metrics.items() if key not in {"per_role_metrics", "per_subject_metrics", "confusion_matrix", "critical_misroutes", "false_safe_cases", "bad_cases", "confidence_calibration", "review_capture_report"}},
    )
    _write_json(out_dir / "per_role_metrics.json", metrics["per_role_metrics"])
    _write_json(out_dir / "per_subject_metrics.json", metrics["per_subject_metrics"])
    _write_json(out_dir / "confusion_matrix.json", metrics["confusion_matrix"])
    _write_json(out_dir / "critical_misroutes.json", metrics["critical_misroutes"])
    _write_json(out_dir / "false_safe_cases.json", metrics["false_safe_cases"])
    _write_json(out_dir / "review_capture_report.json", metrics["review_capture_report"])
    _write_json(out_dir / "confidence_calibration.json", metrics["confidence_calibration"])
    _write_json(out_dir / "bad_cases.json", metrics["bad_cases"])
    _write_json(out_dir / "dataset_coverage.json", coverage)
    _write_review_pack(out_dir, cases, predictions, metrics["bad_cases"])
    _write_json(out_dir / "run_summary.json", run_summary)
    return exit_code, run_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Semantic Role Effectiveness Evaluation v0.1.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--out-root", default="outputs/semantic_role_effectiveness_eval")
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-target", type=int, default=40)
    args = parser.parse_args()
    exit_code, summary = run_eval(
        cases_path=Path(args.cases),
        out_root=Path(args.out_root),
        run_id=args.run_id,
        candidate_target=args.candidate_target,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
