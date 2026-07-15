from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


CONFIDENCE_BUCKETS = [
    (0.00, 0.49, "0.00-0.49"),
    (0.50, 0.69, "0.50-0.69"),
    (0.70, 0.79, "0.70-0.79"),
    (0.80, 0.89, "0.80-0.89"),
    (0.90, 1.00, "0.90-1.00"),
]


def _safe_div(num: float, den: float) -> float:
    return 0.0 if den == 0 else num / den


def _pred_role(prediction: dict[str, Any]) -> str:
    return str(prediction.get("semantic_role") or prediction.get("shadow_role") or "")


def _pred_route(prediction: dict[str, Any]) -> str:
    return str(prediction.get("route_candidate") or "")


def _pred_disposition(prediction: dict[str, Any]) -> str:
    return str(prediction.get("disposition") or prediction.get("disposition_candidate") or "")


def _is_auto_routed(prediction: dict[str, Any]) -> bool:
    route = str(prediction.get("effective_route_candidate") or prediction.get("route_candidate") or "")
    return route not in {"", "review_only", "noise"} and prediction.get("needs_role_review") is not True


def _is_verified_real_gold(case: dict[str, Any]) -> bool:
    return case.get("evaluation_tier") == "VERIFIED_REAL_GOLD" and case.get("gold_status") == "VERIFIED"


def _relations_match(expected: list[dict[str, Any]], predicted: list[dict[str, Any]]) -> bool | None:
    if not expected:
        return None
    expected_pairs = {(str(row.get("type")), str(row.get("target_node_id"))) for row in expected}
    predicted_pairs = {(str(row.get("type")), str(row.get("target_node_id"))) for row in predicted}
    return expected_pairs.issubset(predicted_pairs)


def critical_misroute_reasons(case: dict[str, Any], prediction: dict[str, Any]) -> list[str]:
    gold_role = str(case.get("expected_semantic_role") or "")
    gold_disposition = str(case.get("expected_disposition") or "")
    role = _pred_role(prediction)
    route = _pred_route(prediction)
    effective_route = str(prediction.get("effective_route_candidate") or route)
    needs_review = prediction.get("needs_role_review") is True
    reasons: list[str] = []

    if gold_role == "exercise" and role == "knowledge":
        reasons.append("exercise_to_knowledge")
    if gold_role == "exercise" and route not in {"question_splitter", "review_only"} and not needs_review:
        reasons.append("exercise_to_non_question_route_without_review")
    if gold_role == "knowledge" and route == "question_splitter":
        reasons.append("knowledge_to_question_splitter")
    if gold_role == "source_material" and route == "question_splitter":
        reasons.append("source_material_to_question_splitter")
    if gold_role == "answer_explanation" and route == "question_splitter":
        reasons.append("answer_explanation_to_question_splitter")
    if gold_role == "answer_explanation" and not prediction.get("relations") and not needs_review:
        reasons.append("answer_explanation_target_missing_without_review")
    if gold_role == "mixed" and effective_route not in {"review_only", "secondary_visual_split"} and not needs_review:
        reasons.append("mixed_auto_routed")
    if gold_disposition == "structurally_blocked" and _is_auto_routed(prediction):
        reasons.append("structurally_blocked_auto_routed")
    if gold_role == "unknown" and _is_auto_routed(prediction):
        reasons.append("unknown_auto_routed")
    return reasons


