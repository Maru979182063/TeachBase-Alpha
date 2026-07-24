from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from jsonschema import Draft202012Validator

from english_text_first_normalizer.common import extract_json, read_json, rel_workspace, render_template, workspace_path, write_json, write_text
from english_text_first_normalizer.evidence_text import (
    blank_run_count,
    markdown_table_surface_present,
    unsupported_lines,
)


PROMPT_VERSION = "english_question_render_normalizer_v1.3_clean_layout_visual_boundary_20260723"
RENDER_PLAN_SCHEMA_PATH = "schemas/render_instruction_plan.schema.json"
RENDER_PLAN_SCHEMA = "render_instruction_plan_v0.1"
RENDER_PLAN_VERSION = "english_render_instruction_planner_v0.1_program_renderer_20260723"
DISPLAY_TARGET_FIELDS = {"stem_markdown", "answer_markdown", "analysis_markdown", "translation_markdown"}
DISPLAY_SOURCE_FIELDS = {
    "final_markdown",
    "passage",
    "context",
    "stem",
    "options",
    "answer",
    "analysis",
    "translation",
    "examples",
    "rubric",
    "resolved_stimulus",
}
RENDER_PLAN_OPS = {
    "copy_field",
    "merge_fields",
    "move_field",
    "attach_parent_context",
    "attach_stimulus",
    "attach_visual_surface",
    "attach_writing_surface",
    "render_table_from_existing_rows",
    "preserve_material_only",
    "mark_review_required",
}
LAYOUT_RENDER_AS = {"source_markdown", "paragraph", "list", "table", "supplement", "surface"}
VISUAL_RECOVERY_RENDER_AS = LAYOUT_RENDER_AS


ADMISSION_MODES = {
    "READY_DIRECT",
    "READY_DIRECT_WITH_SURFACE",
    "READY_WITH_PARENT_CONTEXT",
    "READY_AS_EXAMPLE_CHILD",
    "READY_WITH_VISUAL_PARENT",
    "FIELD_REPAIR_THEN_READY",
    "FIELD_REPAIR_OR_SOURCE_REVIEW",
    "SPLIT_OR_PARENT_CLUSTER_REQUIRED",
    "DO_NOT_IMPORT_DUPLICATE_COMPOSITE",
    "NOT_RENDERABLE",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))


