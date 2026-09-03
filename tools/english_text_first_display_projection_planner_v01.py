from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text


PLANNER_VERSION = "english_display_projection_planner_v0.1_from_runtime_projection_20260727"
SCHEMA = "english_display_projection_plan_v0.1"
STIMULUS_NODE_KINDS = {"shared_stimulus", "stimulus_description", "stimulus_with_own_interaction"}


def text_of(value: Any) -> str:
    return str(value or "").strip()


def safe_id(value: Any) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))


def question_form(projection: dict[str, Any]) -> str:
    contract = projection.get("field_contract") or {}
    return text_of(contract.get("question_form")) or "unknown"


def packet_family(packet: dict[str, Any]) -> str:
    return text_of(packet.get("packet_family")).lower() or "open"


def source_field_present(packet: dict[str, Any], source_field: str, projection: dict[str, Any]) -> bool:
    question = packet.get("standard_question") or {}
    if source_field == "resolved_stimulus":
        return bool(text_of((projection.get("resolved_stimulus") or {}).get("text")))
    if source_field == "resolved_parent_context":
        stimulus_id = (projection.get("resolved_stimulus") or {}).get("semantic_node_id")
        for node in projection.get("resolved_parent_nodes") or []:
            if not isinstance(node, dict):
                continue
            if node.get("semantic_node_id") == stimulus_id:
                continue
            if text_of(node.get("text")):
                return True
        return False
    if source_field == "options":
        return bool(question.get("options"))
    if source_field == "final_markdown":
        return bool(text_of(packet.get("final_markdown")))
    return bool(text_of(question.get(source_field)))


def add_section(
    sections: list[dict[str, Any]],
    *,
    packet: dict[str, Any],
    projection: dict[str, Any],
    section_id: str,
    display_area: str,
    source_fields: list[str],
    render_as: str,
    reason: str,
) -> None:
    fields = [field for field in source_fields if source_field_present(packet, field, projection)]
    if not fields:
        return
    key = (display_area, tuple(fields))
    for existing in sections:
        if (existing.get("display_area"), tuple(existing.get("source_fields") or [])) == key:
            return
    sections.append(
        {
            "section_id": section_id,
            "display_area": display_area,
            "source_fields": fields,
            "render_as": render_as,
            "reason": reason,
        }
    )


def binding(status: str, required: bool, resolved_refs: list[str] | None = None, asset_refs: list[str] | None = None, reason: str = "") -> dict[str, Any]:
    return {
        "required": bool(required),
        "resolved_refs": resolved_refs or [],
        "asset_refs": asset_refs or [],
        "status": status,
        "reason": reason,
    }