def classify_bad_case(case: dict[str, Any], prediction: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    if _pred_role(prediction) != case.get("expected_semantic_role"):
        categories.append("role_error")
    if prediction.get("presentation_kind") != case.get("expected_presentation_kind"):
        categories.append("presentation_error")
    if _pred_disposition(prediction) != case.get("expected_disposition"):
        categories.append("disposition_error")
    if _pred_route(prediction) != case.get("expected_route_candidate"):
        categories.append("route_error")
    relation_match = _relations_match(case.get("expected_relations") or [], prediction.get("relations") or [])
    if relation_match is False:
        categories.append("relation_error")
    if case.get("expected_semantic_role") == "mixed" and _pred_role(prediction) != "mixed":
        categories.append("mixed_not_detected")
    if case.get("expected_semantic_role") == "unknown" and _pred_role(prediction) != "unknown":
        categories.append("unknown_not_detected")
    if (
        (_pred_role(prediction) != case.get("expected_semantic_role") or _pred_route(prediction) != case.get("expected_route_candidate"))
        and prediction.get("needs_role_review") is not True
    ):
        categories.append("review_not_triggered")
    if case.get("gold_status") != "VERIFIED":
        categories.append("gold_evidence_insufficient")
    if not categories:
        return []
    if any(tag in case.get("difficulty_tags", []) for tag in ["cross-page", "boundary", "orphan"]):
        categories.append("boundary_error")
    if str(case.get("notes") or "").lower().find("current") >= 0:
        categories.append("current_node_type_bias")
    return sorted(set(categories))


def compute_metrics(cases: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    prediction_by_id = {str(row.get("case_id")): row for row in predictions}
    verified = [case for case in cases if _is_verified_real_gold(case)]
    contract_fixtures = [case for case in cases if case.get("evaluation_tier") == "CONTRACT_FIXTURE"]
    labels = sorted({str(case.get("expected_semantic_role")) for case in verified if case.get("expected_semantic_role")})

    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    subject_counts: dict[str, Counter[str]] = defaultdict(Counter)
    role_exact = 0
    presentation_exact = 0
    disposition_exact = 0
    route_exact = 0
    relation_total = 0
    relation_exact = 0
    wrong_cases: list[dict[str, Any]] = []
    false_safe_cases: list[dict[str, Any]] = []
    captured_wrong = 0
    safe_auto = 0
    critical_cases: list[dict[str, Any]] = []
    bad_cases: list[dict[str, Any]] = []
    confidence_bins = {
        label: {"sample_count": 0, "correct_count": 0, "error_count": 0, "false_safe_count": 0}
        for _, _, label in CONFIDENCE_BUCKETS
    }

    for case in verified:
        pred = prediction_by_id.get(str(case.get("case_id")), {})
        expected_role = str(case.get("expected_semantic_role") or "")
        predicted_role = _pred_role(pred)
        confusion[expected_role][predicted_role] += 1
        subject = str(case.get("subject") or "unknown")
        subject_counts[subject]["support"] += 1

        role_ok = predicted_role == expected_role
        presentation_ok = pred.get("presentation_kind") == case.get("expected_presentation_kind")
        disposition_ok = _pred_disposition(pred) == case.get("expected_disposition")
        route_ok = _pred_route(pred) == case.get("expected_route_candidate")
        relation_match = _relations_match(case.get("expected_relations") or [], pred.get("relations") or [])
        all_primary_ok = role_ok and presentation_ok and disposition_ok and route_ok and relation_match is not False

        role_exact += int(role_ok)
        presentation_exact += int(presentation_ok)
        disposition_exact += int(disposition_ok)
        route_exact += int(route_ok)
        subject_counts[subject]["role_correct"] += int(role_ok)
        if relation_match is not None:
            relation_total += 1
            relation_exact += int(relation_match)

        confidence = float(pred.get("confidence") or 0.0)
        for low, high, label in CONFIDENCE_BUCKETS:
            if low <= confidence <= high:
                confidence_bins[label]["sample_count"] += 1
                confidence_bins[label]["correct_count"] += int(role_ok)
                confidence_bins[label]["error_count"] += int(not role_ok)
                confidence_bins[label]["false_safe_count"] += int(not all_primary_ok and pred.get("needs_role_review") is not True)
                break

        if not all_primary_ok:
            wrong_entry = {
                "case_id": case.get("case_id"),
                "expected_semantic_role": expected_role,
                "predicted_semantic_role": predicted_role,
                "expected_route_candidate": case.get("expected_route_candidate"),
                "predicted_route_candidate": _pred_route(pred),
                "needs_role_review": bool(pred.get("needs_role_review")),
                "confidence": confidence,
            }
            wrong_cases.append(wrong_entry)
            captured_wrong += int(pred.get("needs_role_review") is True)
            if pred.get("needs_role_review") is not True:
                false_safe_cases.append(wrong_entry)
            bad_cases.append({**wrong_entry, "categories": classify_bad_case(case, pred)})

        if all_primary_ok and pred.get("needs_role_review") is not True and pred.get("hard_constraints_passed") is True:
            safe_auto += 1

        critical_reasons = critical_misroute_reasons(case, pred)
        if critical_reasons:
            critical_cases.append(
                {
                    "case_id": case.get("case_id"),
                    "reasons": critical_reasons,
                    "expected_semantic_role": expected_role,
                    "predicted_semantic_role": predicted_role,
                    "route_candidate": _pred_route(pred),
                    "needs_role_review": bool(pred.get("needs_role_review")),
                }
            )

    per_role: dict[str, Any] = {}
    f1_values: list[float] = []
    for label in labels:
        tp = confusion[label][label]
        fp = sum(rows[label] for gold, rows in confusion.items() if gold != label)
        fn = sum(count for pred_label, count in confusion[label].items() if pred_label != label)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        f1_values.append(f1)
        per_role[label] = {
            "support": sum(confusion[label].values()),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "confusion_targets": dict(sorted(confusion[label].items())),
        }

    total = len(verified)
    for row in confidence_bins.values():
        row["accuracy"] = _safe_div(row["correct_count"], row["sample_count"])

    per_subject = {
        subject: {
            "support": counts["support"],
            "role_exact_match_accuracy": _safe_div(counts["role_correct"], counts["support"]),
        }
        for subject, counts in sorted(subject_counts.items())
    }
    hard_gate = {
        "structurally_blocked_auto_route_count": sum(
            1 for case in verified if case.get("expected_disposition") == "structurally_blocked" and _is_auto_routed(prediction_by_id.get(str(case.get("case_id")), {}))
        ),
        "mixed_auto_route_count": sum(
            1 for case in verified if case.get("expected_semantic_role") == "mixed" and _is_auto_routed(prediction_by_id.get(str(case.get("case_id")), {}))
        ),
        "unknown_auto_route_count": sum(
            1 for case in verified if case.get("expected_semantic_role") == "unknown" and _is_auto_routed(prediction_by_id.get(str(case.get("case_id")), {}))
        ),
        "answer_explanation_missing_target_auto_route_count": sum(
            1
            for case in verified
            if case.get("expected_semantic_role") == "answer_explanation"
            and not prediction_by_id.get(str(case.get("case_id")), {}).get("relations")
            and _is_auto_routed(prediction_by_id.get(str(case.get("case_id")), {}))
        ),
        "critical_misroute_count": len(critical_cases),
        "false_safe_count": len(false_safe_cases),
    }
    hard_gate["passed"] = all(value == 0 for key, value in hard_gate.items() if key != "passed")

    return {
        "verified_case_count": total,
        "verified_real_gold_case_count": total,
        "contract_fixture_count": len(contract_fixtures),
        "candidate_case_count": len(cases),
        "role_exact_match_accuracy": _safe_div(role_exact, total),
        "macro_f1": _safe_div(sum(f1_values), len(f1_values)),
        "presentation_kind_accuracy": _safe_div(presentation_exact, total),
        "disposition_accuracy": _safe_div(disposition_exact, total),
        "route_candidate_accuracy": _safe_div(route_exact, total),
        "relation_accuracy": None if relation_total == 0 else _safe_div(relation_exact, relation_total),
        "critical_misroute_rate": _safe_div(len(critical_cases), total),
        "false_safe_rate": _safe_div(len(false_safe_cases), total),
        "error_capture_rate": None if not wrong_cases else _safe_div(captured_wrong, len(wrong_cases)),
        "safe_automation_coverage": _safe_div(safe_auto, total),
        "review_rate": _safe_div(sum(1 for row in predictions if row.get("needs_role_review") is True), len(predictions)),
        "per_role_metrics": per_role,
        "per_subject_metrics": per_subject,
        "confusion_matrix": {gold: dict(sorted(rows.items())) for gold, rows in sorted(confusion.items())},
        "critical_misroutes": critical_cases,
        "false_safe_cases": false_safe_cases,
        "bad_cases": bad_cases,
        "confidence_calibration": confidence_bins,
        "review_capture_report": {
            "wrong_case_count": len(wrong_cases),
            "captured_wrong_count": captured_wrong,
            "error_capture_rate": None if not wrong_cases else _safe_div(captured_wrong, len(wrong_cases)),
        },
        "hard_safety_gate": hard_gate,
    }


def dataset_coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [case for case in cases if _is_verified_real_gold(case)]
    contract_fixtures = [case for case in cases if case.get("evaluation_tier") == "CONTRACT_FIXTURE"]
    statuses = Counter(str(case.get("gold_status") or "") for case in cases)
    tiers = Counter(str(case.get("evaluation_tier") or "") for case in cases)
    verified_subjects = Counter(str(case.get("subject") or "unknown") for case in verified)
    verified_roles = Counter(str(case.get("expected_semantic_role") or "") for case in verified)
    edge_count = sum(
        1
        for case in verified
        if case.get("expected_semantic_role") in {"mixed", "unknown"}
        or case.get("expected_disposition") in {"review_required", "structurally_blocked"}
        or case.get("expected_needs_role_review") is True
    )
    relation_count = sum(1 for case in verified if case.get("expected_relations"))
    coverage_gate = {
        "verified_total_at_least_24": len(verified) >= 24,
        "verified_math_at_least_10": verified_subjects["math"] >= 10,
        "verified_english_at_least_10": verified_subjects["english"] >= 10,
        "verified_edge_at_least_4": edge_count >= 4,
        "semantic_roles_at_least_6": len([role for role, count in verified_roles.items() if role and count > 0]) >= 6,
        "has_review_path": edge_count >= 1,
        "has_relation_case": relation_count >= 1,
    }
    coverage_gate["passed"] = all(coverage_gate.values())
    return {
        "total_cases": len(cases),
        "status_counts": dict(sorted(statuses.items())),
        "evaluation_tier_counts": dict(sorted(tiers.items())),
        "verified_case_count": len(verified),
        "verified_real_gold_case_count": len(verified),
        "contract_fixture_count": len(contract_fixtures),
        "verified_subject_counts": dict(sorted(verified_subjects.items())),
        "verified_role_counts": dict(sorted(verified_roles.items())),
        "verified_edge_case_count": edge_count,
        "verified_relation_case_count": relation_count,
        "coverage_gate": coverage_gate,
    }