def page_image_paths(packet: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in (packet.get("asset_refs") or {}).get("page_image_refs") or []:
        path = workspace_path(item.get("path") or "")
        if path.exists() and path not in paths:
            paths.append(path)
    return paths[:3]


def with_projection_context(packet: dict[str, Any], projection: dict[str, Any] | None) -> dict[str, Any]:
    if not projection:
        return packet
    merged = json.loads(json.dumps(packet, ensure_ascii=False))
    resolved_stimulus = projection.get("resolved_stimulus") or {}
    resolved_parent_nodes = projection.get("resolved_parent_nodes") or []
    selected_parent_nodes = resolved_parent_nodes
    if resolved_stimulus.get("semantic_node_id"):
        selected_parent_nodes = [
            node for node in resolved_parent_nodes
            if node.get("semantic_node_id") == resolved_stimulus.get("semantic_node_id")
        ] or resolved_parent_nodes
    merged["projection_context"] = {
        "projection_id": projection.get("projection_id"),
        "projection_status": projection.get("projection_status"),
        "parent_node_ids": projection.get("parent_node_ids") or [],
        "resolved_parent_nodes": selected_parent_nodes,
        "resolved_stimulus": resolved_stimulus,
        "field_contract": projection.get("field_contract") or {},
    }
    if str(resolved_stimulus.get("text") or "").strip():
        question = merged.setdefault("standard_question", {})
        question.setdefault("passage", resolved_stimulus["text"])
    return merged


def build_input_payload(packet: dict[str, Any]) -> dict[str, Any]:
    asset_refs = packet.get("asset_refs") or {}
    return {
        "source_packet_id": packet.get("source_packet_id"),
        "source_group_id": packet.get("source_group_id"),
        "packet_family": packet.get("packet_family"),
        "question_type": packet.get("question_type"),
        "refine_status": packet.get("refine_status"),
        "projection_context": packet.get("projection_context") or {},
        "standard_question": packet.get("standard_question") or {},
        "final_markdown": packet.get("final_markdown") or "",
        "source_refs": packet.get("source_refs") or {},
        "asset_refs": asset_refs,
        "source_visual_profile": {
            "visual_refs_present": bool(asset_refs.get("visual_refs")),
            "visual_refs": asset_refs.get("visual_refs") or [],
            "writing_surface_refs_present": bool(asset_refs.get("writing_surface_refs")),
            "writing_surface_refs": asset_refs.get("writing_surface_refs") or [],
        },
        "warnings": packet.get("warnings") or [],
        "status_breakdown": packet.get("status_breakdown") or {},
    }


def load_system_prompt_for_packet(node: dict[str, Any], packet: dict[str, Any]) -> str:
    family = str(packet.get("packet_family") or "open").strip().lower()
    prompt_paths = node.get("family_system_prompt_paths") if isinstance(node.get("family_system_prompt_paths"), dict) else {}
    selected_path = prompt_paths.get(family) or node.get("system_prompt_path")
    system_prompt = workspace_path(selected_path).read_text(encoding="utf-8")
    common_path = node.get("common_system_prompt_path")
    if common_path and "{{common_prompt}}" in system_prompt:
        common_prompt = workspace_path(common_path).read_text(encoding="utf-8")
        system_prompt = system_prompt.replace("{{common_prompt}}", common_prompt)
    return system_prompt


def warning_codes(packet: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for warning in packet.get("warnings") or []:
        if isinstance(warning, dict) and warning.get("code"):
            codes.add(str(warning["code"]))
    return codes


def field_requirement(packet: dict[str, Any], field_name: str) -> str:
    contract = ((packet.get("projection_context") or {}).get("field_contract") or {})
    for item in contract.get("field_requirements") or []:
        if isinstance(item, dict) and item.get("field") == field_name:
            return str(item.get("requirement") or "")
    return ""


VISUAL_STRUCTURE_RENDERING_BLOCKS = {
    "diagram",
    "diagram_outline",
    "flowchart",
    "flowchart_outline",
    "mindmap",
    "mind_map",
    "mindmap_outline",
    "mind_map_outline",
    "structured_visual",
    "visual_knowledge_structure",
}


def has_visual_structure_block(rendering_blocks: list[Any]) -> bool:
    """Use only structured rendering labels, not source-text keyword matching."""
    normalized = {str(item).strip().lower() for item in rendering_blocks if str(item).strip()}
    return bool(normalized & VISUAL_STRUCTURE_RENDERING_BLOCKS)


def multiple_choice_label_counts(markdown: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.strip()
        if len(line) < 3:
            continue
        label = line[0].upper()
        if label in {"A", "B", "C", "D", "E", "F"} and line[1] in {".", "．", "、"}:
            counts[label] = counts.get(label, 0) + 1
    return counts


def is_option_line(text: str) -> bool:
    line = str(text or "").strip()
    return len(line) >= 3 and line[0].upper() in {"A", "B", "C", "D", "E", "F"} and line[1] in {".", "．", "、"}


def strip_option_lines(markdown: str) -> str:
    lines = []
    for raw_line in str(markdown or "").splitlines():
        if not is_option_line(raw_line):
            lines.append(raw_line)
    return "\n".join(lines).strip()


def source_option_lines(packet: dict[str, Any]) -> list[str]:
    question = packet.get("standard_question") or {}
    options = question.get("options") if isinstance(question.get("options"), list) else []
    lines = []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip().upper()
        text = str(option.get("text") or "").strip()
        if label and text:
            lines.append(f"{label}. {text}")
    return lines


def item_option_lines(record: dict[str, Any]) -> list[str]:
    display = record.get("display_question") or {}
    lines = []
    seen = set()
    for item in display.get("items") or []:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if is_option_line(prompt):
            label = prompt[0].upper()
            if label not in seen:
                lines.append(prompt)
                seen.add(label)
    return lines


def options_need_repair(stem_markdown: str, option_lines: list[str]) -> bool:
    if not option_lines:
        return False
    counts = multiple_choice_label_counts(stem_markdown)
    for option_line in option_lines:
        label = option_line[0].upper()
        text = option_line[3:].strip()
        if counts.get(label, 0) != 1 or (text and text not in stem_markdown):
            return True
    return False


def append_canonical_options(stem_markdown: str, option_lines: list[str]) -> str:
    stem_without_options = strip_option_lines(stem_markdown)
    option_block = "### 选项\n" + "\n".join(option_lines)
    return (stem_without_options + "\n\n" + option_block).strip()


def postprocess_rendered_record(record: dict[str, Any], packet: dict[str, Any]) -> None:
    """Deterministically repair fields that have structured source evidence."""
    display = record.get("display_question") or {}
    actions = record.setdefault("normalization_actions", [])
    if not isinstance(actions, list):
        actions = []
        record["normalization_actions"] = actions

    stem_markdown = str(display.get("stem_markdown") or "")
    option_lines = source_option_lines(packet) or item_option_lines(record)
    if options_need_repair(stem_markdown, option_lines):
        display["stem_markdown"] = append_canonical_options(stem_markdown, option_lines)
        actions.append("postprocess:canonical_options_visible_in_stem")

    source_answer = str((packet.get("standard_question") or {}).get("answer") or "").strip()
    current_answer = str(display.get("answer_markdown") or "").strip()
    reset_to_source_answer = (
        bool(source_answer)
        and bool(current_answer)
        and current_answer != source_answer
        and (
            len(source_answer) <= 120
            or ("源材料" in current_answer and "源材料" not in source_answer)
        )
    )
    if reset_to_source_answer:
        display["answer_markdown"] = source_answer
        record["normalization_actions"] = [
            action for action in actions
            if "missing definition" not in str(action).lower()
            and "source warning" not in str(action).lower()
            and "source note" not in str(action).lower()
            and "源材料" not in str(action)
        ]
        actions = record["normalization_actions"]
        actions.append("postprocess:answer_markdown_reset_to_source_answer")


def derive_admission_profile(packet: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Compute target-import posture from already available contracts.

    This is deliberately based on upstream statuses, warning codes, parent refs,
    and asset refs. It does not inspect content text or add lesson-type rules.
    """
    projection_context = packet.get("projection_context") or {}
    parent_node_ids = projection_context.get("parent_node_ids") or []
    field_contract = projection_context.get("field_contract") or {}
    asset_refs = packet.get("asset_refs") or {}
    codes = warning_codes(packet)
    display = record.get("display_question") or {}
    rendering_blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
    packet_family = str(packet.get("packet_family") or "")
    refine_status = str(packet.get("refine_status") or "")
    projection_status = str(projection_context.get("projection_status") or "")
    question_type = str(packet.get("question_type") or "")
    project_directly = projection_status not in {"PRESERVED_NON_DIRECT", "UNSUPPORTED"}
    model_profile = record.get("admission_profile") if isinstance(record.get("admission_profile"), dict) else {}
    model_mode = str(model_profile.get("admission_mode") or "")

    source_review_required = "question_answer_number_mismatch" in codes
    split_required = (
        refine_status == "PRESERVED_NON_DIRECT"
        or "non_direct_preserved" in codes
        or "upstream_preserved_non_direct_refined" in codes
    )
    parent_required = bool(parent_node_ids) or "REQUIRES_PARENT" in projection_status
    surface_required = bool(asset_refs.get("writing_surface_refs"))
    model_visual_parent_required = bool(model_profile.get("visual_parent_required"))
    structured_visual_rendered = has_visual_structure_block(rendering_blocks)
    source_visual_refs_present = bool(asset_refs.get("visual_refs"))
    source_visual_contract_present = field_requirement(packet, "visual_refs") in {"required", "optional"}
    visual_parent_required = (
        not surface_required
        and (
            model_visual_parent_required
            or structured_visual_rendered
            or (source_visual_refs_present and source_visual_contract_present and packet_family != "reading")
        )
    )
    field_repairs: list[str] = []
    missing_optional = field_contract.get("missing_optional_fields") or []
    for optional_name in ["analysis", "translation", "examples", "rubric"]:
        if optional_name in missing_optional:
            field_repairs.append(f"{optional_name}:not_required_if_source_absent")
    if "partial_answer_set" in codes:
        field_repairs.append("answer:verify_cross_page_completion")
    if "TRUNCATED_ANALYSIS_CONTENT" in codes:
        field_repairs.append("analysis:source_truncated")
    blocking_field_repairs = [
        repair for repair in field_repairs
        if not str(repair).endswith(":not_required_if_source_absent")
    ]
    model_mode_allowed = model_mode in ADMISSION_MODES
    if model_mode in {"FIELD_REPAIR_THEN_READY", "FIELD_REPAIR_OR_SOURCE_REVIEW"} and not (
        blocking_field_repairs or source_review_required
    ):
        model_mode_allowed = False

    mode = "READY_DIRECT"
    builder_action = "build_direct_packet"
    direct_import_allowed = True
    reason = "Display fields are renderable and no blocking import posture was derived."

    if record.get("render_status") == "BLOCKED":
        mode = "NOT_RENDERABLE"
        direct_import_allowed = False
        builder_action = "do_not_build"
        reason = "Rendered record is blocked."
    elif source_review_required:
        mode = "FIELD_REPAIR_OR_SOURCE_REVIEW"
        direct_import_allowed = False
        builder_action = "hold_for_source_numbering_or_mapping_review"
        reason = "Source numbering or answer mapping mismatch is present."
    elif split_required:
        mode = "SPLIT_OR_PARENT_CLUSTER_REQUIRED"
        direct_import_allowed = False
        builder_action = "do_not_build_direct_packet"
        reason = "Upstream preserved this as non-direct or mixed source material."
    elif visual_parent_required:
        mode = "READY_WITH_VISUAL_PARENT"
        builder_action = "build_packet_with_visual_parent_or_source_page"
        reason = "Structured visual evidence is required to preserve the question surface."
    elif model_mode_allowed:
        mode = model_mode
        direct_import_allowed = bool(model_profile.get("direct_import_allowed", direct_import_allowed))
        builder_action = str(model_profile.get("builder_action") or builder_action)
        reason = str(model_profile.get("reason") or reason)
    elif parent_required:
        mode = "READY_WITH_PARENT_CONTEXT"
        builder_action = "build_child_packet_with_parent_context"
        reason = "A parent/context group is required by upstream projection."
    elif surface_required or "writing_surface" in rendering_blocks:
        mode = "READY_DIRECT_WITH_SURFACE"
        builder_action = "build_direct_packet_with_surface"
        reason = "Writing or response surface is present and restored."
    elif blocking_field_repairs and record.get("render_status") == "NEEDS_REVIEW":
        mode = "FIELD_REPAIR_THEN_READY"
        direct_import_allowed = False
        builder_action = "repair_contract_then_build"
        reason = "Only field-contract cleanup appears to block the packet."

    if "example" in question_type.lower() and mode in {"READY_DIRECT", "READY_DIRECT_WITH_SURFACE", "READY_WITH_PARENT_CONTEXT"}:
        mode = "READY_AS_EXAMPLE_CHILD"
        direct_import_allowed = False
        builder_action = "build_example_child_under_parent"
        reason = "Upstream question_type identifies this as an example-style child item."

    if mode in {"READY_AS_EXAMPLE_CHILD", "READY_WITH_PARENT_CONTEXT", "READY_WITH_VISUAL_PARENT"}:
        direct_import_allowed = False
    if mode in {"SPLIT_OR_PARENT_CLUSTER_REQUIRED", "DO_NOT_IMPORT_DUPLICATE_COMPOSITE", "FIELD_REPAIR_THEN_READY", "FIELD_REPAIR_OR_SOURCE_REVIEW", "NOT_RENDERABLE"}:
        direct_import_allowed = False
    if record.get("render_status") != "READY":
        direct_import_allowed = False
    action_by_mode = {
        "READY_DIRECT": "build_direct_packet",
        "READY_DIRECT_WITH_SURFACE": "build_direct_packet_with_surface",
        "READY_WITH_PARENT_CONTEXT": "build_child_packet_with_parent_context",
        "READY_AS_EXAMPLE_CHILD": "build_example_child_under_parent",
        "READY_WITH_VISUAL_PARENT": "build_packet_with_visual_parent_or_source_page",
        "FIELD_REPAIR_THEN_READY": "repair_contract_then_build",
        "FIELD_REPAIR_OR_SOURCE_REVIEW": "hold_for_source_numbering_or_mapping_review",
        "SPLIT_OR_PARENT_CLUSTER_REQUIRED": "do_not_build_direct_packet",
        "DO_NOT_IMPORT_DUPLICATE_COMPOSITE": "absorb_or_build_parent_child_only",
        "NOT_RENDERABLE": "do_not_build",
    }
    builder_action = action_by_mode.get(mode, builder_action)
    return {
        "admission_mode": mode,
        "direct_import_allowed": direct_import_allowed,
        "builder_action": builder_action,
        "parent_required": parent_required,
        "source_review_required": source_review_required,
        "split_required": split_required,
        "surface_required": surface_required,
        "visual_parent_required": visual_parent_required,
        "field_repairs": field_repairs,
        "reason": reason,
    }


def derive_render_status(record: dict[str, Any]) -> str:
    """Compute display readiness from import posture instead of model wording."""
    if record.get("render_status") == "BLOCKED":
        return "BLOCKED"
    admission_profile = record.get("admission_profile") if isinstance(record.get("admission_profile"), dict) else {}
    mode = str(admission_profile.get("admission_mode") or "")
    if mode in {"NOT_RENDERABLE", "FIELD_REPAIR_THEN_READY", "FIELD_REPAIR_OR_SOURCE_REVIEW"}:
        return "NEEDS_REVIEW"
    return "READY"


def field_drop_reasons(packet: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    question = packet.get("standard_question") or {}
    display = record.get("display_question") or {}
    display_text = display_user_text(record)
    mapping = {
        "answer": "answer_markdown",
        "analysis": "analysis_markdown",
        "translation": "translation_markdown",
    }
    reasons: list[dict[str, Any]] = []
    for source_key, display_key in mapping.items():
        source_text = str(question.get(source_key) or "").strip()
        if not source_text or str(display.get(display_key) or "").strip():
            continue
        if not unsupported_lines(source_text=display_text, output_text=source_text, max_examples=1):
            continue
        else:
            reasons.append(
                {
                    "code": f"{source_key}_dropped_after_5b",
                    "message": f"5b standard_question.{source_key} is non-empty but 6b display_question.{display_key} is empty.",
                    "source_field": source_key,
                    "display_field": display_key,
                }
            )
    return reasons


def source_surface_loss_reasons(packet: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    display_text = display_user_text(record)
    reasons: list[dict[str, Any]] = []
    source_blank_runs = source_surface_blank_run_count(packet)
    display_blank_runs = blank_run_count(display_text)
    if source_blank_runs and display_blank_runs < source_blank_runs:
        reasons.append(
            {
                "code": "blank_runs_dropped_after_5b",
                "message": "5b/refined source contains visible fill-in blanks or underline runs that are fewer in 6b display output.",
                "source_blank_runs": source_blank_runs,
                "display_blank_runs": display_blank_runs,
            }
        )
    if source_markdown_table_present(packet) and not markdown_table_surface_present(display_text):
        reasons.append(
            {
                "code": "markdown_table_dropped_after_5b",
                "message": "5b/refined source contains a Markdown table surface that is missing in 6b display output.",
            }
        )
    return reasons


def unsupported_text_reasons(
    packet: dict[str, Any], record: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    source_text = render_source_text(packet)
    display = record.get("display_question") or {}
    blocking_reasons: list[dict[str, Any]] = []
    review_reasons: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    field_policy = {
        "stem_markdown": "image_recoverable",
        "answer_markdown": "verified_solution_field",
        "analysis_markdown": "verified_solution_field",
        "translation_markdown": "image_recoverable",
    }
    for field_name, policy in field_policy.items():
        unsupported = unsupported_lines(source_text=source_text, output_text=str(display.get(field_name) or ""), max_examples=8)
        if not unsupported:
            continue
        issue = {
            "code": f"{field_name}_text_not_in_5b_text_evidence",
            "message": f"6b display_question.{field_name} contains user-facing text not present in 5b text fields/final_markdown.",
            "examples": unsupported,
        }
        if policy == "verified_solution_field":
            review_reasons.append(issue)
            continue
        if has_image_surface_evidence(packet):
            warnings.append(
                {
                    **issue,
                    "message": issue["message"] + " Page image evidence exists, so this is treated as image-restored display content.",
                }
            )
        else:
            blocking_reasons.append(issue)
    return blocking_reasons, review_reasons, warnings


def compute_admission_profile(packet: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Program-side render/import posture; it checks consistency, not lesson semantics."""
    model_profile = record.get("admission_profile") if isinstance(record.get("admission_profile"), dict) else {}
    projection_context = packet.get("projection_context") or {}
    parent_node_ids = projection_context.get("parent_node_ids") or []
    resolved_stimulus = projection_context.get("resolved_stimulus") or {}
    asset_refs = packet.get("asset_refs") or {}
    display = record.get("display_question") or {}
    rendering_blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
    refine_status = str(packet.get("refine_status") or "")
    projection_status = str(projection_context.get("projection_status") or "")
    codes = warning_codes(packet)

    blocking_reasons: list[dict[str, Any]] = []
    review_reasons: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not str(display.get("stem_markdown") or "").strip():
        blocking_reasons.append({"code": "empty_display_stem", "message": "display_question.stem_markdown is empty."})
    if refine_status == "REFINE_FAILED":
        review_reasons.append({"code": "upstream_refine_failed", "message": "Node5b failed local refinement validation; 6b output must be reviewed before import."})
    if refine_status == "PRESERVED_NON_DIRECT" or "non_direct_preserved" in codes or "upstream_preserved_non_direct_refined" in codes:
        review_reasons.append({"code": "preserved_non_direct_source", "message": "Upstream/refiner marked this as non-direct material."})
    for issue in record.get("unresolved_issues") or []:
        if isinstance(issue, dict):
            review_reasons.append(
                {
                    "code": str(issue.get("code") or "unresolved_issue"),
                    "message": str(issue.get("message") or ""),
                    "source_refs": issue.get("source_refs") if isinstance(issue.get("source_refs"), list) else [],
                }
            )
    review_reasons.extend(field_drop_reasons(packet, record))
    review_reasons.extend(source_surface_loss_reasons(packet, record))
    unsupported_blockers, unsupported_review_reasons, unsupported_warnings = unsupported_text_reasons(packet, record)
    blocking_reasons.extend(unsupported_blockers)
    review_reasons.extend(unsupported_review_reasons)
    warnings.extend(unsupported_warnings)
    if asset_refs.get("writing_surface_refs") and "writing_surface" not in rendering_blocks:
        review_reasons.append(
            {
                "code": "surface_ref_without_rendering_block",
                "message": "asset_refs.writing_surface_refs exists but display_question.rendering_blocks does not include writing_surface.",
            }
        )

    parent_required = bool(parent_node_ids) or "REQUIRES_PARENT" in projection_status
    surface_required = bool(asset_refs.get("writing_surface_refs"))
    visual_parent_required = (
        not surface_required
        and (
            bool(model_profile.get("visual_parent_required"))
            or has_visual_structure_block(rendering_blocks)
            or bool(asset_refs.get("visual_refs"))
        )
    )

    mode = "READY_DIRECT"
    reason = "Program-side consistency checks found no blocking or review-only condition."
    if blocking_reasons:
        mode = "NOT_RENDERABLE"
        reason = "Program-side consistency checks found blocking render issues."
    elif any(item.get("code") == "preserved_non_direct_source" for item in review_reasons):
        mode = "SPLIT_OR_PARENT_CLUSTER_REQUIRED"
        reason = "Source is preserved as non-direct or mixed material; do not build direct packet."
    elif review_reasons:
        mode = "FIELD_REPAIR_OR_SOURCE_REVIEW"
        reason = "Program-side consistency checks found field or surface issues that require repair/review."
    elif parent_required:
        mode = "READY_WITH_PARENT_CONTEXT"
        reason = "Projection context contains parent/shared material refs; direct standalone import is not allowed."
    elif visual_parent_required:
        mode = "READY_WITH_VISUAL_PARENT"
        reason = "Visual evidence must remain attached for faithful display."
    elif surface_required or "writing_surface" in rendering_blocks:
        mode = "READY_DIRECT_WITH_SURFACE"
        reason = "Display is renderable and has writing/response surface evidence."
    if str(resolved_stimulus.get("text") or "").strip() and mode == "READY_DIRECT":
        mode = "READY_WITH_PARENT_CONTEXT"
        reason = "Resolved shared stimulus exists; import should keep parent/context relation."

    render_status = "READY"
    if mode == "NOT_RENDERABLE":
        render_status = "BLOCKED"
    elif mode in {"FIELD_REPAIR_OR_SOURCE_REVIEW", "SPLIT_OR_PARENT_CLUSTER_REQUIRED"}:
        render_status = "NEEDS_REVIEW"

    direct_import_allowed = mode in {"READY_DIRECT", "READY_DIRECT_WITH_SURFACE"} and render_status == "READY"
    action_by_mode = {
        "READY_DIRECT": "build_direct_packet",
        "READY_DIRECT_WITH_SURFACE": "build_direct_packet_with_surface",
        "READY_WITH_PARENT_CONTEXT": "build_child_packet_with_parent_context",
        "READY_WITH_VISUAL_PARENT": "build_packet_with_visual_parent_or_source_page",
        "FIELD_REPAIR_OR_SOURCE_REVIEW": "hold_for_render_repair_or_source_review",
        "SPLIT_OR_PARENT_CLUSTER_REQUIRED": "do_not_build_direct_packet",
        "NOT_RENDERABLE": "do_not_build",
    }
    return {
        "admission_mode": mode,
        "direct_import_allowed": direct_import_allowed,
        "builder_action": action_by_mode.get(mode, "hold_for_review"),
        "parent_required": parent_required,
        "source_review_required": bool(blocking_reasons or review_reasons),
        "split_required": mode == "SPLIT_OR_PARENT_CLUSTER_REQUIRED",
        "surface_required": surface_required,
        "visual_parent_required": visual_parent_required,
        "field_repairs": [item["code"] for item in blocking_reasons + review_reasons],
        "reason": reason,
        "computed_render_status": render_status,
        "blocking_reasons": blocking_reasons,
        "review_reasons": review_reasons,
        "warnings": warnings,
    }


def finalize_record_posture(packet: dict[str, Any], record: dict[str, Any]) -> None:
    record["model_admission_profile"] = record.get("admission_profile") if isinstance(record.get("admission_profile"), dict) else {}
    model_profile = derive_admission_profile(packet, record)
    record["model_derived_admission_profile"] = model_profile
    record["admission_profile"] = model_profile
    record["render_status"] = derive_render_status(record)
    computed_profile = compute_admission_profile(packet, record)
    record["computed_admission_profile"] = computed_profile
    record["admission_profile"] = {
        key: value
        for key, value in computed_profile.items()
        if key not in {"computed_render_status", "blocking_reasons", "review_reasons", "warnings"}
    }
    record["render_status"] = computed_profile["computed_render_status"]
    normalize_non_direct_material_record(packet, record)


def compact_for_length_compare(text: str) -> str:
    return "".join(str(text or "").split())


def render_source_text(packet: dict[str, Any]) -> str:
    question = packet.get("standard_question") or {}
    parts = [str(packet.get("final_markdown") or "")]
    for key in ["passage", "context", "stem", "answer", "analysis", "translation", "examples", "rubric"]:
        parts.append(str(question.get(key) or ""))
    options = question.get("options") if isinstance(question.get("options"), list) else []
    for option in options:
        if isinstance(option, dict):
            parts.append(" ".join(str(option.get(key) or "") for key in ["label", "text"]))
    projection_context = packet.get("projection_context") or {}
    resolved_stimulus = projection_context.get("resolved_stimulus") or {}
    parts.append(str(resolved_stimulus.get("text") or ""))
    return "\n".join(parts)


def render_source_field_texts(packet: dict[str, Any]) -> list[str]:
    question = packet.get("standard_question") or {}
    parts = [str(packet.get("final_markdown") or "")]
    for key in ["passage", "context", "stem", "answer", "analysis", "translation", "examples", "rubric"]:
        parts.append(str(question.get(key) or ""))
    options = question.get("options") if isinstance(question.get("options"), list) else []
    if options:
        option_lines: list[str] = []
        for option in options:
            if isinstance(option, dict):
                option_lines.append(" ".join(str(option.get(key) or "") for key in ["label", "text"]))
        parts.append("\n".join(option_lines))
    projection_context = packet.get("projection_context") or {}
    resolved_stimulus = projection_context.get("resolved_stimulus") or {}
    parts.append(str(resolved_stimulus.get("text") or ""))
    return [part for part in parts if part.strip()]


def source_surface_blank_run_count(packet: dict[str, Any]) -> int:
    """Count required blanks without double-counting final_markdown and field copies."""
    return max([blank_run_count(part) for part in render_source_field_texts(packet)] or [0])


def source_markdown_table_present(packet: dict[str, Any]) -> bool:
    return any(markdown_table_surface_present(part) for part in render_source_field_texts(packet))


def has_loose_pipe_table(text: str) -> bool:
    run = 0
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if "|" in stripped and not stripped.startswith("|") and stripped.count("|") >= 1:
            run += 1
            if run >= 2:
                return True
            continue
        if stripped:
            run = 0
    return False


def has_malformed_pipe_table(text: str) -> bool:
    pipe_lines = 0
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            pipe_lines += 1
            if pipe_lines >= 2:
                return True
            continue
        if stripped:
            pipe_lines = 0
    return False


def normalize_loose_pipe_tables(markdown: str) -> str:
    """Convert adjacent `label | value` rows into a renderable Markdown table.

    This is syntax repair only: it preserves cell text and adds only Markdown
    table punctuation, with blank headers to avoid inventing labels.
    """
    lines = str(markdown or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("|") or "|" not in stripped:
            out.append(lines[i])
            i += 1
            continue
        run: list[str] = []
        while i < len(lines):
            candidate = lines[i].strip()
            if candidate and "|" in candidate and not candidate.startswith("|"):
                run.append(lines[i])
                i += 1
                continue
            break
        if len(run) < 2:
            out.extend(run)
            continue
        max_cells = max(len(row.split("|")) for row in run)
        out.append("| " + " | ".join([""] * max_cells) + " |")
        out.append("| " + " | ".join(["---"] * max_cells) + " |")
        for row in run:
            cells = [cell.strip() for cell in row.split("|")]
            cells.extend([""] * (max_cells - len(cells)))
            out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def context_belongs_in_stem(packet: dict[str, Any], context_text: str) -> bool:
    asset_refs = packet.get("asset_refs") or {}
    if asset_refs.get("writing_surface_refs") or asset_refs.get("visual_refs"):
        return True
    if markdown_table_surface_present(context_text) or has_loose_pipe_table(context_text):
        return True
    projection_context = packet.get("projection_context") or {}
    if projection_context.get("resolved_parent_nodes"):
        return True
    return False


def display_user_text(record: dict[str, Any]) -> str:
    display = record.get("display_question") or {}
    parts = [
        str(display.get("stem_markdown") or ""),
        str(display.get("answer_markdown") or ""),
        str(display.get("analysis_markdown") or ""),
        str(display.get("translation_markdown") or ""),
    ]
    return "\n".join(parts)


def unsupported_display_lines(record: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    return unsupported_lines(source_text=render_source_text(packet), output_text=display_user_text(record))


def has_image_surface_evidence(packet: dict[str, Any]) -> bool:
    asset_refs = packet.get("asset_refs") or {}
    page_images = asset_refs.get("page_image_refs") or []
    return bool(page_images)


def normalize_non_direct_material_record(packet: dict[str, Any], record: dict[str, Any]) -> None:
    """Keep preserved non-direct material from masquerading as a question.

    This is an import/display contract, not a lesson-type rule: when upstream
    has already marked a packet as preserved source material, Node6b may render
    it for human review, but must not emit answerable items.
    """
    refine_status = str(packet.get("refine_status") or "")
    admission = record.get("admission_profile") if isinstance(record.get("admission_profile"), dict) else {}
    builder_action = str(admission.get("builder_action") or "")
    if refine_status != "PRESERVED_NON_DIRECT" and builder_action != "do_not_build_direct_packet":
        return

    question = packet.get("standard_question") or {}
    display = record.setdefault("display_question", {})
    material_parts: list[str] = []
    for key in ["context", "stem", "examples", "rubric"]:
        append_unique_text(material_parts, str(question.get(key) or ""))
    source_material = "\n\n".join(material_parts).strip() or str(packet.get("final_markdown") or "").strip()
    current_stem = str(display.get("stem_markdown") or "").strip()
    if source_material and len(compact_for_length_compare(source_material)) > len(compact_for_length_compare(current_stem)):
        display["stem_markdown"] = source_material
    display["answer_markdown"] = ""
    display["analysis_markdown"] = ""
    display["translation_markdown"] = ""
    display["items"] = []
    rendering_blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
    rendering_blocks = [block for block in rendering_blocks if block != "question_items"]
    if "material_card" not in rendering_blocks:
        rendering_blocks.insert(0, "material_card")
    display["rendering_blocks"] = rendering_blocks
    actions = record.setdefault("normalization_actions", [])
    action = "postprocess:preserved_non_direct_rendered_as_material_card"
    if action not in actions:
        actions.append(action)


def is_renderable_question(packet: dict[str, Any]) -> bool:
    if packet.get("refine_status") == "PRESERVED_NON_DIRECT":
        return False
    question = packet.get("standard_question") or {}
    return bool(str(question.get("stem") or "").strip() and str(question.get("answer") or "").strip())


def call_model(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path],
    api_key: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    }
    started = time.time()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                config["api_url"],
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json=body,
                timeout=300,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
            raw = response.json()
            break
        except Exception as exc:
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"model request failed: {last_error}")
    raw_content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(raw_content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def repair_shape(payload: dict[str, Any] | None, packet: dict[str, Any]) -> dict[str, Any]:
    q = packet.get("standard_question") or {}
    if not isinstance(payload, dict):
        payload = {}
    display = payload.get("display_question")
    if not isinstance(display, dict):
        display = {}
    display.setdefault("title", q.get("title") or packet.get("source_packet_id") or "")
    display.setdefault("stem_markdown", q.get("stem") or "")
    display.setdefault("answer_markdown", q.get("answer") or "")
    display.setdefault("analysis_markdown", q.get("analysis") or "")
    display.setdefault("translation_markdown", q.get("translation") or "")
    display.setdefault("items", [])
    display.setdefault("rendering_blocks", [])
    admission_profile = payload.get("admission_profile")
    if not isinstance(admission_profile, dict):
        admission_profile = {}
    payload.update(
        {
            "schema": "rendered_question_record_v0.1",
            "doc_id": packet.get("doc_id"),
            "source_packet_id": packet.get("source_packet_id"),
            "source_group_id": packet.get("source_group_id"),
            "prompt_version": PROMPT_VERSION,
            "render_status": payload.get("render_status") if payload.get("render_status") in {"READY", "NEEDS_REVIEW", "SOURCE_IMAGE_REQUIRED", "BLOCKED"} else "NEEDS_REVIEW",
            "display_question": display,
            "admission_profile": admission_profile,
            "source_refs_used": payload.get("source_refs_used") if isinstance(payload.get("source_refs_used"), list) else [],
            "unresolved_issues": payload.get("unresolved_issues") if isinstance(payload.get("unresolved_issues"), list) else [],
            "normalization_actions": payload.get("normalization_actions") if isinstance(payload.get("normalization_actions"), list) else [],
        }
    )
    return payload


def standard_source_fields(packet: dict[str, Any]) -> dict[str, str]:
    question = packet.get("standard_question") or {}
    options = question.get("options") if isinstance(question.get("options"), list) else []
    option_lines: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        text = str(option.get("text") or "").strip()
        if label or text:
            option_lines.append(f"{label}. {text}".strip())
    projection_context = packet.get("projection_context") or {}
    resolved_stimulus = projection_context.get("resolved_stimulus") or {}
    return {
        "final_markdown": str(packet.get("final_markdown") or "").strip(),
        "passage": str(question.get("passage") or "").strip(),
        "context": str(question.get("context") or "").strip(),
        "stem": str(question.get("stem") or "").strip(),
        "options": "\n".join(option_lines).strip(),
        "answer": str(question.get("answer") or "").strip(),
        "analysis": str(question.get("analysis") or "").strip(),
        "translation": str(question.get("translation") or "").strip(),
        "examples": str(question.get("examples") or "").strip(),
        "rubric": str(question.get("rubric") or "").strip(),
        "resolved_stimulus": str(resolved_stimulus.get("text") or "").strip(),
    }


def append_unique_text(parts: list[str], text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    compact = compact_for_length_compare(cleaned)
    for existing in parts:
        existing_compact = compact_for_length_compare(existing)
        if compact and (compact in existing_compact or existing_compact in compact):
            if len(compact) <= len(existing_compact):
                return
            parts.remove(existing)
            break
    parts.append(cleaned)


def merge_visual_recovery_continuation(parts: list[str], recovered_text: str) -> bool:
    recovered_lines = [line.strip() for line in str(recovered_text or "").splitlines() if line.strip()]
    if not recovered_lines:
        return False
    if len(recovered_lines) == 1 and 0 < len(recovered_lines[0]) <= 8:
        tail = recovered_lines[0]
        terminal_punctuation = set(".。?？!！;；:：)")
        for part_index in range(len(parts) - 1, -1, -1):
            part_lines = parts[part_index].splitlines()
            for line_index in range(len(part_lines) - 1, -1, -1):
                existing_line = part_lines[line_index].rstrip()
                if len(existing_line.strip()) >= 20 and existing_line[-1:] not in terminal_punctuation:
                    part_lines[line_index] = existing_line + tail
                    parts[part_index] = "\n".join(part_lines).strip()
                    return True
    changed = False
    for recovered_line in recovered_lines:
        recovered_compact = compact_for_length_compare(recovered_line)
        if len(recovered_compact) < 24:
            continue
        for part_index, part in enumerate(list(parts)):
            part_lines = part.splitlines()
            for line_index, existing_line in enumerate(part_lines):
                existing_compact = compact_for_length_compare(existing_line)
                if len(existing_compact) < 24:
                    continue
                if existing_compact != recovered_compact and recovered_compact.startswith(existing_compact):
                    part_lines[line_index] = recovered_line
                    parts[part_index] = "\n".join(part_lines).strip()
                    changed = True
                    break
            if changed:
                break
    return changed


def default_rendering_blocks(packet: dict[str, Any], stem_markdown: str) -> list[str]:
    blocks: list[str] = []
    q = packet.get("standard_question") or {}
    if q.get("passage") or ((packet.get("projection_context") or {}).get("resolved_stimulus") or {}).get("text"):
        blocks.append("shared_stimulus")
    if q.get("context"):
        blocks.append("parent_context")
    if q.get("stem"):
        blocks.append("question_stem")
    if q.get("options"):
        blocks.append("question_options")
    if markdown_table_surface_present(stem_markdown):
        blocks.append("markdown_table")
    asset_refs = packet.get("asset_refs") or {}
    if asset_refs.get("visual_refs"):
        blocks.append("visual_surface")
    if asset_refs.get("writing_surface_refs"):
        blocks.append("writing_surface")
    return list(dict.fromkeys(blocks))


def empty_binding_decision(status: str = "NOT_REQUIRED", required: bool = False, reason: str = "") -> dict[str, Any]:
    return {
        "required": required,
        "resolved_refs": [],
        "asset_refs": [],
        "status": status,
        "reason": reason,
    }


def repair_plan_shape(payload: dict[str, Any] | None, packet: dict[str, Any], reason: str = "") -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    asset_refs = packet.get("asset_refs") or {}
    projection_context = packet.get("projection_context") or {}
    resolved_stimulus = projection_context.get("resolved_stimulus") or {}
    operations: list[dict[str, Any]] = []
    for operation in payload.get("operations") if isinstance(payload.get("operations"), list) else []:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "")
        if op not in RENDER_PLAN_OPS:
            continue
        target = str(operation.get("target_field") or "")
        if target and target not in DISPLAY_TARGET_FIELDS and op not in {
            "attach_parent_context",
            "attach_stimulus",
            "attach_visual_surface",
            "attach_writing_surface",
            "preserve_material_only",
            "mark_review_required",
        }:
            continue
        operations.append(
            {
                "op": op,
                "target_field": target,
                "source_fields": [str(item) for item in operation.get("source_fields") or [] if str(item) in DISPLAY_SOURCE_FIELDS],
                "source_refs": [str(item) for item in operation.get("source_refs") or []],
                "reason": str(operation.get("reason") or ""),
            }
        )
    review_requirements: list[dict[str, Any]] = []
    for item in payload.get("review_requirements") if isinstance(payload.get("review_requirements"), list) else []:
        if not isinstance(item, dict):
            continue
        review_requirements.append(
            {
                "code": str(item.get("code") or "review_required"),
                "message": str(item.get("message") or ""),
                "source_refs": [str(ref) for ref in item.get("source_refs") or []],
            }
        )
    layout_sections: list[dict[str, Any]] = []
    for section in payload.get("layout_sections") if isinstance(payload.get("layout_sections"), list) else []:
        if not isinstance(section, dict):
            continue
        display_area = str(section.get("display_area") or "")
        if display_area not in DISPLAY_TARGET_FIELDS:
            continue
        layout_sections.append(
            {
                "section_id": str(section.get("section_id") or f"section_{len(layout_sections) + 1:03d}"),
                "display_area": display_area,
                "source_fields": [str(item) for item in section.get("source_fields") or [] if str(item) in DISPLAY_SOURCE_FIELDS],
                "render_as": str(section.get("render_as") or "source_markdown") if str(section.get("render_as") or "source_markdown") in LAYOUT_RENDER_AS else "source_markdown",
                "reason": str(section.get("reason") or ""),
            }
        )
    visual_recovered_sections: list[dict[str, Any]] = []
    for section in payload.get("visual_recovered_sections") if isinstance(payload.get("visual_recovered_sections"), list) else []:
        if not isinstance(section, dict):
            continue
        display_area = str(section.get("display_area") or "")
        render_as = str(section.get("render_as") or "source_markdown")
        if display_area not in DISPLAY_TARGET_FIELDS or render_as not in VISUAL_RECOVERY_RENDER_AS:
            continue
        visual_recovered_sections.append(
            {
                "section_id": str(section.get("section_id") or f"vr_{len(visual_recovered_sections) + 1:03d}"),
                "display_area": display_area,
                "render_as": render_as,
                "source_page_refs": [str(item) for item in section.get("source_page_refs") or []],
                "bbox_hint": str(section.get("bbox_hint") or ""),
                "recovered_markdown": str(section.get("recovered_markdown") or ""),
                "confidence": str(section.get("confidence") or "low") if str(section.get("confidence") or "low") in {"high", "medium", "low"} else "low",
                "recovery_reason": str(section.get("recovery_reason") or ""),
            }
        )
    plan = {
        "schema": RENDER_PLAN_SCHEMA,
        "doc_id": packet.get("doc_id"),
        "source_packet_id": packet.get("source_packet_id"),
        "source_group_id": packet.get("source_group_id"),
        "planner_version": RENDER_PLAN_VERSION,
        "plan_status": payload.get("plan_status") if payload.get("plan_status") in {"PLAN_READY", "PLAN_NEEDS_REVIEW", "PLAN_BLOCKED"} else "PLAN_NEEDS_REVIEW",
        "operations": operations,
        "layout_sections": layout_sections,
        "visual_recovered_sections": visual_recovered_sections,
        "binding_decisions": payload.get("binding_decisions") if isinstance(payload.get("binding_decisions"), dict) else {},
        "review_requirements": review_requirements,
    }
    bindings = plan["binding_decisions"]
    defaults = {
        "parent_context": empty_binding_decision(
            "BOUND" if projection_context.get("resolved_parent_nodes") else "NOT_REQUIRED",
            bool(projection_context.get("resolved_parent_nodes")),
            "projection_context.resolved_parent_nodes present" if projection_context.get("resolved_parent_nodes") else "",
        ),
        "stimulus": empty_binding_decision(
            "BOUND" if str(resolved_stimulus.get("text") or "").strip() else "NOT_REQUIRED",
            bool(str(resolved_stimulus.get("text") or "").strip()),
            "projection_context.resolved_stimulus.text present" if str(resolved_stimulus.get("text") or "").strip() else "",
        ),
        "visual_surface": empty_binding_decision(
            "BOUND" if asset_refs.get("visual_refs") else "NOT_REQUIRED",
            bool(asset_refs.get("visual_refs")),
            "asset_refs.visual_refs present" if asset_refs.get("visual_refs") else "",
        ),
        "writing_surface": empty_binding_decision(
            "BOUND" if asset_refs.get("writing_surface_refs") else "NOT_REQUIRED",
            bool(asset_refs.get("writing_surface_refs")),
            "asset_refs.writing_surface_refs present" if asset_refs.get("writing_surface_refs") else "",
        ),
    }
    for key, default in defaults.items():
        value = bindings.get(key)
        if not isinstance(value, dict):
            bindings[key] = default
            continue
        repaired = dict(default)
        repaired.update(
            {
                "required": bool(value.get("required")),
                "resolved_refs": value.get("resolved_refs") if isinstance(value.get("resolved_refs"), list) else [],
                "asset_refs": value.get("asset_refs") if isinstance(value.get("asset_refs"), list) else [],
                "status": value.get("status") if value.get("status") in {"BOUND", "NOT_REQUIRED", "UNRESOLVED", "SOURCE_IMAGE_REQUIRED"} else default["status"],
                "reason": str(value.get("reason") or default.get("reason") or ""),
            }
        )
        bindings[key] = repaired
    if reason:
        plan["review_requirements"].append({"code": "planner_repaired", "message": reason, "source_refs": []})
    return plan


def validate_render_plan(plan: dict[str, Any]) -> dict[str, Any]:
    schema = read_json(workspace_path(RENDER_PLAN_SCHEMA_PATH))
    validator = Draft202012Validator(schema)
    errors = [
        {"path": "$." + ".".join(str(part) for part in error.path), "message": error.message}
        for error in validator.iter_errors(plan)
    ]
    return {"valid": not errors, "errors": errors}


def operation_source_text(operation: dict[str, Any], source_fields: dict[str, str]) -> str:
    parts: list[str] = []
    for field in operation.get("source_fields") or []:
        if str(field) in DISPLAY_SOURCE_FIELDS:
            append_unique_text(parts, source_fields.get(str(field), ""))
    return "\n\n".join(parts).strip()


def render_layout_section_text(section: dict[str, Any], source_fields: dict[str, str]) -> str:
    parts: list[str] = []
    for field in section.get("source_fields") or []:
        text = source_fields.get(str(field), "")
        if section.get("render_as") in {"table", "surface"} or has_loose_pipe_table(text):
            text = normalize_loose_pipe_tables(text)
        append_unique_text(parts, text)
    return "\n\n".join(parts).strip()


def visual_recovery_areas(plan: dict[str, Any]) -> set[str]:
    areas: set[str] = set()
    for section in plan.get("visual_recovered_sections") or []:
        if not isinstance(section, dict):
            continue
        if str(section.get("recovered_markdown") or "").strip():
            areas.add(str(section.get("display_area") or ""))
    return areas


def field_looks_like_surface_companion(text: str) -> bool:
    if markdown_table_surface_present(text) or has_loose_pipe_table(text) or has_malformed_pipe_table(text):
        return True
    normalized = str(text or "").strip().lower()
    companion_markers = [
        "blank exercise table:",
        "red filled answer table:",
        "headers are",
        "visible filled rows:",
        "remaining rows",
    ]
    return any(marker in normalized for marker in companion_markers)


def render_layout_section_text_with_visual_replacement(
    section: dict[str, Any],
    source_fields: dict[str, str],
    replaced_areas: set[str],
) -> str:
    if str(section.get("display_area") or "") not in replaced_areas:
        return render_layout_section_text(section, source_fields)
    parts: list[str] = []
    for field in section.get("source_fields") or []:
        text = source_fields.get(str(field), "")
        if field_looks_like_surface_companion(text):
            continue
        if section.get("render_as") in {"table", "surface"} or has_loose_pipe_table(text):
            text = normalize_loose_pipe_tables(text)
        append_unique_text(parts, text)
    return "\n\n".join(parts).strip()


def layout_surface_review_requirements(plan: dict[str, Any], source_fields: dict[str, str]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for section in plan.get("layout_sections") or []:
        if not isinstance(section, dict) or section.get("render_as") != "table":
            continue
        section_text = "\n\n".join(source_fields.get(str(field), "") for field in section.get("source_fields") or [])
        if markdown_table_surface_present(section_text) or has_loose_pipe_table(section_text):
            continue
        requirements.append(
            {
                "code": "table_layout_requested_without_structured_table_text",
                "message": "Layout plan requested table rendering, but the referenced source fields contain only prose/table companion text; visual table recovery is required.",
                "source_refs": [],
            }
        )
    return requirements


def render_visual_recovered_text(section: dict[str, Any]) -> str:
    text = str(section.get("recovered_markdown") or "").strip()
    if section.get("render_as") in {"table", "surface"}:
        text = normalize_loose_pipe_tables(text)
    return text


def visual_recovery_review_requirements(plan: dict[str, Any]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for section in plan.get("visual_recovered_sections") or []:
        if not isinstance(section, dict):
            continue
        refs = [str(item) for item in section.get("source_page_refs") or [] if str(item).strip()]
        bbox_hint = str(section.get("bbox_hint") or "").strip()
        text = str(section.get("recovered_markdown") or "").strip()
        confidence = str(section.get("confidence") or "low")
        if not refs or not bbox_hint or not text:
            requirements.append(
                {
                    "code": "visual_recovery_missing_evidence",
                    "message": "Visual recovery section lacks page ref, bbox_hint, or recovered text.",
                    "source_refs": refs,
                }
            )
        if confidence != "high":
            requirements.append(
                {
                    "code": "visual_recovery_requires_review",
                    "message": f"Visual recovery confidence is {confidence}; review before direct import.",
                    "source_refs": refs,
                }
            )
        if section.get("render_as") == "table" and not markdown_table_surface_present(text):
            requirements.append(
                {
                    "code": "visual_recovery_table_not_markdown_table",
                    "message": "Visual recovery section requested table rendering but recovered_markdown is not a renderable Markdown table.",
                    "source_refs": refs,
                }
            )
    return requirements


def default_layout_sections(packet: dict[str, Any], source_fields: dict[str, str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    context_text = source_fields.get("context", "")
    context_area = "stem_markdown" if context_belongs_in_stem(packet, context_text) else "translation_markdown"
    for field in ["resolved_stimulus", "passage"]:
        if source_fields.get(field):
            sections.append({"section_id": field, "display_area": "stem_markdown", "source_fields": [field], "render_as": "source_markdown", "reason": "default stimulus/passage placement"})
    if context_text:
        sections.append({"section_id": "context", "display_area": context_area, "source_fields": ["context"], "render_as": "table" if has_loose_pipe_table(context_text) else "supplement", "reason": "default context placement"})
    for field in ["stem", "options", "examples", "rubric"]:
        if source_fields.get(field):
            sections.append({"section_id": field, "display_area": "stem_markdown", "source_fields": [field], "render_as": "source_markdown", "reason": "default question body placement"})
    for field, area in [("answer", "answer_markdown"), ("analysis", "analysis_markdown"), ("translation", "translation_markdown")]:
        if source_fields.get(field):
            sections.append({"section_id": field, "display_area": area, "source_fields": [field], "render_as": "table" if has_loose_pipe_table(source_fields.get(field, "")) else "source_markdown", "reason": "default solution/supplement placement"})
    return sections


def execute_render_plan(packet: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    source_fields = standard_source_fields(packet)
    area_parts: dict[str, list[str]] = {field: [] for field in DISPLAY_TARGET_FIELDS}
    layout_sections = plan.get("layout_sections") if isinstance(plan.get("layout_sections"), list) else []
    if not layout_sections:
        layout_sections = default_layout_sections(packet, source_fields)
    replaced_areas = visual_recovery_areas(plan)
    for section in layout_sections:
        if not isinstance(section, dict):
            continue
        area = str(section.get("display_area") or "")
        if area not in area_parts:
            continue
        append_unique_text(area_parts[area], render_layout_section_text_with_visual_replacement(section, source_fields, replaced_areas))
    for section in plan.get("visual_recovered_sections") or []:
        if not isinstance(section, dict):
            continue
        area = str(section.get("display_area") or "")
        if area not in area_parts:
            continue
        recovered_text = render_visual_recovered_text(section)
        if not merge_visual_recovery_continuation(area_parts[area], recovered_text):
            append_unique_text(area_parts[area], recovered_text)
    display = {
        "title": (packet.get("standard_question") or {}).get("title") or packet.get("source_packet_id") or "",
        "stem_markdown": "\n\n".join(area_parts["stem_markdown"]).strip(),
        "answer_markdown": "\n\n".join(area_parts["answer_markdown"]).strip(),
        "analysis_markdown": "\n\n".join(area_parts["analysis_markdown"]).strip(),
        "translation_markdown": "\n\n".join(area_parts["translation_markdown"]).strip(),
        "items": [],
        "rendering_blocks": [],
    }
    has_layout_sections = bool(plan.get("layout_sections"))
    actions = ["program_renderer:layout_sections" if has_layout_sections else "program_renderer:default_layout_sections"]
    for operation in plan.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "")
        target = str(operation.get("target_field") or "")
        text = operation_source_text(operation, source_fields)
        if has_layout_sections and target in DISPLAY_TARGET_FIELDS:
            actions.append(f"program_renderer:ignored_legacy_text_operation_after_layout:{op}:{target}")
            continue
        if target in DISPLAY_TARGET_FIELDS and text:
            if op in {"copy_field", "merge_fields", "move_field", "attach_parent_context", "attach_stimulus", "render_table_from_existing_rows"}:
                if target == "stem_markdown":
                    append_unique_text(area_parts[target], text)
                    display[target] = "\n\n".join(area_parts[target]).strip()
                else:
                    display[target] = text
                actions.append(f"program_renderer:{op}:{target}")
        if op == "attach_visual_surface":
            display["rendering_blocks"].append("visual_surface")
            actions.append("program_renderer:attach_visual_surface")
        elif op == "attach_writing_surface":
            display["rendering_blocks"].append("writing_surface")
            actions.append("program_renderer:attach_writing_surface")
        elif op == "preserve_material_only" and packet.get("refine_status") == "PRESERVED_NON_DIRECT":
            display["answer_markdown"] = ""
            display["analysis_markdown"] = ""
            display["translation_markdown"] = ""
            actions.append("program_renderer:preserve_material_only")
        elif op == "preserve_material_only":
            actions.append("program_renderer:ignored_preserve_material_only_for_direct_packet")
    display["rendering_blocks"] = list(dict.fromkeys(default_rendering_blocks(packet, display["stem_markdown"]) + display["rendering_blocks"]))
    unresolved = [dict(item) for item in plan.get("review_requirements") or [] if isinstance(item, dict)]
    if not plan.get("visual_recovered_sections"):
        unresolved.extend(layout_surface_review_requirements(plan, source_fields))
    unresolved.extend(visual_recovery_review_requirements(plan))
    for binding_name, binding in (plan.get("binding_decisions") or {}).items():
        if not isinstance(binding, dict):
            continue
        if binding.get("required") and binding.get("status") in {"UNRESOLVED", "SOURCE_IMAGE_REQUIRED"}:
            unresolved.append(
                {
                    "code": f"{binding_name}_{str(binding.get('status') or '').lower()}",
                    "message": str(binding.get("reason") or f"{binding_name} requires review."),
                    "source_refs": list(binding.get("resolved_refs") or []) + list(binding.get("asset_refs") or []),
                }
            )
    record = repair_shape(
        {
            "render_status": "NEEDS_REVIEW" if unresolved or plan.get("plan_status") != "PLAN_READY" else "READY",
            "display_question": display,
            "admission_profile": {},
            "source_refs_used": sorted(set(sum((list(operation.get("source_refs") or []) for operation in plan.get("operations") or [] if isinstance(operation, dict)), []))),
            "unresolved_issues": unresolved,
            "normalization_actions": actions,
            "render_instruction_plan": plan,
            "visual_recovered_sections": plan.get("visual_recovered_sections") or [],
        },
        packet,
    )
    return record


def validate_record(record: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for key in [
        "schema",
        "doc_id",
        "source_packet_id",
        "source_group_id",
        "prompt_version",
        "render_status",
        "display_question",
        "admission_profile",
        "source_refs_used",
        "unresolved_issues",
        "normalization_actions",
    ]:
        if key not in record:
            errors.append({"path": f"$.{key}", "message": "missing required key"})
    if record.get("schema") != "rendered_question_record_v0.1":
        errors.append({"path": "$.schema", "message": "invalid schema"})
    admission_profile = record.get("admission_profile")
    if not isinstance(admission_profile, dict):
        errors.append({"path": "$.admission_profile", "message": "missing admission profile"})
    elif admission_profile.get("admission_mode") and admission_profile.get("admission_mode") not in ADMISSION_MODES:
        warnings.append({"path": "$.admission_profile.admission_mode", "message": "unknown admission mode"})
    if record.get("doc_id") != packet.get("doc_id"):
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if record.get("source_packet_id") != packet.get("source_packet_id"):
        errors.append({"path": "$.source_packet_id", "message": "source_packet_id mismatch"})
    display = record.get("display_question") or {}
    for key in ["title", "stem_markdown", "answer_markdown", "analysis_markdown", "translation_markdown", "items", "rendering_blocks"]:
        if key not in display:
            errors.append({"path": f"$.display_question.{key}", "message": "missing display field"})
    if not str(display.get("stem_markdown") or "").strip():
        errors.append({"path": "$.display_question.stem_markdown", "message": "empty stem_markdown"})
    rendering_blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
    asset_refs = packet.get("asset_refs") or {}
    if asset_refs.get("writing_surface_refs") and record.get("render_status") in {"READY", "NEEDS_REVIEW"}:
        if "writing_surface" not in rendering_blocks:
            errors.append(
                {
                    "path": "$.display_question.rendering_blocks",
                    "message": "writing_surface_refs are present but display rendering_blocks does not include writing_surface; restore the visible writing/response surface into stem_markdown",
                }
            )
    projection_context = packet.get("projection_context") or {}
    resolved_stimulus = projection_context.get("resolved_stimulus") or {}
    if str(resolved_stimulus.get("text") or "").strip() and record.get("render_status") == "READY":
        stimulus_text = str(resolved_stimulus.get("text") or "").strip()
        stimulus_head = stimulus_text[:120].strip()
        display_text = "\n".join(
            str(display.get(key) or "")
            for key in ["stem_markdown", "analysis_markdown", "translation_markdown"]
        )
        if stimulus_head and stimulus_head not in display_text:
            errors.append(
                {
                    "path": "$.display_question.stem_markdown",
                    "message": "resolved shared stimulus exists but its leading text is not visible in display fields; include the shared passage in stem_markdown for a self-contained rendered question",
                }
            )
    stem_markdown = str(display.get("stem_markdown") or "")
    standard_question = packet.get("standard_question") or {}
    options = standard_question.get("options") if isinstance(standard_question.get("options"), list) else []
    if options:
        label_counts = multiple_choice_label_counts(stem_markdown)
        for option in options:
            if not isinstance(option, dict):
                continue
            label = str(option.get("label") or "").strip().upper()
            text = str(option.get("text") or "").strip()
            if not label:
                continue
            if label_counts.get(label, 0) != 1:
                errors.append(
                    {
                        "path": "$.display_question.stem_markdown",
                        "message": f"multiple-choice option label {label} appears {label_counts.get(label, 0)} times; preserve exactly one visible option line per source option",
                    }
                )
            if text and text not in stem_markdown:
                errors.append(
                    {
                        "path": "$.display_question.stem_markdown",
                        "message": f"multiple-choice option {label} text is missing or changed; preserve source option text exactly",
                    }
                )
    for index, item in enumerate(display.get("items") or []):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if len(prompt) >= 12 and prompt not in stem_markdown:
            warnings.append(
                {
                    "path": f"$.display_question.items[{index}].prompt",
                    "message": "item prompt is not literally included in stem_markdown; verify display stem is self-contained",
                }
            )
    unsupported = unsupported_display_lines(record, packet)
    if unsupported:
        issue = {
            "path": "$.display_question",
            "message": "display output contains user-facing lines not supported by refined packet text evidence",
            "examples": unsupported,
        }
        if has_image_surface_evidence(packet):
            warnings.append(
                {
                    **issue,
                    "message": issue["message"] + "; page image / visual surface evidence exists, so this requires visual coverage verification instead of text-only rejection",
                }
            )
        else:
            errors.append(issue)
    source_blank_runs = source_surface_blank_run_count(packet)
    display_blank_runs = blank_run_count(display_user_text(record))
    if source_blank_runs and display_blank_runs < source_blank_runs:
        errors.append(
            {
                "path": "$.display_question.stem_markdown",
                "message": "fill-in blanks/underline runs were lost during render normalization",
                "source_blank_runs": source_blank_runs,
                "display_blank_runs": display_blank_runs,
            }
        )
    if source_markdown_table_present(packet) and not markdown_table_surface_present(display_user_text(record)):
        errors.append(
            {
                "path": "$.display_question.stem_markdown",
                "message": "source Markdown table surface was lost during render normalization",
            }
        )
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def markdown_table_to_html(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    header = rows[0]
    body = rows[2:] if len(rows) > 2 else []
    head_html = "".join(f"<th>{inline_markdown(cell)}</th>" for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{inline_markdown(cell)}</td>" for cell in row) + "</tr>"
        for row in body
    )
    return f"<table class='md-table'><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"


def is_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    return all(ch in {"-", ":", "|", " "} for ch in stripped)


def inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    return escaped.replace("&nbsp;", " ")


def markdown_to_html(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + "<br>".join(inline_markdown(line) for line in paragraph) + "</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            out.append("<ul>" + "".join(f"<li>{inline_markdown(item)}</li>" for item in list_items) + "</ul>")
            list_items = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            flush_paragraph()
            flush_list()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(markdown_table_to_html(table_lines))
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            out.append(f"<h4>{inline_markdown(stripped[4:].strip())}</h4>")
            i += 1
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            out.append(f"<h3>{inline_markdown(stripped[3:].strip())}</h3>")
            i += 1
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            out.append(f"<h2>{inline_markdown(stripped[2:].strip())}</h2>")
            i += 1
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            list_items.append(stripped[2:].strip())
            i += 1
            continue
        if set(stripped) <= {"_", "-"} and len(stripped) >= 8:
            flush_paragraph()
            flush_list()
            out.append("<div class='write-line'></div>")
            i += 1
            continue
        paragraph.append(line)
        i += 1
    flush_paragraph()
    flush_list()
    return "".join(out) or "<div class='empty'>（空）</div>"


def render_review(records: list[dict[str, Any]]) -> str:
    cards = []
    for item in records:
        record = item["rendered_record"]
        display = record["display_question"]
        page_figs = []
        for path in item.get("page_images") or []:
            abs_path = workspace_path(path)
            url = abs_path.resolve().as_uri()
            page_figs.append(f"<figure><a href='{html.escape(url)}' target='_blank'><img src='{html.escape(url)}'></a><figcaption>{html.escape(path)}</figcaption></figure>")
        cards.append(
            f"""
<section class="card">
  <h2>{html.escape(record['source_group_id'])} / {html.escape(record['source_packet_id'])} - {html.escape(record['render_status'])}</h2>
  <div class="grid">
    <div><h3>原页</h3><div class="pages">{''.join(page_figs)}</div></div>
    <div>
      <h3>格式还原题面</h3><pre>{html.escape(display.get('stem_markdown') or '')}</pre>
      <h3>格式还原答案</h3><pre>{html.escape(display.get('answer_markdown') or '')}</pre>
      <h3>Items</h3><pre>{html.escape(json.dumps(display.get('items') or [], ensure_ascii=False, indent=2))}</pre>
      <h3>原 standard_question.stem</h3><pre>{html.escape(item.get('source_stem') or '')}</pre>
      <h3>原 final_markdown</h3><pre>{html.escape(item.get('source_final_markdown') or '')}</pre>
      <h3>Validation</h3><pre>{html.escape(json.dumps(item.get('validation'), ensure_ascii=False, indent=2))}</pre>
      <h3>Admission Profile</h3><pre>{html.escape(json.dumps(record.get('admission_profile') or {}, ensure_ascii=False, indent=2))}</pre>
      <h3>Issues / Actions</h3><pre>{html.escape(json.dumps({'unresolved_issues': record.get('unresolved_issues'), 'normalization_actions': record.get('normalization_actions')}, ensure_ascii=False, indent=2))}</pre>
    </div>
  </div>
</section>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Question Render Normalizer Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:20px;line-height:1.45}}
.card{{border:1px solid #ddd;margin:18px 0;padding:14px}}
.grid{{display:grid;grid-template-columns:minmax(360px,42vw) 1fr;gap:16px;align-items:start}}
.pages{{display:flex;gap:12px;flex-wrap:wrap}}
figure{{margin:0;max-width:320px}}
img{{width:310px;border:1px solid #ccc;background:white}}
figcaption{{font-size:12px;word-break:break-all;color:#555}}
pre{{white-space:pre-wrap;background:#f7f7f7;padding:10px}}
</style>
<h1>Question Render Normalizer Review</h1>
<p>Node6b smoke output. This node restores display formatting only; it does not import Runtime payloads or write DB.</p>
{''.join(cards)}
"""


def render_final_review(records: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    cards = []
    for index, item in enumerate(records, start=1):
        record = item["rendered_record"]
        display = record["display_question"]
        status = record.get("render_status") or ""
        status_class = "ready" if status == "READY" else "review" if status == "NEEDS_REVIEW" else "other"
        page_figs = []
        for path in item.get("page_images") or []:
            abs_path = workspace_path(path)
            if not abs_path.exists():
                continue
            url = abs_path.resolve().as_uri()
            page_figs.append(
                f"<figure><a href='{html.escape(url)}' target='_blank'><img src='{html.escape(url)}'></a>"
                f"<figcaption>{html.escape(Path(path).name)}</figcaption></figure>"
            )
        issues = record.get("unresolved_issues") or []
        issues_html = ""
        if issues:
            issues_html = (
                "<details><summary>需要注意</summary>"
                f"<pre>{html.escape(json.dumps(issues, ensure_ascii=False, indent=2))}</pre></details>"
            )
        admission_profile = record.get("admission_profile") or {}
        admission_mode = str(admission_profile.get("admission_mode") or "")
        admission_html = (
            "<div class='admission'>"
            f"<b>入库画像：</b>{html.escape(admission_mode or '未生成')}<br>"
            f"<b>Builder 动作：</b>{html.escape(str(admission_profile.get('builder_action') or ''))}<br>"
            f"<b>原因：</b>{html.escape(str(admission_profile.get('reason') or ''))}"
            "</div>"
        )
        cards.append(
            f"""
<section class="card {status_class}">
  <div class="card-head">
    <div><span class="idx">#{index}</span> <strong>{html.escape(record.get('source_group_id') or '')}</strong>
      <span class="packet">{html.escape(record.get('source_packet_id') or '')}</span></div>
    <span class="badge {status_class}">{html.escape(status)}</span>
  </div>
  <div class="grid">
    <div>
      <h3>原页</h3>
      <div class="pages">{''.join(page_figs) or '<div class="empty">无原页图片</div>'}</div>
    </div>
    <div>
      {admission_html}
      <h3>最终题干</h3><div class="rendered">{markdown_to_html(display.get('stem_markdown') or '')}</div>
      <h3>最终答案</h3><div class="rendered">{markdown_to_html(display.get('answer_markdown') or '')}</div>
      <h3>最终解析</h3><div class="rendered">{markdown_to_html(display.get('analysis_markdown') or '')}</div>
      <h3>翻译/补充</h3><div class="rendered">{markdown_to_html(display.get('translation_markdown') or '')}</div>
      {issues_html}
      <details><summary>查看 Markdown 源码</summary>
        <h4>题干源码</h4><pre>{html.escape(display.get('stem_markdown') or '')}</pre>
        <h4>答案源码</h4><pre>{html.escape(display.get('answer_markdown') or '')}</pre>
        <h4>入库画像源码</h4><pre>{html.escape(json.dumps(admission_profile, ensure_ascii=False, indent=2))}</pre>
      </details>
    </div>
  </div>
</section>
"""
        )
    summary = payload.get("summary") or {}
    return f"""<!doctype html>
<meta charset="utf-8">
<title>最终题目验收</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f5f6f8;color:#202124;line-height:1.5}}
header{{position:sticky;top:0;background:white;border-bottom:1px solid #d8dde6;padding:14px 20px;z-index:2}}
h1{{font-size:20px;margin:0 0 6px}} .summary{{font-size:13px;color:#5f6368}}
.card{{margin:18px auto;padding:14px 16px;background:white;border:1px solid #d8dde6;border-radius:8px;max-width:1500px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.card-head{{display:flex;justify-content:space-between;gap:12px;align-items:center;border-bottom:1px solid #eef1f5;padding-bottom:10px;margin-bottom:12px}}
.idx{{color:#6b7280;margin-right:6px}} .packet{{color:#6b7280;font-size:12px;margin-left:8px}}
.badge{{font-size:12px;font-weight:700;border-radius:999px;padding:4px 10px}} .badge.ready{{background:#e7f6ed;color:#137333}} .badge.review{{background:#fff3d6;color:#8a5a00}} .badge.other{{background:#eee;color:#555}}
.grid{{display:grid;grid-template-columns:minmax(360px,42%) 1fr;gap:18px;align-items:start}}
h3{{font-size:14px;margin:10px 0 8px;color:#1f3b63}} h4{{font-size:14px;margin:12px 0 6px}}
.pages{{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}} figure{{margin:0 0 12px;max-width:320px}} img{{width:310px;border:1px solid #cfd6df;background:white}} figcaption{{font-size:12px;color:#6b7280;word-break:break-all;margin-top:4px}}
.rendered{{background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:10px;margin:0 0 12px}} .rendered p{{margin:0 0 8px}} .rendered h2,.rendered h3,.rendered h4{{color:#111827;margin:10px 0 8px}} .rendered ul{{margin:6px 0 10px 22px;padding:0}}
.admission{{background:#f8fafc;border:1px solid #d8dde6;border-radius:6px;padding:10px;margin:0 0 12px;font-size:13px;line-height:1.6}}
.md-table{{border-collapse:collapse;width:100%;margin:8px 0 12px;font-size:14px}} .md-table th,.md-table td{{border:1px solid #cfd6df;padding:7px 9px;vertical-align:top}} .md-table th{{background:#f3f6fa;text-align:left}}
.write-line{{height:18px;border-bottom:1px solid #4b5563;margin:8px 0}} pre{{white-space:pre-wrap;word-break:break-word;background:#fafafa;border:1px solid #e5e7eb;border-radius:6px;padding:10px;font-family:'Microsoft YaHei',Arial,sans-serif;font-size:14px}}
.empty{{color:#9aa0a6;background:#fafafa;border:1px dashed #d8dde6;padding:10px;border-radius:6px;margin-bottom:12px}} details{{margin-top:8px}} summary{{cursor:pointer;color:#5f6368;font-weight:700}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}} figure,img{{max-width:100%;width:100%}}}}
</style>
<header>
  <h1>最终题目验收</h1>
  <div class="summary">doc_id={html.escape(payload.get('doc_id') or '')} | records={summary.get('record_count')} | valid={summary.get('valid_count')} | status={html.escape(str(summary.get('render_status_counts')))}</div>
</header>
<main>{''.join(cards)}</main>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node6b_question_render_normalizer"]
    api_key = str(os.environ.get(config.get("api_key_env", "ARK_API_KEY")) or "").strip()
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')}")

    refined_payload = read_json(workspace_path(args.refined_packets_json))
    packets = refined_payload.get("refined_packets") or []
    projection_by_group: dict[str, dict[str, Any]] = {}
    if args.runtime_projection_plan_json:
        projection_payload = read_json(workspace_path(args.runtime_projection_plan_json))
        for projection in projection_payload.get("question_projections") or []:
            group_id = projection.get("source_group_id")
            if group_id:
                projection_by_group[group_id] = projection
        packets = [
            with_projection_context(packet, projection_by_group.get(packet.get("source_group_id")))
            for packet in packets
        ]
    selected = set(args.group_ids or [])
    if selected:
        packets = [packet for packet in packets if packet.get("source_group_id") in selected or packet.get("source_packet_id") in selected]
    if args.renderable_only:
        packets = [packet for packet in packets if is_renderable_question(packet)]
    if args.max_packets:
        packets = packets[: args.max_packets]

    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    def process_packet(packet: dict[str, Any]) -> dict[str, Any]:
        packet_dir = out_root / "records" / safe_id(packet.get("source_packet_id") or packet.get("source_group_id"))
        images = page_image_paths(packet)
        system_prompt = load_system_prompt_for_packet(node, packet)
        input_payload = build_input_payload(packet)
        user_prompt = render_template(
            user_template,
            {
                "prompt_version": PROMPT_VERSION,
                "doc_id": packet.get("doc_id"),
                "source_packet_id": packet.get("source_packet_id"),
                "source_group_id": packet.get("source_group_id"),
                "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            },
        )
        attempts: list[dict[str, Any]] = []
        try:
            model_result = call_model(config=config, node=node, system_prompt=system_prompt, user_prompt=user_prompt, image_paths=images, api_key=api_key)
            attempts.append(model_result)
            plan = repair_plan_shape(model_result["parsed"], packet)
            plan_validation = validate_render_plan(plan)
            if not plan_validation["valid"]:
                retry_prompt = (
                    user_prompt
                    + "\n\nRETRY_CONSTRAINT:\n"
                    + "Your previous response failed render instruction plan schema validation. "
                    + "Return one complete JSON object only using schema render_instruction_plan_v0.1. "
                    + "Do not output final student-facing prose. "
                    + f"Validation errors: {json.dumps(plan_validation['errors'], ensure_ascii=False)[:1200]}"
                )
                retry_result = call_model(config=config, node=node, system_prompt=system_prompt, user_prompt=retry_prompt, image_paths=images, api_key=api_key)
                attempts.append(retry_result)
                retry_plan = repair_plan_shape(retry_result["parsed"], packet)
                retry_plan_validation = validate_render_plan(retry_plan)
                if retry_plan_validation["valid"]:
                    user_prompt = retry_prompt
                    model_result = retry_result
                    plan = retry_plan
                    plan_validation = retry_plan_validation
            if not plan_validation["valid"]:
                plan = repair_plan_shape(None, packet, "Model render instruction plan failed schema validation; program renderer used baseline source-field copy.")
                plan_validation = validate_render_plan(plan)
            record = execute_render_plan(packet, plan)
            postprocess_rendered_record(record, packet)
            finalize_record_posture(packet, record)
        except Exception as exc:
            plan = repair_plan_shape(None, packet, f"model_call_failed: {type(exc).__name__}: {exc}")
            plan_validation = validate_render_plan(plan)
            record = repair_shape(
                {
                    "render_status": "NEEDS_REVIEW",
                    "display_question": {
                        "title": packet.get("source_packet_id") or "",
                        "stem_markdown": (packet.get("standard_question") or {}).get("stem") or "",
                        "answer_markdown": (packet.get("standard_question") or {}).get("answer") or "",
                        "analysis_markdown": (packet.get("standard_question") or {}).get("analysis") or "",
                        "translation_markdown": (packet.get("standard_question") or {}).get("translation") or "",
                        "items": [],
                        "rendering_blocks": [],
                    },
                    "unresolved_issues": [{"code": "planner_model_call_failed", "message": f"{type(exc).__name__}: {exc}", "source_refs": []}],
                    "render_instruction_plan": plan,
                },
                packet,
            )
            postprocess_rendered_record(record, packet)
            finalize_record_posture(packet, record)
            validation = validate_record(record, packet)
            write_text(packet_dir / "used_system_prompt.md", system_prompt)
            write_text(packet_dir / "used_user_prompt.md", user_prompt)
            write_json(packet_dir / "render_instruction_plan.json", plan)
            write_json(packet_dir / "render_instruction_plan_validation.json", plan_validation)
            write_json(packet_dir / "model_attempts_summary.json", [{"attempt": 1, "parsed": False, "parse_error": f"{type(exc).__name__}: {exc}"}])
            write_json(packet_dir / "rendered_question_record.json", record)
            write_json(packet_dir / "validation_report.json", validation)
            return {
                "source_packet_id": packet.get("source_packet_id"),
                "source_group_id": packet.get("source_group_id"),
                "render_status": record.get("render_status"),
                "admission_profile": record.get("admission_profile") or {},
                "parsed": False,
                "parse_error": f"{type(exc).__name__}: {exc}",
                "validation": validation,
                "latency_seconds": 0,
                "usage": {},
                "attempt_count": 1,
                "artifact_path": rel_workspace(packet_dir / "rendered_question_record.json"),
                "page_images": [rel_workspace(path) for path in images],
                "page_image_sha256": {rel_workspace(path): sha256_file(path) for path in images},
                "source_stem": (packet.get("standard_question") or {}).get("stem") or "",
                "source_final_markdown": packet.get("final_markdown") or "",
                "rendered_record": record,
            }
        validation = validate_record(record, packet)
        write_text(packet_dir / "used_system_prompt.md", system_prompt)
        write_text(packet_dir / "used_user_prompt.md", user_prompt)
        write_json(packet_dir / "request_messages.full.local.json", model_result["request_body"])
        write_json(packet_dir / "raw_response.json", model_result["raw_response"])
        write_text(packet_dir / "raw_content.txt", model_result["raw_content"])
        write_json(packet_dir / "render_instruction_plan.json", plan)
        write_json(packet_dir / "render_instruction_plan_validation.json", plan_validation)
        write_json(
            packet_dir / "model_attempts_summary.json",
            [
                {
                    "attempt": index + 1,
                    "parsed": attempt["parsed"] is not None,
                    "parse_error": attempt.get("parse_error"),
                    "latency_seconds": attempt.get("latency_seconds"),
                    "usage": attempt.get("raw_response", {}).get("usage", {}),
                }
                for index, attempt in enumerate(attempts)
            ],
        )
        write_json(packet_dir / "rendered_question_record.json", record)
        write_json(packet_dir / "validation_report.json", validation)
        return {
            "source_packet_id": packet.get("source_packet_id"),
            "source_group_id": packet.get("source_group_id"),
            "render_status": record.get("render_status"),
            "admission_profile": record.get("admission_profile") or {},
            "parsed": model_result["parsed"] is not None,
            "parse_error": model_result.get("parse_error"),
            "validation": validation,
            "latency_seconds": model_result["latency_seconds"],
            "usage": model_result["raw_response"].get("usage", {}),
            "attempt_count": len(attempts),
            "artifact_path": rel_workspace(packet_dir / "rendered_question_record.json"),
            "page_images": [rel_workspace(path) for path in images],
            "page_image_sha256": {rel_workspace(path): sha256_file(path) for path in images},
            "source_stem": (packet.get("standard_question") or {}).get("stem") or "",
            "source_final_markdown": packet.get("final_markdown") or "",
            "rendered_record": record,
        }
    records: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_by_packet = {executor.submit(process_packet, packet): packet for packet in packets}
        for future in concurrent.futures.as_completed(future_by_packet):
            records.append(future.result())
    records.sort(key=lambda item: (str(item.get("source_group_id") or ""), str(item.get("source_packet_id") or "")))
    payload = {
        "schema": "rendered_question_records_batch_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_version": PROMPT_VERSION,
        "doc_id": refined_payload.get("doc_id"),
        "records": records,
        "summary": {
            "record_count": len(records),
            "valid_count": sum(1 for record in records if record["validation"]["valid"]),
            "render_status_counts": {
                status: sum(1 for record in records if record["render_status"] == status)
                for status in sorted({record["render_status"] for record in records})
            },
            "admission_mode_counts": {
                mode: sum(
                    1
                    for record in records
                    if (
                        (record.get("admission_profile") or (record.get("rendered_record") or {}).get("admission_profile") or {})
                        .get("admission_mode")
                        == mode
                    )
                )
                for mode in sorted(
                    {
                        (record.get("admission_profile") or (record.get("rendered_record") or {}).get("admission_profile") or {}).get("admission_mode")
                        for record in records
                        if (record.get("admission_profile") or (record.get("rendered_record") or {}).get("admission_profile") or {}).get("admission_mode")
                    }
                )
            },
            "runtime_import_enabled": False,
            "database_write_enabled": False,
        },
    }
    summary = {
        "schema": "english_question_render_normalizer.run_summary",
        "generated_at": payload["generated_at"],
        "doc_id": payload["doc_id"],
        "prompt_version": PROMPT_VERSION,
        "out_dir": rel_workspace(out_root),
        **payload["summary"],
        "rendered_records_json": rel_workspace(out_root / "rendered_question_records.json"),
        "review_html": rel_workspace(out_root / "review.html"),
        "final_review_html": rel_workspace(out_root / "review_final_only.html"),
    }
    write_json(out_root / "rendered_question_records.json", payload)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(records))
    write_text(out_root / "review_final_only.html", render_final_review(records, payload))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--refined-packets-json", required=True)
    parser.add_argument("--runtime-projection-plan-json", default="")
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--renderable-only", action="store_true")
    parser.add_argument("--max-packets", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
