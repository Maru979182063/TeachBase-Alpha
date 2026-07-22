from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, render_template, workspace_path, write_json, write_text
from english_text_first_normalizer.model_api import call_model


REFINER_VERSION = "english_question_packet_refiner_v0.1_one_packet_model_refine_20260717"
FIELD_REF_KEYS = {
    "passage_refs": "passage",
    "stem_refs": "stem",
    "option_refs": "options",
    "answer_refs": "answer",
    "analysis_refs": "analysis",
    "translation_refs": "translation",
    "context_refs": "context",
    "example_refs": "examples",
    "rubric_refs": "rubric",
}
QUESTION_LIKE_CONTENT_KEYS = {"stem", "options", "answer", "analysis", "translation", "examples", "rubric"}
QUESTION_CLOSURE_CONTENT_KEYS = {"answer", "analysis"}
STATUS_BREAKDOWN_DEFAULT = {
    "content_status": "CLEAN",
    "source_status": "CLEAN",
    "projection_status": "READY",
    "risk_codes": [],
}


def packet_field_refs(packet: dict[str, Any]) -> dict[str, list[str]]:
    field_map = (packet.get("evidence") or {}).get("field_ref_map") or {}
    return {
        "passage_refs": list(field_map.get("passage") or []),
        "stem_refs": list(field_map.get("stem") or []) + list(field_map.get("instruction") or []),
        "option_refs": list(field_map.get("options") or []),
        "answer_refs": list(field_map.get("answer") or []),
        "analysis_refs": list(field_map.get("analysis") or []),
        "translation_refs": list(field_map.get("translation") or []),
        "context_refs": list(field_map.get("context") or []),
        "example_refs": list(field_map.get("examples") or []),
        "rubric_refs": list(field_map.get("rubric") or []),
    }


def empty_standard_question() -> dict[str, Any]:
    return {
        "title": "",
        "passage": "",
        "stem": "",
        "options": [],
        "answer": "",
        "analysis": "",
        "translation": "",
        "context": "",
        "examples": "",
        "rubric": "",
    }


def build_final_markdown(refined: dict[str, Any]) -> str:
    q = refined.get("standard_question") or {}
    parts: list[str] = []
    title = str(q.get("title") or "").strip()
    if title and title != refined.get("source_packet_id"):
        parts.append(f"# {title}")
    if q.get("passage"):
        parts.append(f"## 材料\n{str(q.get('passage')).strip()}")
    if q.get("context"):
        parts.append(f"## 上下文\n{str(q.get('context')).strip()}")
    if q.get("stem"):
        parts.append(f"## 题目\n{str(q.get('stem')).strip()}")
    options = q.get("options") or []
    if options:
        option_lines = []
        for item in options:
            label = str(item.get("label") or "").strip()
            text = str(item.get("text") or "").strip()
            option_lines.append(f"{label}. {text}".strip())
        parts.append("## 选项\n" + "\n".join(option_lines))
    if q.get("examples"):
        parts.append(f"## 例句/例子\n{str(q.get('examples')).strip()}")
    if q.get("answer"):
        parts.append(f"## 答案\n{str(q.get('answer')).strip()}")
    if q.get("analysis"):
        parts.append(f"## 解析\n{str(q.get('analysis')).strip()}")
    if q.get("translation"):
        parts.append(f"## 翻译\n{str(q.get('translation')).strip()}")
    if q.get("rubric"):
        parts.append(f"## 评分/要求\n{str(q.get('rubric')).strip()}")
    assets = refined.get("asset_refs") or {}
    surface_refs = assets.get("writing_surface_refs") or []
    visual_refs = assets.get("visual_refs") or []
    if surface_refs or visual_refs:
        parts.append(
            "## 视觉/作答面\n"
            + f"- writing_surface_refs: {json.dumps(surface_refs, ensure_ascii=False)}\n"
            + f"- visual_refs: {json.dumps(visual_refs, ensure_ascii=False)}"
        )
    return "\n\n".join(part for part in parts if part.strip()).strip()


def field_text(packet: dict[str, Any], key: str) -> str:
    value = (packet.get("content") or {}).get(key) or {}
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