def projection_for_packet(packet: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    group_id = packet.get("source_group_id")
    family = packet_family(packet)
    form = question_form(projection)
    asset_refs = packet.get("asset_refs") or {}
    resolved_stimulus = projection.get("resolved_stimulus") or {}
    resolved_parent_nodes = projection.get("resolved_parent_nodes") or []
    stimulus_id = resolved_stimulus.get("semantic_node_id")
    has_stimulus = bool(text_of(resolved_stimulus.get("text")))
    has_parent_context = any(
        isinstance(node, dict) and node.get("semantic_node_id") != stimulus_id and text_of(node.get("text"))
        for node in resolved_parent_nodes
    )
    visual_refs = [str(item) for item in asset_refs.get("visual_refs") or []]
    writing_refs = [str(item) for item in asset_refs.get("writing_surface_refs") or []]

    primary_refs: list[str] = []
    weak_refs: list[str] = []
    if has_stimulus:
        primary_refs.extend(str(item) for item in resolved_stimulus.get("source_group_ids") or [])
    for node in resolved_parent_nodes:
        if not isinstance(node, dict) or node.get("semantic_node_id") == stimulus_id:
            continue
        refs = [str(item) for item in node.get("source_group_ids") or []]
        if node.get("node_kind") in STIMULUS_NODE_KINDS:
            primary_refs.extend(refs)
        else:
            weak_refs.extend(refs)

    sections: list[dict[str, Any]] = []
    if has_stimulus:
        add_section(
            sections,
            packet=packet,
            projection=projection,
            section_id="shared_stimulus",
            display_area="stem_markdown",
            source_fields=["resolved_stimulus"],
            render_as="source_markdown",
            reason="resolved shared stimulus should be visible before the question",
        )
    else:
        add_section(
            sections,
            packet=packet,
            projection=projection,
            section_id="passage",
            display_area="stem_markdown",
            source_fields=["passage"],
            render_as="source_markdown",
            reason="packet passage is student-facing material",
        )

    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="question_body",
        display_area="stem_markdown",
        source_fields=["stem", "options"],
        render_as="source_markdown",
        reason="core question body belongs in the main display",
    )
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="examples",
        display_area="stem_markdown",
        source_fields=["examples"],
        render_as="source_markdown",
        reason="examples are part of the visible activity when present",
    )
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="rubric",
        display_area="analysis_markdown" if family == "writing" else "stem_markdown",
        source_fields=["rubric"],
        render_as="source_markdown",
        reason="rubric is preserved as display support rather than discarded",
    )
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="answer",
        display_area="answer_markdown",
        source_fields=["answer"],
        render_as="source_markdown",
        reason="answer field maps to answer display",
    )
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="analysis",
        display_area="analysis_markdown",
        source_fields=["analysis"],
        render_as="source_markdown",
        reason="analysis field maps to analysis display",
    )
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="translation",
        display_area="translation_markdown",
        source_fields=["translation"],
        render_as="source_markdown",
        reason="translation is supplemental and should not be mixed into stem",
    )

    context_area = "stem_markdown" if family in {"reading", "writing"} else "translation_markdown"
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="context",
        display_area=context_area,
        source_fields=["context"],
        render_as="supplement",
        reason="packet context is support material; placement is explicit to avoid field drift",
    )
    add_section(
        sections,
        packet=packet,
        projection=projection,
        section_id="parent_context",
        display_area="translation_markdown",
        source_fields=["resolved_parent_context"],
        render_as="supplement",
        reason="resolved non-stimulus parent context is weak display support, not main stem text",
    )

    display_mode = "direct_question"
    if has_stimulus:
        display_mode = "question_with_shared_stimulus"
    elif has_parent_context:
        display_mode = "question_with_parent_context"
    if visual_refs or writing_refs:
        display_mode += "_with_surface"
    if form == "material_only" or packet.get("refine_status") == "PRESERVED_NON_DIRECT":
        display_mode = "material_preservation"

    bindings = {
        "parent_context": binding(
            "BOUND" if has_parent_context else "NOT_REQUIRED",
            has_parent_context,
            weak_refs,
            [],
            "resolved non-stimulus parent context is available" if has_parent_context else "",
        ),
        "stimulus": binding(
            "BOUND" if has_stimulus else "NOT_REQUIRED",
            has_stimulus,
            primary_refs,
            [],
            "resolved shared stimulus is available" if has_stimulus else "",
        ),
        "visual_surface": binding(
            "BOUND" if visual_refs else "NOT_REQUIRED",
            bool(visual_refs),
            [],
            visual_refs,
            "visual refs are present and should be preserved as source surface" if visual_refs else "",
        ),
        "writing_surface": binding(
            "BOUND" if writing_refs else "NOT_REQUIRED",
            bool(writing_refs),
            [],
            writing_refs,
            "writing/response surface refs are present and should be preserved as source surface" if writing_refs else "",
        ),
    }

    review_requirements: list[dict[str, Any]] = []
    if (visual_refs or writing_refs) and not (asset_refs.get("page_image_refs") or packet.get("source_refs")):
        review_requirements.append(
            {
                "code": "surface_without_page_context",
                "message": "Surface refs exist but page context is not explicit; Node6b should use source page fallback and retain source surface.",
                "source_refs": visual_refs + writing_refs,
            }
        )

    return {
        "source_group_id": group_id,
        "source_packet_id": packet.get("source_packet_id"),
        "version": PLANNER_VERSION,
        "display_mode": display_mode,
        "question_form": form,
        "packet_family": family,
        "primary_material_refs": sorted(set(primary_refs)),
        "weak_context_refs": sorted(set(weak_refs)),
        "surface_refs": sorted(set(visual_refs + writing_refs)),
        "layout_sections": sections,
        "binding_decisions": bindings,
        "review_requirements": review_requirements,
    }


