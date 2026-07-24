from __future__ import annotations

import html
from typing import Any

from tools.semantic_profile_config import (
    default_route_for_role,
    eligible_for_question_bank,
    load_semantic_profile_configs,
    route_availability,
    semantic_enums,
    threshold_version,
)


ADAPTER_VERSION = "semantic_role_adapter_shadow.v0.2"


def _audit_map(audit_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(record.get("node_id", "")): record for record in audit_report.get("records", []) if record.get("node_id")}


def _presentation_kind(text: str, flags: list[str]) -> str:
    if "table_like" in flags or "|" in text or "□" in text:
        return "table"
    if "diagram_like" in flags or any(token in text for token in ["如图", "图", "函数图象", "几何"]):
        return "diagram"
    if any(token in text for token in ["\\frac", "\\overrightarrow", "∠", "⊥", "∥"]):
        return "formula_heavy"
    return "text"


def _infer_semantic_role(node: dict[str, Any], audit: dict[str, Any], text: str) -> tuple[str, str, float, list[dict[str, Any]]]:
    lower = text.lower()
    flags = [flag for fragment in node.get("fragments", []) or [] for flag in fragment.get("flags", []) or []]
    fragment_roles = [str(fragment.get("role") or "") for fragment in node.get("fragments", []) or []]
    evidence: list[dict[str, Any]] = []
    if node.get("node_type") == "knowledge_block" or "knowledge_like" in flags or "possible_section_heading" in flags:
        evidence.append({"type": "existing_assignment", "detail": "knowledge_like_or_section", "weight": 0.50})
        return "knowledge", "text", 0.76, evidence
    if audit.get("status") == "QUARANTINED" or node.get("review_status") == "QUARANTINED":
        evidence.append({"type": "audit_signal", "detail": "quarantined", "weight": 1.0})
        return "unknown", "unknown", 0.35, evidence
    if any(token in text for token in ["【答案】", "答案", "【解析】", "解析", "【详解】", "翻译"]):
        if "question_body" not in fragment_roles:
            evidence.append({"type": "content_function", "detail": "answer_or_analysis_without_stem", "weight": 0.80})
            return "answer_explanation", "text", 0.74, evidence
    if "passage" in lower or any(token in text for token in ["阅读", "文章", "材料", "实验材料"]):
        evidence.append({"type": "content_function", "detail": "source_material_marker", "weight": 0.60})
        return "source_material", "text", 0.72, evidence
    if any(token in text for token in ["例题", "【例", "解：", "分析", "详解"]) and any(token in text for token in ["答案", "解析", "解得"]):
        evidence.append({"type": "content_function", "detail": "worked_example_like", "weight": 0.65})
        return "worked_example", _presentation_kind(text, flags), 0.78, evidence
    if node.get("node_type") == "question" or "possible_question_start" in flags:
        evidence.append({"type": "existing_assignment", "detail": "question_node_or_start_flag", "weight": 0.65})
        return "exercise", _presentation_kind(text, flags), 0.82, evidence
    evidence.append({"type": "fallback", "detail": "no_strong_role_signal", "weight": 0.20})
    return "unknown", _presentation_kind(text, flags), 0.40, evidence


def _relations_for(node: dict[str, Any], role: str, nodes: list[dict[str, Any]], idx: int, confidence: float) -> list[dict[str, Any]]:
    if role != "answer_explanation":
        return []
    for prev in reversed(nodes[:idx]):
        if prev.get("node_type") == "question":
            return [
                {
                    "type": "explains",
                    "source_node_id": node.get("node_id", ""),
                    "target_node_id": prev.get("node_id", ""),
                    "confidence": max(0.0, min(confidence, 0.72)),
                    "evidence": [{"type": "context_relation", "detail": "nearest_previous_question"}],
                }
            ]
    return []


