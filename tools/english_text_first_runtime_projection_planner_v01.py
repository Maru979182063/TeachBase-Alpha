from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text


PLANNER_VERSION = "english_runtime_projection_planner_v0.1_graph_first_no_model_20260717"
QUESTION_STATUSES = {"REFINED_READY", "REFINED_NEEDS_REVIEW"}
ABSORBING_RELATIONS = {"is_child_of"}
CONTEXT_RELATIONS = {"uses_context", "depends_on"}
TARGET_CONTRACT = "teacher_answered_question_bank_v0.1"


def text_of(value: Any) -> str:
    return str(value or "").strip()


def predicate(relation: dict[str, Any]) -> str:
    return text_of(relation.get("predicate") or relation.get("predicate_open_text")).lower()


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)


def question_has_core_fields(packet: dict[str, Any]) -> bool:
    contract = build_field_contract(packet=packet, parent_node_ids=[])
    return not contract["missing_required_fields"]


def warning_texts(packet: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for warning in packet.get("warnings") or []:
        if isinstance(warning, dict):
            out.append(" ".join([text_of(warning.get("code")), text_of(warning.get("message"))]).strip())
        else:
            out.append(text_of(warning))
    for code in (packet.get("status_breakdown") or {}).get("risk_codes") or []:
        out.append(text_of(code))
    return [item for item in out if item]


def has_critical_source_risk(packet: dict[str, Any]) -> bool:
    status = packet.get("status_breakdown") or {}
    if status.get("content_status") == "BROKEN" or status.get("projection_status") == "BLOCKED":
        return True
    risk_text = "\n".join(warning_texts(packet)).lower()
    critical_markers = [
        "partial_answer",
        "answer:partial",
        "incomplete_source",
        "truncated",
        "parse_failed",
        "refine_failed",
    ]
    return any(marker in risk_text for marker in critical_markers)


def infer_question_form(packet: dict[str, Any], parent_node_ids: list[str]) -> str:
    question = packet.get("standard_question") or {}
    asset_refs = packet.get("asset_refs") or {}
    if packet.get("refine_status") == "PRESERVED_NON_DIRECT":
        return "material_only"
    if asset_refs.get("writing_surface_refs") or text_of(question.get("rubric")):
        return "writing_prompt"
    if text_of(question.get("passage")) or any("stimulus" in node_id for node_id in parent_node_ids):
        if question.get("options"):
            return "reading_with_options"
        return "question_with_shared_context"
    if question.get("options"):
        return "selected_response"
    if text_of(question.get("stem")) and text_of(question.get("answer")):
        return "constructed_response"
    return "question_like"


def field_presence(question: dict[str, Any], asset_refs: dict[str, Any], parent_node_ids: list[str]) -> dict[str, bool]:
    return {
        "stem": bool(text_of(question.get("stem"))),
        "answer": bool(text_of(question.get("answer"))),
        "analysis": bool(text_of(question.get("analysis"))),
        "translation": bool(text_of(question.get("translation"))),
        "options": bool(question.get("options")),
        "passage": bool(text_of(question.get("passage"))),
        "context": bool(text_of(question.get("context"))),
        "examples": bool(text_of(question.get("examples"))),
        "rubric": bool(text_of(question.get("rubric"))),
        "visual_refs": bool(asset_refs.get("visual_refs")),
        "writing_surface_refs": bool(asset_refs.get("writing_surface_refs")),
        "parent_refs": bool(parent_node_ids),
    }


def build_field_contract(packet: dict[str, Any], parent_node_ids: list[str]) -> dict[str, Any]:
    question = packet.get("standard_question") or {}
    asset_refs = packet.get("asset_refs") or {}
    presence = field_presence(question, asset_refs, parent_node_ids)
    question_form = infer_question_form(packet, parent_node_ids)

    requirements = {
        "stem": "required",
        "answer": "required",
        "analysis": "optional",
        "translation": "optional",
        "context": "optional",
        "examples": "optional",
        "visual_refs": "optional",
        "parent_refs": "optional",
        "options": "not_applicable",
        "passage": "not_applicable",
        "rubric": "not_applicable",
        "writing_surface_refs": "not_applicable",
    }
    if question_form in {"selected_response", "reading_with_options"}:
        requirements["options"] = "required"
    if question_form in {"reading_with_options", "question_with_shared_context"}:
        requirements["passage"] = "required" if not presence["parent_refs"] else "optional"
        requirements["parent_refs"] = "required" if presence["parent_refs"] else "optional"
    if question_form == "writing_prompt":
        requirements["writing_surface_refs"] = "required"
        requirements["rubric"] = "optional"
        requirements["answer"] = "optional"
    if question_form == "material_only":
        for key in requirements:
            requirements[key] = "not_applicable"

    field_requirements = []
    missing_required = []
    missing_optional = []
    missing_not_applicable = []
    for field, requirement in requirements.items():
        present = presence[field]
        status = "present" if present else "missing"
        field_requirements.append({"field": field, "requirement": requirement, "presence": status})
        if not present and requirement == "required":
            missing_required.append(field)
        elif not present and requirement == "optional":
            missing_optional.append(field)
        elif not present and requirement == "not_applicable":
            missing_not_applicable.append(field)

    blocking_risks = []
    if has_critical_source_risk(packet):
        blocking_risks.append("critical_source_risk")

    return {
        "target_contract": TARGET_CONTRACT,
        "question_form": question_form,
        "field_requirements": field_requirements,
        "missing_required_fields": missing_required,
        "missing_optional_fields": missing_optional,
        "missing_not_applicable_fields": missing_not_applicable,
        "blocking_risks": blocking_risks,
    }


def has_closure(packet: dict[str, Any]) -> bool:
    question = packet.get("standard_question") or {}
    return bool(text_of(question.get("answer")) or text_of(question.get("analysis")))


def has_meaningful_material(packet: dict[str, Any]) -> bool:
    question = packet.get("standard_question") or {}
    material_text = "\n".join(
        text_of(question.get(key))
        for key in ["passage", "context", "examples", "rubric", "translation", "stem"]
    ).strip()
    asset_refs = packet.get("asset_refs") or {}
    return len(material_text) >= 20 or bool(asset_refs.get("visual_refs") or asset_refs.get("writing_surface_refs"))


def status_from_packet(packet: dict[str, Any], needs_parent: bool, field_contract: dict[str, Any], unsupported_reason: str = "") -> str:
    if unsupported_reason:
        return "UNSUPPORTED"
    if field_contract.get("missing_required_fields") or field_contract.get("blocking_risks"):
        return "NEEDS_REVIEW"
    if packet.get("refine_status") == "REFINED_READY":
        return "READY_REQUIRES_PARENT" if needs_parent else "READY"
    if packet.get("refine_status") == "REFINED_NEEDS_REVIEW":
        return "READY_WITH_SOURCE_WARNINGS_REQUIRES_PARENT" if needs_parent else "READY_WITH_SOURCE_WARNINGS"
    if packet.get("refine_status") == "PRESERVED_NON_DIRECT":
        return "EVIDENCE_ONLY"
    return "NEEDS_REVIEW"


def packet_brief(packet: dict[str, Any]) -> dict[str, Any]:
    question = packet.get("standard_question") or {}
    return {
        "source_packet_id": packet.get("source_packet_id"),
        "source_group_id": packet.get("source_group_id"),
        "packet_family": packet.get("packet_family"),
        "refine_status": packet.get("refine_status"),
        "stem": text_of(question.get("stem"))[:240],
        "answer_present": bool(text_of(question.get("answer"))),
        "analysis_present": bool(text_of(question.get("analysis"))),
        "passage_present": bool(text_of(question.get("passage"))),
        "visual_refs": (packet.get("asset_refs") or {}).get("visual_refs") or [],
        "writing_surface_refs": (packet.get("asset_refs") or {}).get("writing_surface_refs") or [],
    }


def connected_components(edges: list[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
        graph[b].add(a)
    seen: set[str] = set()
    components: list[list[str]] = []
    for node in sorted(graph):
        if node in seen:
            continue
        queue = deque([node])
        seen.add(node)
        component = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for nxt in sorted(graph[current]):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        if len(component) > 1:
            components.append(component)
    return components


def build_review(plan: dict[str, Any]) -> str:
    rows = []
    for item in plan["projection_report"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['source_group_id'])}</td>"
            f"<td>{html.escape(item['source_packet_id'])}</td>"
            f"<td>{html.escape(item['projection_kind'])}</td>"
            f"<td>{html.escape(item['projection_status'])}</td>"
            f"<td>{html.escape(', '.join(item.get('parent_node_ids') or []))}</td>"
            f"<td>{html.escape('; '.join(item.get('reasons') or []))}</td>"
            "</tr>"
        )
    summary = html.escape(json.dumps(plan["summary"], ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Runtime Projection Plan</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.45; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px; vertical-align: top; }}
th {{ background: #f4f4f4; }}
pre {{ background: #f7f7f7; padding: 12px; overflow: auto; }}
</style>
<h1>Runtime Projection Plan</h1>
<pre>{summary}</pre>
<table>
<thead><tr><th>group</th><th>packet</th><th>kind</th><th>status</th><th>parents</th><th>reasons</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""


def plan_projection(
    *,
    refined_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    graph_payload: dict[str, Any],
    inputs: dict[str, str],
) -> dict[str, Any]:
    doc_id = refined_payload["doc_id"]
    refined_packets = refined_payload.get("refined_packets") or []
    candidates = candidate_payload.get("packet_candidates") or []
    graph_nodes = {node["document_group_id"]: node for node in graph_payload.get("nodes") or []}
    graph_relations = graph_payload.get("relations") or []

    refined_by_group = {packet["source_group_id"]: packet for packet in refined_packets}
    candidate_by_group = {packet["source_group_id"]: packet for packet in candidates}

    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    share_edges: list[tuple[str, str]] = []
    for relation in graph_relations:
        subject = relation.get("subject_group_id")
        obj = relation.get("object_group_id")
        if not subject or not obj:
            continue
        outgoing[subject].append(relation)
        incoming[obj].append(relation)
        if predicate(relation) == "shares_stimulus":
            share_edges.append((subject, obj))

    semantic_nodes: list[dict[str, Any]] = []
    question_projections: list[dict[str, Any]] = []
    absorption_map: list[dict[str, Any]] = []
    projection_report: list[dict[str, Any]] = []
    asset_manifest: list[dict[str, Any]] = []
    parent_nodes_by_group: dict[str, str] = {}

    for component_index, component in enumerate(connected_components(share_edges), start=1):
        component_packets = [refined_by_group[group_id] for group_id in component if group_id in refined_by_group]
        passage_owner = max(
            component_packets,
            key=lambda packet: len(text_of((packet.get("standard_question") or {}).get("passage"))),
            default=None,
        )
        if not passage_owner or not text_of((passage_owner.get("standard_question") or {}).get("passage")):
            continue
        node_id = f"stimulus_{safe_id(doc_id)}_{component_index:03d}"
        semantic_nodes.append(
            {
                "semantic_node_id": node_id,
                "node_kind": "shared_stimulus",
                "source_group_ids": component,
                "source_packet_ids": [packet.get("source_packet_id") for packet in component_packets],
                "text": text_of((passage_owner.get("standard_question") or {}).get("passage")),
                "evidence_refs": (passage_owner.get("source_refs") or {}).get("passage_refs") or [],
                "asset_refs": passage_owner.get("asset_refs") or {},
                "projection_status": "READY",
                "reason": "groups are connected by shares_stimulus and at least one packet carries the shared passage text",
            }
        )
        for group_id in component:
            parent_nodes_by_group[group_id] = node_id

    for group_id, packet in refined_by_group.items():
        candidate = candidate_by_group.get(group_id) or {}
        graph_node = graph_nodes.get(group_id) or {}
        rel_out = outgoing.get(group_id, [])
        rel_in = incoming.get(group_id, [])
        out_is_child = [rel for rel in rel_out if predicate(rel) in ABSORBING_RELATIONS]
        parent_group_ids = [rel.get("object_group_id") for rel in rel_out if predicate(rel) in CONTEXT_RELATIONS | ABSORBING_RELATIONS]
        parent_node_ids = [parent_nodes_by_group[group_id]] if group_id in parent_nodes_by_group else []

        for parent_group_id in parent_group_ids:
            if parent_group_id and parent_group_id in refined_by_group:
                parent_packet = refined_by_group[parent_group_id]
                if parent_packet.get("refine_status") == "PRESERVED_NON_DIRECT":
                    parent_node_ids.append(f"material_{safe_id(doc_id)}_{parent_group_id}")
                else:
                    parent_node_ids.append(f"projection_{safe_id(parent_packet.get('source_packet_id', parent_group_id))}")
        parent_node_ids = sorted(set(parent_node_ids))

        reasons: list[str] = []
        projection_kind = ""
        projection_status = ""

        if out_is_child and packet.get("refine_status") == "PRESERVED_NON_DIRECT":
            target_group = out_is_child[0].get("object_group_id")
            target_packet = refined_by_group.get(target_group, {}).get("source_packet_id")
            absorption_map.append(
                {
                    "source_packet_id": packet.get("source_packet_id"),
                    "source_group_id": group_id,
                    "absorbed_by_group_id": target_group,
                    "absorbed_by_packet_id": target_packet,
                    "relation": "is_child_of",
                    "reason": out_is_child[0].get("reason", ""),
                    "evidence_refs": out_is_child[0].get("evidence_refs") or [],
                }
            )
            projection_kind = "absorbed_fragment"
            projection_status = "ABSORBED"
            reasons.append("PRESERVED_NON_DIRECT child fragment is absorbed by parent/owner group")
        elif packet.get("refine_status") == "PRESERVED_NON_DIRECT":
            if has_meaningful_material(packet) or rel_in:
                node_id = f"material_{safe_id(doc_id)}_{group_id}"
                semantic_nodes.append(
                    {
                        "semantic_node_id": node_id,
                        "node_kind": graph_node.get("projection_target_hint") or "material_node",
                        "source_group_ids": [group_id],
                        "source_packet_ids": [packet.get("source_packet_id")],
                        "text": packet.get("final_markdown") or "",
                        "evidence_refs": candidate.get("evidence", {}).get("source_refs") or [],
                        "asset_refs": packet.get("asset_refs") or {},
                        "projection_status": "EVIDENCE_ONLY",
                        "reason": "non-direct material is preserved for context/evidence, not projected as standalone question",
                    }
                )
                projection_kind = "material_node"
                projection_status = "EVIDENCE_ONLY"
                reasons.append("non-direct material kept as semantic/evidence node")
            else:
                projection_kind = "evidence_only"
                projection_status = "EVIDENCE_ONLY"
                reasons.append("non-direct fragment has no standalone question projection")
        elif packet.get("refine_status") in QUESTION_STATUSES:
            field_contract = build_field_contract(packet=packet, parent_node_ids=parent_node_ids)
            if field_contract.get("missing_required_fields"):
                projection_kind = "incomplete_question_candidate"
                projection_status = "NEEDS_REVIEW"
                reasons.append("question-like packet lacks required fields for target contract")
            else:
                needs_parent = bool(parent_node_ids)
                projection_kind = "child_question" if needs_parent else "standalone_question"
                projection_status = status_from_packet(packet, needs_parent, field_contract)
                if needs_parent:
                    reasons.append("question requires parent/context/stimulus node before runtime projection")
                else:
                    reasons.append("question has core fields and no required parent relation")
                if field_contract.get("missing_not_applicable_fields"):
                    reasons.append("missing not-applicable fields ignored by target contract")
                if field_contract.get("blocking_risks"):
                    reasons.append("critical source risk blocks projection")
            question_projections.append(
                {
                    "projection_id": f"projection_{safe_id(packet.get('source_packet_id', group_id))}",
                    "source_packet_id": packet.get("source_packet_id"),
                    "source_group_id": group_id,
                    "projection_kind": projection_kind,
                    "projection_status": projection_status,
                    "parent_node_ids": parent_node_ids,
                    "standard_question": packet.get("standard_question") or {},
                    "source_refs": packet.get("source_refs") or {},
                    "asset_refs": packet.get("asset_refs") or {},
                    "status_breakdown": packet.get("status_breakdown") or {},
                    "field_contract": build_field_contract(packet=packet, parent_node_ids=parent_node_ids),
                    "reasons": reasons,
                }
            )
        else:
            projection_kind = "unsupported_status"
            projection_status = "UNSUPPORTED"
            reasons.append(f"unsupported refine_status: {packet.get('refine_status')}")

        projection_report.append(
            {
                "source_packet_id": packet.get("source_packet_id"),
                "source_group_id": group_id,
                "packet_brief": packet_brief(packet),
                "graph_hint": {
                    "projection_target_hint": graph_node.get("projection_target_hint"),
                    "project_directly_to_question": graph_node.get("project_directly_to_question"),
                    "semantic_role": graph_node.get("semantic_role"),
                },
                "projection_kind": projection_kind,
                "projection_status": projection_status,
                "parent_group_ids": sorted(set(parent_group_id for parent_group_id in parent_group_ids if parent_group_id)),
                "parent_node_ids": parent_node_ids,
                "field_contract": build_field_contract(packet=packet, parent_node_ids=parent_node_ids),
                "incoming_relation_count": len(rel_in),
                "outgoing_relation_count": len(rel_out),
                "reasons": reasons,
            }
        )

        asset_refs = packet.get("asset_refs") or {}
        for ref_kind in ["visual_refs", "writing_surface_refs"]:
            for ref in asset_refs.get(ref_kind) or []:
                asset_manifest.append(
                    {
                        "asset_ref": ref,
                        "asset_kind": ref_kind,
                        "source_packet_id": packet.get("source_packet_id"),
                        "source_group_id": group_id,
                        "projection_usage": projection_kind,
                    }
                )
        for page_image in asset_refs.get("page_image_refs") or []:
            asset_manifest.append(
                {
                    "asset_ref": page_image.get("path"),
                    "asset_kind": "page_image",
                    "source_packet_id": packet.get("source_packet_id"),
                    "source_group_id": group_id,
                    "page": page_image.get("page"),
                    "exists": page_image.get("exists"),
                    "projection_usage": projection_kind,
                }
            )

    summary = {
        "packet_count": len(refined_packets),
        "semantic_node_count": len(semantic_nodes),
        "question_projection_count": len(question_projections),
        "absorption_count": len(absorption_map),
        "asset_manifest_count": len(asset_manifest),
        "by_projection_status": dict(sorted({status: sum(1 for item in projection_report if item["projection_status"] == status) for status in {item["projection_status"] for item in projection_report}}.items())),
        "by_projection_kind": dict(sorted({kind: sum(1 for item in projection_report if item["projection_kind"] == kind) for kind in {item["projection_kind"] for item in projection_report}}.items())),
        "runtime_payload_built": False,
        "database_write_enabled": False,
    }
    return {
        "schema": "english_runtime_projection_plan_v0.1",
        "doc_id": doc_id,
        "planner_version": PLANNER_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": inputs,
        "semantic_nodes": semantic_nodes,
        "question_projections": question_projections,
        "absorption_map": absorption_map,
        "asset_manifest": asset_manifest,
        "projection_report": projection_report,
        "summary": summary,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    refined_path = workspace_path(args.refined_packets_json)
    candidate_path = workspace_path(args.packet_candidates_json)
    graph_path = workspace_path(args.group_projection_graph_json)
    refined_payload = read_json(refined_path)
    candidate_payload = read_json(candidate_path)
    graph_payload = read_json(graph_path)
    out_root = workspace_path(args.output_root) / args.run_id
    inputs = {
        "refined_packets_json": rel_workspace(refined_path),
        "packet_candidates_json": rel_workspace(candidate_path),
        "group_projection_graph_json": rel_workspace(graph_path),
    }
    plan = plan_projection(
        refined_payload=refined_payload,
        candidate_payload=candidate_payload,
        graph_payload=graph_payload,
        inputs=inputs,
    )
    summary = {
        "schema": "english_runtime_projection_planner.run_summary",
        "generated_at": plan["generated_at"],
        "doc_id": plan["doc_id"],
        "planner_version": PLANNER_VERSION,
        "out_dir": rel_workspace(out_root),
        "runtime_payload_built": False,
        "database_write_enabled": False,
        **plan["summary"],
        "projection_plan_json": rel_workspace(out_root / "runtime_projection_plan.json"),
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "runtime_projection_plan.json", plan)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", build_review(plan))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refined-packets-json", required=True)
    parser.add_argument("--packet-candidates-json", required=True)
    parser.add_argument("--group-projection-graph-json", required=True)
    parser.add_argument("--output-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/controlled_runs")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