def render_review(plan: dict[str, Any]) -> str:
    rows = []
    for item in plan.get("display_projections") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('source_group_id') or ''))}</td>"
            f"<td>{html.escape(str(item.get('display_mode') or ''))}</td>"
            f"<td>{html.escape(', '.join(item.get('primary_material_refs') or []))}</td>"
            f"<td>{html.escape(', '.join(item.get('weak_context_refs') or []))}</td>"
            f"<td>{html.escape(', '.join(item.get('surface_refs') or []))}</td>"
            f"<td><pre>{html.escape(json.dumps(item.get('layout_sections') or [], ensure_ascii=False, indent=2))}</pre></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Display Projection Plan</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.45}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #d6dbe3;padding:8px;vertical-align:top}}
th{{background:#f3f6fa}}
pre{{white-space:pre-wrap;margin:0;font-size:12px}}
</style>
<h1>Display Projection Plan</h1>
<pre>{html.escape(json.dumps(plan.get('summary') or {{}}, ensure_ascii=False, indent=2))}</pre>
<table>
<thead><tr><th>group</th><th>mode</th><th>primary</th><th>weak</th><th>surface</th><th>layout</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    refined_payload = read_json(workspace_path(args.refined_packets_json))
    projection_payload = read_json(workspace_path(args.runtime_projection_plan_json))
    projections_by_group = {
        projection.get("source_group_id"): projection
        for projection in projection_payload.get("question_projections") or []
        if projection.get("source_group_id")
    }
    selected = set(args.group_ids or [])
    display_projections = []
    missing_projection = []
    for packet in refined_payload.get("refined_packets") or []:
        group_id = packet.get("source_group_id")
        if selected and group_id not in selected and packet.get("source_packet_id") not in selected:
            continue
        projection = projections_by_group.get(group_id)
        if not projection:
            missing_projection.append(group_id)
            projection = {"source_group_id": group_id, "field_contract": {}, "resolved_parent_nodes": [], "resolved_stimulus": {}}
        display_projections.append(projection_for_packet(packet, projection))
    summary = {
        "display_projection_count": len(display_projections),
        "missing_runtime_projection_count": len(missing_projection),
        "display_mode_counts": dict(Counter(item.get("display_mode") for item in display_projections)),
        "surface_required_count": sum(1 for item in display_projections if item.get("surface_refs")),
        "primary_material_count": sum(1 for item in display_projections if item.get("primary_material_refs")),
        "weak_context_count": sum(1 for item in display_projections if item.get("weak_context_refs")),
    }
    out_root = workspace_path(args.output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": SCHEMA,
        "planner_version": PLANNER_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": refined_payload.get("doc_id"),
        "inputs": {
            "refined_packets_json": rel_workspace(workspace_path(args.refined_packets_json)),
            "runtime_projection_plan_json": rel_workspace(workspace_path(args.runtime_projection_plan_json)),
        },
        "display_projections": display_projections,
        "summary": summary,
    }
    write_json(out_root / "display_projection_plan.json", plan)
    write_text(out_root / "display_projection_plan.html", render_review(plan))
    run_summary = {
        "schema": "english_display_projection_planner.run_summary",
        "generated_at": plan["generated_at"],
        "doc_id": plan["doc_id"],
        "planner_version": PLANNER_VERSION,
        "out_dir": rel_workspace(out_root),
        "display_projection_plan_json": rel_workspace(out_root / "display_projection_plan.json"),
        "review_html": rel_workspace(out_root / "display_projection_plan.html"),
        **summary,
    }
    write_json(out_root / "run_summary.json", run_summary)
    return run_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refined-packets-json", required=True)
    parser.add_argument("--runtime-projection-plan-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--group-ids", nargs="*", default=[])
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