def has_question_like_content(packet: dict[str, Any]) -> bool:
    return any(field_text(packet, key).strip() for key in QUESTION_LIKE_CONTENT_KEYS)


def has_question_closure_content(packet: dict[str, Any]) -> bool:
    return any(field_text(packet, key).strip() for key in QUESTION_CLOSURE_CONTENT_KEYS)


def relation_predicate(relation: dict[str, Any]) -> str:
    return str(relation.get("predicate") or relation.get("predicate_open_text") or "").strip().lower()


def preserved_rescue_blockers(packet: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    relations = packet.get("relations") or {}
    source_group_id = str(packet.get("source_group_id") or "")
    for relation in relations.get("outgoing") or []:
        predicate = relation_predicate(relation)
        if predicate == "is_child_of":
            blockers.append("outgoing_is_child_of")
    for relation in relations.get("incoming") or []:
        predicate = relation_predicate(relation)
        if predicate in {"is_child_of", "uses_context", "depends_on"}:
            object_group_id = str(relation.get("object_group_id") or "")
            if object_group_id == source_group_id:
                blockers.append(f"incoming_{predicate}_parent")
    if not has_question_closure_content(packet):
        blockers.append("missing_answer_or_analysis_closure")
    return sorted(set(blockers))


def should_refine_preserved_candidate(packet: dict[str, Any]) -> bool:
    return (
        packet.get("projection_status") == "PRESERVED_NON_DIRECT"
        and has_question_like_content(packet)
        and not preserved_rescue_blockers(packet)
    )


def warning_codes(refined: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for warning in refined.get("warnings") or []:
        if isinstance(warning, dict):
            code = str(warning.get("code") or "")
        else:
            code = str(warning or "")
        if code:
            codes.append(code)
    return codes


def compute_status_breakdown(refined: dict[str, Any]) -> dict[str, Any]:
    status = dict(STATUS_BREAKDOWN_DEFAULT)
    q = refined.get("standard_question") or {}
    missing = [str(item) for item in refined.get("missing_fields") or []]
    codes = warning_codes(refined)
    risk_codes = sorted(set(codes + [item for item in missing if "partial" in item.lower() or "truncated" in item.lower()]))

    if refined.get("refine_status") == "PRESERVED_NON_DIRECT":
        return {
            "content_status": "PRESERVED_SOURCE_ONLY",
            "source_status": "CLEAN",
            "projection_status": "PRESERVED_SOURCE_ONLY",
            "risk_codes": risk_codes,
        }

    has_core_text = bool(str(q.get("stem") or q.get("passage") or q.get("context") or "").strip())
    if not has_core_text:
        status["content_status"] = "BROKEN"
    elif any("partial" in item.lower() or "truncated" in item.lower() for item in missing + codes):
        status["content_status"] = "PARTIAL"

    lower_codes = " ".join(codes).lower()
    if "upstream_preserved_non_direct_refined" in codes:
        status["source_status"] = "RESCUED_FROM_UPSTREAM"
    elif "incomplete" in lower_codes or "truncated" in lower_codes or "missing_corresponding_answer" in lower_codes:
        status["source_status"] = "INCOMPLETE_SOURCE"
    elif "overlap" in lower_codes:
        status["source_status"] = "OVERLAP_WARNING"
    elif "mixed_open_status" in codes:
        status["source_status"] = "MIXED_WINDOW_STATUS"

    if status["content_status"] == "BROKEN":
        status["projection_status"] = "BLOCKED"
    elif status["content_status"] == "PARTIAL" or status["source_status"] in {"RESCUED_FROM_UPSTREAM", "INCOMPLETE_SOURCE"}:
        status["projection_status"] = "NEEDS_REVIEW"
    elif status["source_status"] in {"OVERLAP_WARNING", "MIXED_WINDOW_STATUS"}:
        status["projection_status"] = "READY_WITH_SOURCE_WARNINGS"
    status["risk_codes"] = risk_codes
    return status


def deterministic_preserve(packet: dict[str, Any], prompt_version: str, status: str, reason: str) -> dict[str, Any]:
    content = packet.get("content") or {}
    standard = empty_standard_question()
    for key in ["passage", "stem", "answer", "analysis", "translation", "context", "examples", "rubric"]:
        standard[key] = str((content.get(key) or {}).get("text") or "")
    standard["title"] = str(packet.get("packet_id") or "")
    refs = packet_field_refs(packet)
    refined = {
        "schema": "refined_question_packet_v0.1",
        "doc_id": packet.get("doc_id", ""),
        "source_packet_id": packet.get("packet_id", ""),
        "source_group_id": packet.get("source_group_id", ""),
        "prompt_version": prompt_version,
        "packet_family": packet.get("packet_family", "open"),
        "refine_status": status,
        "question_type": packet.get("packet_family", "open"),
        "final_markdown": "",
        "standard_question": standard,
        "source_refs": refs,
        "asset_refs": packet.get("asset_refs") or {"visual_refs": [], "writing_surface_refs": [], "page_image_refs": []},
        "missing_fields": list(packet.get("missing_fields") or []),
        "warnings": [
            {
                "code": "deterministic_preserve",
                "message": reason,
                "refs": [str(packet.get("packet_id", ""))],
            }
        ],
        "normalization_actions": [],
    }
    refined["final_markdown"] = build_final_markdown(refined)
    refined["status_breakdown"] = compute_status_breakdown(refined)
    return refined


def repair_refined_shape(refined: dict[str, Any], packet: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    """Fill contract defaults without rewriting model-produced question text."""
    repaired = dict(refined or {})
    repaired["schema"] = "refined_question_packet_v0.1"
    repaired["doc_id"] = packet.get("doc_id", "")
    repaired["source_packet_id"] = packet.get("packet_id", "")
    repaired["source_group_id"] = packet.get("source_group_id", "")
    repaired["prompt_version"] = prompt_version
    repaired.setdefault("packet_family", packet.get("packet_family", "open"))
    if repaired.get("refine_status") not in {"REFINED_READY", "REFINED_NEEDS_REVIEW", "PRESERVED_NON_DIRECT", "REFINE_FAILED"}:
        repaired["refine_status"] = "REFINED_NEEDS_REVIEW"
    repaired.setdefault("question_type", packet.get("packet_family", "open"))

    question = dict(repaired.get("standard_question") or {})
    for key, value in empty_standard_question().items():
        question.setdefault(key, value)
    if not isinstance(question.get("options"), list):
        question["options"] = []
    repaired["standard_question"] = question
    if not isinstance(repaired.get("final_markdown"), str) or not repaired.get("final_markdown", "").strip():
        repaired["final_markdown"] = build_final_markdown(repaired)

    packet_refs = packet_field_refs(packet)
    refs = dict(repaired.get("source_refs") or {})
    for ref_key, fallback_values in packet_refs.items():
        values = refs.get(ref_key)
        if not isinstance(values, list):
            refs[ref_key] = list(fallback_values)
    repaired["source_refs"] = refs

    repaired.setdefault("asset_refs", packet.get("asset_refs") or {"visual_refs": [], "writing_surface_refs": [], "page_image_refs": []})
    for array_key in ["missing_fields", "warnings", "normalization_actions"]:
        if not isinstance(repaired.get(array_key), list):
            repaired[array_key] = []
    repaired["status_breakdown"] = compute_status_breakdown(repaired)
    return repaired


def mark_refined_from_preserved_input(refined: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(refined)
    if repaired.get("refine_status") in {"REFINED_READY", "PRESERVED_NON_DIRECT"}:
        repaired["refine_status"] = "REFINED_NEEDS_REVIEW"
    warnings = list(repaired.get("warnings") or [])
    warnings.append(
        {
            "code": "upstream_preserved_non_direct_refined",
            "message": "Input was marked PRESERVED_NON_DIRECT upstream, but structured question-like fields were present, so Node5 refined it conservatively.",
            "refs": [str(repaired.get("source_packet_id") or "")],
        }
    )
    repaired["warnings"] = warnings
    repaired["final_markdown"] = build_final_markdown(repaired)
    repaired["status_breakdown"] = compute_status_breakdown(repaired)
    return repaired


def validate_refined(refined: dict[str, Any], packet: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if refined.get("schema") != "refined_question_packet_v0.1":
        errors.append({"path": "$.schema", "message": "invalid schema"})
    for key, expected in [
        ("doc_id", packet.get("doc_id")),
        ("source_packet_id", packet.get("packet_id")),
        ("source_group_id", packet.get("source_group_id")),
        ("prompt_version", prompt_version),
    ]:
        if refined.get(key) != expected:
            errors.append({"path": f"$.{key}", "message": "identifier mismatch"})
    if refined.get("refine_status") not in {"REFINED_READY", "REFINED_NEEDS_REVIEW", "PRESERVED_NON_DIRECT", "REFINE_FAILED"}:
        errors.append({"path": "$.refine_status", "message": "invalid refine_status"})
    if not isinstance(refined.get("final_markdown"), str):
        errors.append({"path": "$.final_markdown", "message": "final_markdown must be string"})
    breakdown = refined.get("status_breakdown")
    if not isinstance(breakdown, dict):
        errors.append({"path": "$.status_breakdown", "message": "missing status_breakdown"})
    else:
        for key in ["content_status", "source_status", "projection_status", "risk_codes"]:
            if key not in breakdown:
                errors.append({"path": f"$.status_breakdown.{key}", "message": "missing key"})
    if (
        packet.get("projection_status") == "PRESERVED_NON_DIRECT"
        and not has_question_like_content(packet)
        and refined.get("refine_status") != "PRESERVED_NON_DIRECT"
    ):
        errors.append({"path": "$.refine_status", "message": "non-direct packet without question-like fields must remain PRESERVED_NON_DIRECT"})
    question = refined.get("standard_question") or {}
    for key in empty_standard_question():
        if key not in question:
            errors.append({"path": f"$.standard_question.{key}", "message": "missing key"})
    if not isinstance(question.get("options"), list):
        errors.append({"path": "$.standard_question.options", "message": "options must be array"})
    refs = refined.get("source_refs") or {}
    allowed_refs = set(packet.get("evidence", {}).get("source_refs") or [])
    allowed_refs.update(ref for values in packet_field_refs(packet).values() for ref in values)
    for ref_key in FIELD_REF_KEYS:
        values = refs.get(ref_key)
        if not isinstance(values, list):
            errors.append({"path": f"$.source_refs.{ref_key}", "message": "source refs field must be array"})
            continue
        for ref in values:
            if ref not in allowed_refs:
                errors.append({"path": f"$.source_refs.{ref_key}", "message": f"invented source ref {ref}"})
    return {"valid": not errors, "errors": errors}


def reconcile_refine_status(refined: dict[str, Any]) -> dict[str, Any]:
    """Make the final status obey the structured status breakdown."""
    if refined.get("refine_status") in {"PRESERVED_NON_DIRECT", "REFINE_FAILED"}:
        return refined
    breakdown = refined.get("status_breakdown") or {}
    content_status = breakdown.get("content_status")
    source_status = breakdown.get("source_status")
    projection_status = breakdown.get("projection_status")
    ready_allowed = (
        content_status == "CLEAN"
        and source_status == "CLEAN"
        and projection_status == "READY"
    )
    if ready_allowed:
        refined["refine_status"] = "REFINED_READY"
        return refined

    if refined.get("refine_status") == "REFINED_READY":
        refined["refine_status"] = "REFINED_NEEDS_REVIEW"
        warnings = refined.setdefault("warnings", [])
        warnings.append(
            "Local status gate downgraded READY because status_breakdown is not fully clean/ready."
        )
    return refined


def refine_one(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    packet: dict[str, Any],
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
) -> dict[str, Any]:
    packet_id = packet["packet_id"]
    packet_dir = out_dir / "packets" / packet_id
    upstream_preserved = packet.get("projection_status") == "PRESERVED_NON_DIRECT"
    rescue_blockers = preserved_rescue_blockers(packet) if upstream_preserved else []
    refine_preserved_candidate = should_refine_preserved_candidate(packet)
    if upstream_preserved and not refine_preserved_candidate:
        reason = "Source packet is non-direct; preserved without model refinement."
        if has_question_like_content(packet) and rescue_blockers:
            reason += " Rescue blocked by relation/closure gate: " + ", ".join(rescue_blockers)
        refined = deterministic_preserve(packet, node["prompt_version"], "PRESERVED_NON_DIRECT", reason)
        validation = validate_refined(refined, packet, node["prompt_version"])
        write_json(packet_dir / "input_packet_candidate.json", packet)
        write_json(packet_dir / "refined_question_packet.json", refined)
        write_json(packet_dir / "validation_report.json", validation)
        return {
            "packet_id": packet_id,
            "source_group_id": packet.get("source_group_id"),
            "model_called": False,
            "parsed": True,
            "refine_status": refined["refine_status"],
            "validation": validation,
            "artifact_path": rel_workspace(packet_dir / "refined_question_packet.json"),
        }

    input_payload = {
        "packet_candidate": packet,
        "required_source_refs": packet_field_refs(packet),
            "refiner_policy": {
            "one_packet_only": True,
            "exact_source_only": True,
            "do_not_invent_missing_fields": True,
            "upstream_preserved_non_direct": upstream_preserved,
            "question_like_structured_signal": refine_preserved_candidate,
            "preserved_rescue_blockers": rescue_blockers,
            "if_upstream_preserved_non_direct_refined": "Return REFINED_NEEDS_REVIEW unless the source should still be PRESERVED_NON_DIRECT.",
        },
    }
    user_prompt = render_template(
        user_template,
        {
            "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            "doc_id": packet.get("doc_id", ""),
            "source_packet_id": packet_id,
            "source_group_id": packet.get("source_group_id", ""),
            "prompt_version": node["prompt_version"],
        },
    )
    def process_model_result(result: dict[str, Any]) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        candidate = result["parsed"]
        candidate_parsed = candidate is not None
        if candidate is None:
            candidate = deterministic_preserve(packet, node["prompt_version"], "REFINE_FAILED", result["parse_error"])
        else:
            candidate = repair_refined_shape(candidate, packet, node["prompt_version"])
            if refine_preserved_candidate:
                candidate = mark_refined_from_preserved_input(candidate)
            candidate = reconcile_refine_status(candidate)
        candidate_validation = validate_refined(candidate, packet, node["prompt_version"])
        return candidate, candidate_parsed, candidate_validation

    attempts: list[dict[str, Any]] = []
    model_result = call_model(config, node, system_prompt, user_prompt, api_key)
    attempts.append(model_result)
    refined, parsed, validation = process_model_result(model_result)
    if refined.get("refine_status") == "REFINE_FAILED" or not validation["valid"]:
        retry_reason = model_result.get("parse_error") or json.dumps(validation.get("errors") or [], ensure_ascii=False)
        retry_prompt = (
            user_prompt
            + "\n\nRETRY_CONSTRAINT:\n"
            + "Your previous response failed local JSON/schema/source-ref validation. "
            + "Return one complete JSON object only. Do not invent source refs. "
            + f"Failure detail: {retry_reason[:1000]}"
        )
        retry_result = call_model(config, node, system_prompt, retry_prompt, api_key)
        attempts.append(retry_result)
        retry_refined, retry_parsed, retry_validation = process_model_result(retry_result)
        if retry_refined.get("refine_status") != "REFINE_FAILED" and retry_validation["valid"]:
            model_result = retry_result
            user_prompt = retry_prompt
            refined = retry_refined
            parsed = retry_parsed
            validation = retry_validation
        else:
            write_json(packet_dir / "invalid_model_output.json", refined)
            refined = deterministic_preserve(packet, node["prompt_version"], "REFINE_FAILED", "Model output failed local validation after retry.")
            validation = validate_refined(refined, packet, node["prompt_version"])

    write_json(packet_dir / "input_packet_candidate.json", packet)
    write_text(packet_dir / "used_system_prompt.md", system_prompt)
    write_text(packet_dir / "used_user_prompt.md", user_prompt)
    write_json(packet_dir / "request_messages.full.local.json", model_result["request_body"])
    write_json(packet_dir / "raw_response.json", model_result["raw_response"])
    write_text(packet_dir / "raw_content.txt", model_result["raw_content"])
    write_json(
        packet_dir / "model_attempts_summary.json",
        [
            {
                "attempt": idx + 1,
                "parsed": result["parsed"] is not None,
                "parse_error": result.get("parse_error"),
                "latency_seconds": result.get("latency_seconds"),
                "usage": result.get("raw_response", {}).get("usage", {}),
            }
            for idx, result in enumerate(attempts)
        ],
    )
    write_json(packet_dir / "refined_question_packet.json", refined)
    write_json(packet_dir / "validation_report.json", validation)
    return {
        "packet_id": packet_id,
        "source_group_id": packet.get("source_group_id"),
        "model_called": True,
        "parsed": parsed,
        "refine_status": refined["refine_status"],
        "validation": validation,
        "artifact_path": rel_workspace(packet_dir / "refined_question_packet.json"),
        "usage": model_result["raw_response"].get("usage", {}),
        "latency_seconds": model_result["latency_seconds"],
    }


def render_review(refined_packets: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    cards = []
    for packet in refined_packets:
        q = packet["standard_question"]
        warnings = html.escape(json.dumps(packet.get("warnings") or [], ensure_ascii=False, indent=2))
        refs = html.escape(json.dumps(packet.get("source_refs") or {}, ensure_ascii=False, indent=2))
        assets = html.escape(json.dumps(packet.get("asset_refs") or {}, ensure_ascii=False, indent=2))
        status_html = html.escape(json.dumps(packet.get("status_breakdown") or {}, ensure_ascii=False, indent=2))
        final_markdown = html.escape(packet.get("final_markdown") or "")
        asset_refs = packet.get("asset_refs") or {}
        surface_refs = asset_refs.get("writing_surface_refs") or []
        visual_refs = asset_refs.get("visual_refs") or []
        page_images = asset_refs.get("page_image_refs") or []
        surface_summary = ""
        if surface_refs or visual_refs or page_images:
            thumbs = []
            for page_ref in page_images[:4]:
                path = page_ref.get("path") if isinstance(page_ref, dict) else ""
                if path:
                    try:
                        img_src = workspace_path(path).as_uri()
                    except ValueError:
                        img_src = html.escape(path)
                    thumbs.append(
                        f"<figure><img src='{html.escape(img_src)}'><figcaption>page {html.escape(str(page_ref.get('page','')))}</figcaption></figure>"
                    )
            surface_summary = f"""
  <section class="surface">
    <h4>visual/writing surface（视觉/作答面证据）</h4>
    <p><b>writing_surface_refs（作答面引用）</b>: {html.escape(json.dumps(surface_refs, ensure_ascii=False))}</p>
    <p><b>visual_refs（题卡/表格/图示引用）</b>: {html.escape(json.dumps(visual_refs, ensure_ascii=False))}</p>
    <div class="thumbs">{''.join(thumbs)}</div>
  </section>
"""
        options = "\n".join(f"{item.get('label','')}. {item.get('text','')}" for item in q.get("options", []))
        cards.append(
            f"""
<article class="card">
  <h2>{html.escape(packet['source_packet_id'])} <small>{html.escape(packet['refine_status'])} / {html.escape(packet['packet_family'])}</small></h2>
  <p><b>question_type（题型）</b>: {html.escape(packet.get('question_type',''))}</p>
  <section class="final"><h4>final_markdown（成品题目 Markdown）</h4><pre>{final_markdown}</pre></section>
  <details open><summary>status_breakdown（状态分流）</summary><pre>{status_html}</pre></details>
  <section><h4>passage（文章/材料）</h4><pre>{html.escape(q.get('passage',''))}</pre></section>
  <section><h4>stem（题干）</h4><pre>{html.escape(q.get('stem',''))}</pre></section>
  <section><h4>options（选项）</h4><pre>{html.escape(options)}</pre></section>
  <section><h4>answer（答案）</h4><pre>{html.escape(q.get('answer',''))}</pre></section>
  <section><h4>analysis（解析）</h4><pre>{html.escape(q.get('analysis',''))}</pre></section>
  <section><h4>translation（翻译）</h4><pre>{html.escape(q.get('translation',''))}</pre></section>
  <section><h4>context（上下文）</h4><pre>{html.escape(q.get('context',''))}</pre></section>
  <section><h4>examples（例句/例子）</h4><pre>{html.escape(q.get('examples',''))}</pre></section>
  {surface_summary}
  <details><summary>asset_refs（资产引用）</summary><pre>{assets}</pre></details>
  <details><summary>source_refs（证据引用）</summary><pre>{refs}</pre></details>
  <details><summary>warnings（警告）</summary><pre>{warnings}</pre></details>
</article>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>English Refined Question Packet Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f7f9;color:#202124;line-height:1.45}}
.card{{background:white;border:1px solid #d8dce2;border-radius:8px;padding:16px;margin:18px 0}}
small{{color:#5f6368;font-weight:400}}
pre{{white-space:pre-wrap;background:#f8f9fb;border:1px solid #e2e5ea;border-radius:6px;padding:10px;overflow:auto}}
section{{border-top:1px solid #eef0f3;padding-top:8px;margin-top:8px}}
.surface{{border:1px solid #cbd5e1;background:#f8fafc;border-radius:6px;padding:10px;margin-top:12px}}
.final{{border:1px solid #b7d4ff;background:#f8fbff;border-radius:6px;padding:10px;margin-top:12px}}
.thumbs{{display:flex;gap:12px;flex-wrap:wrap}}
figure{{margin:0;max-width:260px}}
img{{max-width:260px;max-height:360px;border:1px solid #ddd;background:white}}
figcaption{{font-size:12px;color:#64748b}}
</style>
<h1>Node5 QuestionPacketRefiner Review</h1>
<p>doc_id=<code>{html.escape(summary['doc_id'])}</code>, packets=<code>{summary['packet_count']}</code>, model_called=<code>{summary['model_called_count']}</code>, refined_ready=<code>{summary['refined_ready_count']}</code>, needs_review=<code>{summary['needs_review_count']}</code>, preserved=<code>{summary['preserved_non_direct_count']}</code>, failed=<code>{summary['refine_failed_count']}</code></p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node5_question_packet_refiner"]
    api_key = os.environ.get(config.get("api_key_env", "ARK_API_KEY"))
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')}")

    packet_payload = read_json(workspace_path(args.question_packet_candidates_json))
    doc_id = args.doc_id or packet_payload["doc_id"]
    packets = packet_payload.get("packet_candidates") or []
    selected_ids = set(args.packet_ids or [])
    if selected_ids:
        packets = [packet for packet in packets if packet.get("packet_id") in selected_ids or packet.get("source_group_id") in selected_ids]
    if args.max_packets:
        packets = packets[: args.max_packets]

    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")

    records = []
    refined_packets = []
    max_workers = max(1, int(args.max_workers or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_by_packet = {
            executor.submit(
                refine_one,
                config=config,
                node=node,
                packet=packet,
                system_prompt=system_prompt,
                user_template=user_template,
                api_key=api_key,
                out_dir=out_root,
            ): packet
            for packet in packets
        }
        for future in concurrent.futures.as_completed(future_by_packet):
            records.append(future.result())
    records.sort(key=lambda item: item["packet_id"])
    for record in records:
        refined_packets.append(read_json(workspace_path(record["artifact_path"])))

    summary_counts = {
        "packet_count": len(refined_packets),
        "model_called_count": sum(1 for record in records if record["model_called"]),
        "refined_ready_count": sum(1 for packet in refined_packets if packet["refine_status"] == "REFINED_READY"),
        "needs_review_count": sum(1 for packet in refined_packets if packet["refine_status"] == "REFINED_NEEDS_REVIEW"),
        "preserved_non_direct_count": sum(1 for packet in refined_packets if packet["refine_status"] == "PRESERVED_NON_DIRECT"),
        "refine_failed_count": sum(1 for packet in refined_packets if packet["refine_status"] == "REFINE_FAILED"),
    }
    payload = {
        "schema": "refined_question_packets_batch_v0.1",
        "doc_id": doc_id,
        "refiner_version": REFINER_VERSION,
        "refined_packets": refined_packets,
        "summary": summary_counts,
    }
    summary = {
        "schema": "english_question_packet_refiner.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node5_question_packet_refiner",
        "doc_id": doc_id,
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "question_packet_candidates_json": rel_workspace(workspace_path(args.question_packet_candidates_json)),
        "out_dir": rel_workspace(out_root),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": records,
        **summary_counts,
        "refined_packets_json": rel_workspace(out_root / "refined_question_packets.json"),
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "refined_question_packets.json", payload)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(refined_packets, summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--question-packet-candidates-json", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--packet-ids", nargs="*", default=[])
    parser.add_argument("--max-packets", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