def _finalize_observation(observation: dict[str, Any], configs: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    enums = semantic_enums(configs)
    if observation.get("shadow_role") not in enums["semantic_roles"]:
        observation["shadow_role"] = "unknown"
        observation["disposition_candidate"] = "review_required"
        observation["needs_role_review"] = True
    if observation.get("presentation_kind") not in enums["presentation_kinds"]:
        observation["presentation_kind"] = "unknown"
    if observation.get("disposition_candidate") not in enums["dispositions"]:
        observation["disposition_candidate"] = "review_required"
    if observation.get("route_candidate") not in enums["routes"]:
        observation["route_candidate"] = "review_only"
    observation["route_availability"] = route_availability(configs, str(observation.get("route_candidate") or "review_only"))
    observation["effective_route_candidate"] = (
        observation.get("route_candidate") if observation["route_availability"] == "implemented" else "review_only"
    )
    observation["threshold_version"] = observation.get("threshold_version") or threshold_version(configs)
    observation["hard_constraints_passed"] = True

    audit_status = audit.get("status") or observation.get("current_review_status")
    if audit_status and audit_status != "AUDITED_READY":
        observation["disposition_candidate"] = "structurally_blocked"
        observation["effective_route_candidate"] = "review_only"
        observation["hard_constraints_passed"] = False
        observation["needs_role_review"] = True
    if observation.get("shadow_role") == "mixed":
        observation["requires_secondary_split"] = True
        observation["disposition_candidate"] = "review_required"
        observation["effective_route_candidate"] = "review_only"
        observation["hard_constraints_passed"] = False
        observation["needs_role_review"] = True
    if observation.get("shadow_role") == "answer_explanation":
        valid_relation = False
        for rel in observation.get("relations", []) or []:
            if rel.get("type") in {"answers", "explains"} and rel.get("target_node_id") and float(rel.get("confidence") or 0) >= 0.88:
                valid_relation = True
        if not valid_relation:
            observation["disposition_candidate"] = "review_required"
            observation["effective_route_candidate"] = "review_only"
            observation["hard_constraints_passed"] = False
            observation["needs_role_review"] = True
    if observation.get("shadow_role") in {"unknown", "mixed"} or observation.get("disposition_candidate") != "processable":
        observation["needs_role_review"] = True
    observation["eligible_for_question_bank"] = eligible_for_question_bank(configs, str(observation.get("shadow_role") or "unknown"))
    return observation


def run_semantic_role_adapter_shadow(
    *,
    semantic_nodes: dict[str, Any],
    audit_report: dict[str, Any],
    document_profile: dict[str, Any],
) -> dict[str, Any]:
    """Produce deterministic, meaningful shadow-only role observations without changing source nodes."""
    configs = load_semantic_profile_configs()
    audits = _audit_map(audit_report)
    nodes = list(semantic_nodes.get("nodes", []) or [])
    observations = []
    for idx, node in enumerate(nodes):
        node_id = str(node.get("node_id") or "")
        current_type = str(node.get("node_type") or "")
        current_status = str(node.get("review_status") or "")
        audit = audits.get(node_id, {})
        text = str(node.get("text_stub", "") or "")
        role, presentation, confidence, evidence = _infer_semantic_role(node, audit, text)
        route = default_route_for_role(configs, role)
        observation = {
            "adapter_version": ADAPTER_VERSION,
            "adapter_mode": "shadow_only",
            "business_mutation_allowed": False,
            "node_id": node_id,
            "current_node_type": current_type,
            "current_review_status": current_status,
            "shadow_role": role,
            "presentation_kind": presentation,
            "disposition_candidate": "processable",
            "route_candidate": route,
            "effective_route_candidate": route,
            "confidence": confidence,
            "confidence_source": "rule_fallback",
            "review_reasons": list(audit.get("reasons", []) or []),
            "evidence": evidence,
            "relations": _relations_for(node, role, nodes, idx, confidence),
            "requires_secondary_split": role == "mixed",
            "preserve_as_handout_content": True,
            "eligible_for_question_bank": eligible_for_question_bank(configs, role),
            "needs_role_review": confidence < 0.80 or role in {"unknown", "mixed"},
            "shadow_decision": "observe_only",
            "would_mutate_pipeline": False,
            "prompt_version": "no_prompt_shadow_rules_v0.2",
            "config_version": document_profile.get("config_version", "semantic_profiles_v0.2"),
        }
        observations.append(_finalize_observation(observation, configs, audit))
    return {
        "schema_version": "semantic_role_adapter_results_shadow.v0.2",
        "adapter_version": ADAPTER_VERSION,
        "adapter_mode": "shadow_only",
        "business_mutation_allowed": False,
        "model_invoked": False,
        "paid_model_invoked": False,
        "prompt_content_changed": False,
        "document_profile_node_count": document_profile.get("node_count", 0),
        "observations": observations,
    }


def _diff_reason(node: dict[str, Any], observation: dict[str, Any]) -> str:
    old_type = str(node.get("node_type", ""))
    role = str(observation.get("shadow_role", ""))
    if old_type == "question" and role not in {"exercise", "worked_example", "question_group", "unknown"}:
        return "old_question_type_role_changed"
    if "knowledge" in old_type and role not in {"knowledge", "method_or_strategy", "unknown"}:
        return "old_knowledge_type_role_changed"
    if observation.get("effective_route_candidate") != observation.get("route_candidate"):
        return "route_fallback_by_availability_or_constraints"
    if old_type != role:
        return "type_role_semantic_layer_diff"
    return "no_major_diff"


def build_adapter_diff_report(*, semantic_nodes: dict[str, Any], adapter_results: dict[str, Any]) -> dict[str, Any]:
    by_node = {str(row.get("node_id")): row for row in adapter_results.get("observations", [])}
    rows = []
    counts = {
        "node_type_shadow_role_diffs": 0,
        "route_fallbacks": 0,
        "needs_manual_review": 0,
        "answer_target_missing": 0,
    }
    for node in semantic_nodes.get("nodes", []) or []:
        node_id = str(node.get("node_id") or "")
        row = by_node.get(node_id, {})
        current_type = str(node.get("node_type") or "")
        shadow_role = str(row.get("shadow_role") or "")
        if current_type != shadow_role:
            counts["node_type_shadow_role_diffs"] += 1
        if row.get("effective_route_candidate") != row.get("route_candidate"):
            counts["route_fallbacks"] += 1
        if row.get("needs_role_review"):
            counts["needs_manual_review"] += 1
        if shadow_role == "answer_explanation" and not any(rel.get("target_node_id") for rel in row.get("relations", []) or []):
            counts["answer_target_missing"] += 1
        rows.append(
            {
                "node_id": node_id,
                "current_node_type": current_type,
                "current_review_status": node.get("review_status", ""),
                "shadow_role": shadow_role,
                "presentation_kind": row.get("presentation_kind", ""),
                "disposition_candidate": row.get("disposition_candidate", ""),
                "route_candidate": row.get("route_candidate", ""),
                "route_availability": row.get("route_availability", ""),
                "effective_route_candidate": row.get("effective_route_candidate", ""),
                "confidence": row.get("confidence", 0),
                "hard_constraints_passed": row.get("hard_constraints_passed", False),
                "relations": row.get("relations", []),
                "review_reasons": row.get("review_reasons", []),
                "needs_role_review": bool(row.get("needs_role_review", False)),
                "business_mutation_allowed": False,
                "diff_reason": _diff_reason(node, row),
            }
        )
    return {
        "schema_version": "semantic_role_adapter_diff_report_shadow.v0.2",
        "adapter_mode": "shadow_only",
        "business_mutation_allowed": False,
        "diff_count": counts["node_type_shadow_role_diffs"],
        "metrics": counts,
        "rows": rows,
        "diffs": [row for row in rows if row["current_node_type"] != row["shadow_role"]],
    }


def build_review_samples_html(adapter_results: dict[str, Any], diff_report: dict[str, Any], max_rows: int = 80) -> str:
    by_node = {str(row.get("node_id")): row for row in adapter_results.get("observations", [])}
    rows = []
    for row in diff_report.get("rows", [])[:max_rows]:
        obs = by_node.get(str(row.get("node_id")), {})
        evidence = html.escape(str(obs.get("evidence", [])))
        reasons = ", ".join(html.escape(str(reason)) for reason in row.get("review_reasons", []))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('node_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('current_node_type', '')))}</td>"
            f"<td>{html.escape(str(row.get('shadow_role', '')))}</td>"
            f"<td>{html.escape(str(row.get('route_candidate', '')))}</td>"
            f"<td>{html.escape(str(row.get('disposition_candidate', '')))}</td>"
            f"<td>{html.escape(str(row.get('confidence', '')))}</td>"
            f"<td>{html.escape(str(row.get('diff_reason', '')))}</td>"
            f"<td>{reasons}</td>"
            f"<td>{evidence}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Semantic Role Shadow Review Samples</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}"
        "table{border-collapse:collapse;width:100%;font-size:12px}</style></head>"
        "<body><table><thead><tr><th>node_id</th><th>current</th><th>shadow</th><th>route</th><th>disposition</th>"
        "<th>confidence</th><th>diff</th><th>review reasons</th><th>evidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )
