from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
REFINER_VERSION = "docx_math_question_refiner_v0.1_strict_fields_with_repair_20260717"
SCHEMA = "docx_math_refined_question_packet_v0.1"
ALLOWED_QUESTION_TYPES = {"single_choice", "multiple_choice", "fill_blank", "solution", "composite"}
CHOICE_QUESTION_TYPES = {"single_choice", "multiple_choice"}
ALLOWED_SOLUTION_POLICIES = {"required", "absent_expected", "partial_solution_expected", "unknown"}

FIELD_REF_KEYS = {
    "context": "context_refs",
    "stem": "stem_refs",
    "subquestions": "subquestion_refs",
    "options": "option_refs",
    "answer": "answer_refs",
    "explanation": "explanation_refs",
    "teaching_note": "teaching_note_refs",
    "assets": "asset_block_refs",
    "other_evidence": "other_evidence_refs",
}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value or "")).strip("_") or "doc"


def render_template(text: str, values: dict[str, Any]) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = str(text or "").strip()
    try:
        return json.loads(stripped), ""
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), ""
            except json.JSONDecodeError as nested:
                return None, str(nested)
        return None, str(exc)


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if isinstance(item, str) and item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def strip_context_assets(markdown: str) -> str:
    return re.sub(r"!\[[^\]]*\]\(asset://[^)]+\)", "", str(markdown or "")).strip()


def compact_field(field: dict[str, Any], *, strip_assets: bool = False) -> dict[str, Any]:
    markdown = str(field.get("markdown") or "")
    if strip_assets:
        markdown = strip_context_assets(markdown)
    return {
        "block_ids": list(field.get("block_ids") or []),
        "markdown": markdown,
        "formula_count": int(field.get("formula_count") or 0),
        "asset_ids": [str(asset.get("asset_id") or "") for asset in field.get("asset_refs") or [] if asset.get("asset_id")],
    }


def draft_allowed_refs(draft: dict[str, Any]) -> set[str]:
    refs = set(str(ref) for ref in draft.get("source_refs") or [])
    for field in (draft.get("fields") or {}).values():
        refs.update(str(ref) for ref in field.get("block_ids") or [])
    return refs


def draft_allowed_asset_ids(draft: dict[str, Any]) -> set[str]:
    ids = set(str(asset.get("asset_id") or "") for asset in draft.get("asset_refs") or [] if asset.get("asset_id"))
    for field in (draft.get("fields") or {}).values():
        ids.update(str(asset.get("asset_id") or "") for asset in field.get("asset_refs") or [] if asset.get("asset_id"))
    return ids


def required_source_refs(draft: dict[str, Any]) -> dict[str, list[str]]:
    fields = draft.get("fields") or {}
    refs: dict[str, list[str]] = {}
    for field_name, ref_key in FIELD_REF_KEYS.items():
        refs[ref_key] = list((fields.get(field_name) or {}).get("block_ids") or [])
    return refs


def build_model_input(draft: dict[str, Any]) -> dict[str, Any]:
    fields = draft.get("fields") or {}
    return {
        "draft_id": draft.get("draft_id"),
        "doc_id": draft.get("doc_id"),
        "source_group_id": draft.get("source_group_id"),
        "record_kind": draft.get("record_kind"),
        "builder_status": draft.get("builder_status"),
        "solution_policy": draft.get("solution_policy"),
        "fields": {
            "context": compact_field(fields.get("context") or {}, strip_assets=True),
            "stem": compact_field(fields.get("stem") or {}),
            "subquestions": compact_field(fields.get("subquestions") or {}),
            "options": compact_field(fields.get("options") or {}),
            "answer": compact_field(fields.get("answer") or {}),
            "explanation": compact_field(fields.get("explanation") or {}),
            "teaching_note": compact_field(fields.get("teaching_note") or {}),
            "other_evidence": compact_field(fields.get("other_evidence") or {}),
        },
        "asset_refs": draft.get("asset_refs") or [],
        "source_refs": draft.get("source_refs") or [],
        "required_source_refs": required_source_refs(draft),
        "upstream_warnings": draft.get("warnings") or [],
        "refiner_policy": {
            "one_draft_only": True,
            "may_clean_markdown": True,
            "may_repair_obvious_formula_markup": True,
            "may_reorganize_within_same_draft": True,
            "must_preserve_meaning": True,
            "must_not_invent_missing_answer": True,
            "must_not_invent_block_or_asset_refs": True,
        },
    }


def empty_refined(draft: dict[str, Any], prompt_version: str, status: str, reason: str) -> dict[str, Any]:
    fields = draft.get("fields") or {}
    stem = str((fields.get("stem") or {}).get("markdown") or "")
    subs_md = str((fields.get("subquestions") or {}).get("markdown") or "")
    answer = str((fields.get("answer") or {}).get("markdown") or "")
    explanation = str((fields.get("explanation") or {}).get("markdown") or "")
    teaching = str((fields.get("teaching_note") or {}).get("markdown") or "")
    context = strip_context_assets(str((fields.get("context") or {}).get("markdown") or ""))
    render = "\n\n".join(part for part in [stem, subs_md, answer, explanation, teaching] if part.strip())
    warnings = list(draft.get("warnings") or [])
    warnings.append({"code": "deterministic_preserve", "message": reason, "refs": [str(draft.get("draft_id") or "")]})
    refined = {
        "schema": SCHEMA,
        "doc_id": draft.get("doc_id", ""),
        "source_draft_id": draft.get("draft_id", ""),
        "source_group_id": draft.get("source_group_id", ""),
        "prompt_version": prompt_version,
        "refine_status": status,
        "question_type": "solution",
        "solution_policy": draft.get("solution_policy") if draft.get("solution_policy") in ALLOWED_SOLUTION_POLICIES else "unknown",
        "standard_question": {
            "title": "",
            "stem_md": stem,
            "subquestions": [{"label": "", "markdown": subs_md}] if subs_md.strip() else [],
            "options": [],
            "answer_md": answer,
            "explanation_md": explanation,
            "teaching_note_md": teaching,
            "context_md": context,
            "render_markdown": render,
        },
        "condition_groups": [],
        "source_refs": required_source_refs(draft),
        "asset_refs": {"visual_refs": draft.get("asset_refs") or []},
        "missing_fields": [],
        "warnings": warnings,
        "normalization_actions": [],
    }
    apply_latex_json_escape_gate(refined)
    apply_solution_policy_gate(refined)
    refined["status_breakdown"] = compute_status(refined)
    return refined


def repair_shape(refined: dict[str, Any], draft: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    fixed = dict(refined or {})
    fixed["schema"] = SCHEMA
    fixed["doc_id"] = draft.get("doc_id", "")
    fixed["source_draft_id"] = draft.get("draft_id", "")
    fixed["source_group_id"] = draft.get("source_group_id", "")
    fixed["prompt_version"] = prompt_version
    if fixed.get("refine_status") not in {"REFINED_READY", "REFINED_NEEDS_REVIEW", "REFINE_FAILED"}:
        fixed["refine_status"] = "REFINED_NEEDS_REVIEW"
    fixed.setdefault("question_type", "solution")
    fixed.setdefault("solution_policy", draft.get("solution_policy", "unknown"))
    q = dict(fixed.get("standard_question") or {})
    for key, value in {
        "title": "",
        "stem_md": "",
        "subquestions": [],
        "options": [],
        "answer_md": "",
        "explanation_md": "",
        "teaching_note_md": "",
        "context_md": "",
        "render_markdown": "",
    }.items():
        q.setdefault(key, value)
    if not isinstance(q.get("subquestions"), list):
        q["subquestions"] = []
    if not isinstance(q.get("options"), list):
        q["options"] = []
    fixed["standard_question"] = q
    if not isinstance(fixed.get("condition_groups"), list):
        fixed["condition_groups"] = []
    refs = dict(fixed.get("source_refs") or {})
    for key, values in required_source_refs(draft).items():
        if not isinstance(refs.get(key), list):
            refs[key] = list(values)
    fixed["source_refs"] = refs
    assets = dict(fixed.get("asset_refs") or {})
    if not isinstance(assets.get("visual_refs"), list):
        assets["visual_refs"] = draft.get("asset_refs") or []
    fixed["asset_refs"] = assets
    for key in ["missing_fields", "warnings", "normalization_actions"]:
        if not isinstance(fixed.get(key), list):
            fixed[key] = []
    apply_latex_json_escape_gate(fixed)
    apply_solution_policy_gate(fixed)
    fixed["status_breakdown"] = compute_status(fixed)
    return fixed


def warning_codes(refined: dict[str, Any]) -> list[str]:
    return [str(w.get("code") or "") for w in refined.get("warnings") or [] if isinstance(w, dict) and w.get("code")]


SOLUTION_ABSENT_FIELDS = {
    "answer",
    "answer_md",
    "explanation",
    "explanation_md",
    "solution",
    "solution_md",
    "analysis",
    "analysis_md",
}


SOLUTION_ABSENT_WARNING_CODES = {
    "MISSING_ANSWER",
    "MISSING_EXPECTED_CONTENT",
    "MISSING_REQUIRED_CONTENT",
}


def is_solution_absence_warning(warning: Any) -> bool:
    if not isinstance(warning, dict):
        return False
    code = str(warning.get("code") or "")
    message = str(warning.get("message") or "").lower()
    if code not in SOLUTION_ABSENT_WARNING_CODES:
        return False
    return any(term in message for term in ["answer", "explanation", "solution", "analysis"])


LATEX_CONTROL_ESCAPE_MAP = {
    "\t": "\\t",
    "\f": "\\f",
    "\b": "\\b",
    "\r": "\\r",
    "\v": "\\v",
}


def repair_latex_control_escapes(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        repaired = value
        count = 0
        for control, replacement in LATEX_CONTROL_ESCAPE_MAP.items():
            hits = repaired.count(control)
            if hits:
                repaired = repaired.replace(control, replacement)
                count += hits
        return repaired, count
    if isinstance(value, list):
        total = 0
        repaired_items = []
        for item in value:
            repaired, count = repair_latex_control_escapes(item)
            repaired_items.append(repaired)
            total += count
        return repaired_items, total
    if isinstance(value, dict):
        total = 0
        repaired_dict: dict[str, Any] = {}
        for key, item in value.items():
            repaired, count = repair_latex_control_escapes(item)
            repaired_dict[key] = repaired
            total += count
        return repaired_dict, total
    return value, 0


def apply_latex_json_escape_gate(refined: dict[str, Any]) -> None:
    repaired, count = repair_latex_control_escapes(refined)
    if count <= 0 or not isinstance(repaired, dict):
        return
    refined.clear()
    refined.update(repaired)
    actions = list(refined.get("normalization_actions") or [])
    actions.append(
        {
            "action": "repair_latex_json_control_escapes",
            "message": "模型 JSON 中的单反斜杠 LaTeX 被解析为控制字符，已恢复为 LaTeX 命令前缀。",
            "replacement_count": count,
        }
    )
    refined["normalization_actions"] = actions


def apply_solution_policy_gate(refined: dict[str, Any]) -> None:
    if refined.get("solution_policy") != "absent_expected":
        return
    missing = [str(item) for item in refined.get("missing_fields") or []]
    kept_missing = [item for item in missing if item not in SOLUTION_ABSENT_FIELDS]
    filtered_missing = len(kept_missing) != len(missing)
    warnings = list(refined.get("warnings") or [])
    kept_warnings = [warning for warning in warnings if not is_solution_absence_warning(warning)]
    filtered_warnings = len(kept_warnings) != len(warnings)
    if filtered_missing or filtered_warnings:
        actions = list(refined.get("normalization_actions") or [])
        actions.append(
            {
                "action": "apply_absent_expected_solution_policy",
                "message": "原卷/无解答来源允许答案和解析缺失；不把该类缺失降级为 needs_review。",
                "removed_missing_fields": [item for item in missing if item not in kept_missing],
                "removed_warning_count": len(warnings) - len(kept_warnings),
            }
        )
        refined["normalization_actions"] = actions
    refined["missing_fields"] = kept_missing
    refined["warnings"] = kept_warnings
    q = refined.get("standard_question") or {}
    has_core = bool(str(q.get("stem_md") or "").strip() or q.get("subquestions"))
    if has_core and not kept_missing and refined.get("refine_status") == "REFINED_NEEDS_REVIEW":
        refined["refine_status"] = "REFINED_READY"


def compute_status(refined: dict[str, Any]) -> dict[str, Any]:
    status = {
        "content_status": "CLEAN",
        "source_status": "CLEAN",
        "projection_status": "READY",
        "risk_codes": [],
    }
    q = refined.get("standard_question") or {}
    codes = warning_codes(refined)
    missing = [str(item) for item in refined.get("missing_fields") or []]
    risks = sorted(set(codes + missing))
    has_core = bool(str(q.get("stem_md") or "").strip() or q.get("subquestions"))
    if refined.get("refine_status") == "REFINE_FAILED":
        status.update({"content_status": "BROKEN", "source_status": "MODEL_FAILED", "projection_status": "BLOCKED"})
    elif not has_core:
        status.update({"content_status": "BROKEN", "projection_status": "BLOCKED"})
    elif refined.get("refine_status") == "REFINED_NEEDS_REVIEW" or missing:
        status.update({"content_status": "PARTIAL", "projection_status": "NEEDS_REVIEW"})
    if any(code.startswith("missing_") for code in codes + missing):
        status["source_status"] = "INCOMPLETE_SOURCE"
    elif codes:
        status["source_status"] = "SOURCE_WARNINGS"
        if status["projection_status"] == "READY":
            status["projection_status"] = "READY_WITH_WARNINGS"
    status["risk_codes"] = risks
    return status


def extract_asset_tokens(text: str) -> set[str]:
    return set(re.findall(r"asset://([A-Za-z0-9_\\-]+)", str(text or "")))


def refined_text_chunks(refined: dict[str, Any]) -> list[str]:
    q = refined.get("standard_question") or {}
    chunks = [
        str(q.get("title") or ""),
        str(q.get("stem_md") or ""),
        str(q.get("answer_md") or ""),
        str(q.get("explanation_md") or ""),
        str(q.get("teaching_note_md") or ""),
        str(q.get("context_md") or ""),
        str(q.get("render_markdown") or ""),
    ]
    chunks.extend(str(item.get("markdown") or "") for item in q.get("subquestions") or [] if isinstance(item, dict))
    chunks.extend(str(item.get("markdown") or "") for item in q.get("options") or [] if isinstance(item, dict))
    chunks.extend(str(item.get("markdown") or "") for item in refined.get("condition_groups") or [] if isinstance(item, dict))
    return chunks


def markdown_risk_errors(refined: dict[str, Any]) -> list[dict[str, str]]:
    chunks = refined_text_chunks(refined)
    text = "\n".join(chunks)
    checks = {
        "bare_sqrt_command": r"(?<!\\)\bsqrt\s*\{",
        "bare_frac_command": r"(?<!\\)\bfrac\s*\{",
        "bare_times_command": r"(?<!\\)\btimes\b",
        "bare_div_command": r"(?<!\\)\bdiv\b",
        "math_error_literal": r"Math input error|Missing open brace|Missing or unrecognized delimiter|Double exponent",
    }
    errors: list[dict[str, str]] = []
    for code, pattern in checks.items():
        if re.search(pattern, text):
            errors.append({"path": "$.standard_question", "message": code})
    for index, chunk in enumerate(chunks):
        if chunk.count("$") % 2:
            errors.append({"path": f"$.standard_question.markdown_chunk[{index}]", "message": "unbalanced_math_dollar_delimiter"})
    return errors


def validate_refined(refined: dict[str, Any], draft: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if refined.get("schema") != SCHEMA:
        errors.append({"path": "$.schema", "message": "invalid schema"})
    if refined.get("question_type") not in ALLOWED_QUESTION_TYPES:
        errors.append({"path": "$.question_type", "message": f"invalid question_type {refined.get('question_type')}"})
    if refined.get("solution_policy") not in ALLOWED_SOLUTION_POLICIES:
        errors.append({"path": "$.solution_policy", "message": f"invalid solution_policy {refined.get('solution_policy')}"})
    for key, expected in [
        ("doc_id", draft.get("doc_id", "")),
        ("source_draft_id", draft.get("draft_id", "")),
        ("source_group_id", draft.get("source_group_id", "")),
        ("prompt_version", prompt_version),
    ]:
        if refined.get(key) != expected:
            errors.append({"path": f"$.{key}", "message": "identifier mismatch"})
    q = refined.get("standard_question") or {}
    for key in ["title", "stem_md", "subquestions", "options", "answer_md", "explanation_md", "teaching_note_md", "context_md", "render_markdown"]:
        if key not in q:
            errors.append({"path": f"$.standard_question.{key}", "message": "missing key"})
    if not isinstance(q.get("subquestions"), list):
        errors.append({"path": "$.standard_question.subquestions", "message": "must be array"})
    if not isinstance(q.get("options"), list):
        errors.append({"path": "$.standard_question.options", "message": "must be array"})
    subquestions = q.get("subquestions") if isinstance(q.get("subquestions"), list) else []
    options = q.get("options") if isinstance(q.get("options"), list) else []
    for index, item in enumerate(subquestions):
        if not isinstance(item, dict):
            errors.append({"path": f"$.standard_question.subquestions[{index}]", "message": "must be object"})
            continue
        if not str(item.get("markdown") or "").strip():
            errors.append({"path": f"$.standard_question.subquestions[{index}].markdown", "message": "empty subquestion markdown"})
    for index, item in enumerate(options):
        if not isinstance(item, dict):
            errors.append({"path": f"$.standard_question.options[{index}]", "message": "must be object"})
            continue
        if not str(item.get("label") or "").strip():
            errors.append({"path": f"$.standard_question.options[{index}].label", "message": "empty option label"})
        if not str(item.get("markdown") or "").strip():
            errors.append({"path": f"$.standard_question.options[{index}].markdown", "message": "empty option markdown"})
    question_type = str(refined.get("question_type") or "")
    if question_type in CHOICE_QUESTION_TYPES and len(options) < 2:
        errors.append({"path": "$.standard_question.options", "message": "choice question requires at least two options"})
    if question_type not in CHOICE_QUESTION_TYPES and options:
        errors.append({"path": "$.standard_question.options", "message": "non-choice question must not contain options"})
    if refined.get("refine_status") == "REFINED_READY" and not (str(q.get("stem_md") or "").strip() or subquestions):
        errors.append({"path": "$.standard_question", "message": "ready packet requires stem or subquestions"})

    allowed_refs = draft_allowed_refs(draft)
    for ref_key, values in (refined.get("source_refs") or {}).items():
        if not isinstance(values, list):
            errors.append({"path": f"$.source_refs.{ref_key}", "message": "must be array"})
            continue
        for value in values:
            if value not in allowed_refs:
                errors.append({"path": f"$.source_refs.{ref_key}", "message": f"invented source ref {value}"})
    for cg in refined.get("condition_groups") or []:
        for value in cg.get("source_block_ids") or []:
            if value not in allowed_refs:
                errors.append({"path": "$.condition_groups.source_block_ids", "message": f"invented source ref {value}"})

    allowed_assets = draft_allowed_asset_ids(draft)
    all_text = "\n".join(refined_text_chunks(refined))
    for asset_id in extract_asset_tokens(all_text):
        if asset_id not in allowed_assets:
            errors.append({"path": "$.standard_question", "message": f"invented asset ref {asset_id}"})
    for asset in (refined.get("asset_refs") or {}).get("visual_refs") or []:
        asset_id = str(asset.get("asset_id") if isinstance(asset, dict) else asset)
        if asset_id and asset_id not in allowed_assets:
            errors.append({"path": "$.asset_refs.visual_refs", "message": f"invented asset ref {asset_id}"})
    errors.extend(markdown_risk_errors(refined))
    return {"valid": not errors, "errors": errors}


def call_model(config: dict[str, Any], node: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    started = time.time()
    response = requests.post(
        config["api_url"],
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
    raw = response.json()
    content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def refine_one(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    draft: dict[str, Any],
    system_prompt: str,
    user_template: str,
    repair_user_template: str,
    api_key: str,
    out_dir: Path,
) -> dict[str, Any]:
    draft_id = str(draft["draft_id"])
    draft_dir = out_dir / safe_name(str(draft.get("doc_id") or "")) / "drafts" / draft_id
    input_payload = build_model_input(draft)
    user_prompt = render_template(
        user_template,
        {
            "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            "doc_id": draft.get("doc_id", ""),
            "source_draft_id": draft_id,
            "source_group_id": draft.get("source_group_id", ""),
            "prompt_version": node["prompt_version"],
        },
    )
    model_result = call_model(config, node, system_prompt, user_prompt, api_key)
    parsed = model_result["parsed"] is not None
    parse_validation_errors: list[dict[str, Any]] = []
    if model_result["parsed"] is None:
        parse_validation_errors.append({"path": "$", "message": f"json_parse_failed: {model_result['parse_error']}"})
        refined = empty_refined(draft, node["prompt_version"], "REFINE_FAILED", model_result["parse_error"])
    else:
        refined = repair_shape(model_result["parsed"], draft, node["prompt_version"])
    validation = validate_refined(refined, draft, node["prompt_version"])
    if parse_validation_errors:
        validation = {"valid": False, "errors": parse_validation_errors + list(validation.get("errors") or [])}
    repair_called = False
    repair_parsed = False
    repair_usage: dict[str, Any] = {}
    if not validation["valid"]:
        write_json(draft_dir / "invalid_model_output.json", refined)
        write_json(draft_dir / "initial_validation_report.json", validation)
        repair_called = True
        repair_user_prompt = render_template(
            repair_user_template,
            {
                "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
                "previous_output_json": json.dumps(refined, ensure_ascii=False, indent=2),
                "validation_errors_json": json.dumps(validation["errors"], ensure_ascii=False, indent=2),
            },
        )
        try:
            repair_result = call_model(config, node, system_prompt, repair_user_prompt, api_key)
            repair_parsed = repair_result["parsed"] is not None
            repair_usage = repair_result["raw_response"].get("usage", {})
            write_text(draft_dir / "repair_user_prompt.md", repair_user_prompt)
            write_json(draft_dir / "repair_request_messages.full.local.json", repair_result["request_body"])
            write_json(draft_dir / "repair_raw_response.json", repair_result["raw_response"])
            write_text(draft_dir / "repair_raw_content.txt", repair_result["raw_content"])
            if repair_result["parsed"] is None:
                refined = empty_refined(draft, node["prompt_version"], "REFINE_FAILED", repair_result["parse_error"])
            else:
                refined = repair_shape(repair_result["parsed"], draft, node["prompt_version"])
            validation = validate_refined(refined, draft, node["prompt_version"])
        except Exception as exc:
            write_text(draft_dir / "repair_error.txt", str(exc))
            refined = empty_refined(draft, node["prompt_version"], "REFINE_FAILED", "Model output failed local validation and repair failed.")
            validation = validate_refined(refined, draft, node["prompt_version"])
    if not validation["valid"]:
        write_json(draft_dir / "repair_invalid_model_output.json", refined)
        refined = empty_refined(draft, node["prompt_version"], "REFINE_FAILED", "Model output failed local validation after repair.")
        validation = validate_refined(refined, draft, node["prompt_version"])

    write_json(draft_dir / "input_draft.json", draft)
    write_json(draft_dir / "model_input.json", input_payload)
    write_text(draft_dir / "used_system_prompt.md", system_prompt)
    write_text(draft_dir / "used_user_prompt.md", user_prompt)
    write_json(draft_dir / "request_messages.full.local.json", model_result["request_body"])
    write_json(draft_dir / "raw_response.json", model_result["raw_response"])
    write_text(draft_dir / "raw_content.txt", model_result["raw_content"])
    write_json(draft_dir / "refined_question_packet.json", refined)
    write_json(draft_dir / "validation_report.json", validation)
    return {
        "draft_id": draft_id,
        "source_group_id": draft.get("source_group_id"),
        "model_called": True,
        "parsed": parsed,
        "refine_status": refined["refine_status"],
        "projection_status": refined.get("status_breakdown", {}).get("projection_status", ""),
        "validation": validation,
        "artifact_path": rel(draft_dir / "refined_question_packet.json"),
        "usage": model_result["raw_response"].get("usage", {}),
        "repair_called": repair_called,
        "repair_parsed": repair_parsed,
        "repair_usage": repair_usage,
        "latency_seconds": model_result["latency_seconds"],
    }


def load_drafts(input_root: Path, doc_ids: set[str], doc_id_contains: list[str], group_ids: set[str]) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    for path in sorted(input_root.glob("*/source_backed_draft/docx_math_source_backed_draft_items.json")):
        payload = read_json(path)
        doc_id = str(payload.get("doc_id") or "")
        if doc_ids and doc_id not in doc_ids:
            continue
        if doc_id_contains and not any(fragment in doc_id for fragment in doc_id_contains):
            continue
        for draft in payload.get("draft_items") or []:
            if group_ids and draft.get("source_group_id") not in group_ids and draft.get("draft_id") not in group_ids:
                continue
            drafts.append(draft)
    return drafts


def render_review(refined_packets: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    cards = []
    for packet in refined_packets:
        q = packet["standard_question"]
        options = "\n".join(f"{item.get('label','')}. {item.get('markdown','')}" for item in q.get("options") or [])
        subquestions = "\n\n".join(f"{item.get('label','')} {item.get('markdown','')}".strip() for item in q.get("subquestions") or [])
        warnings = html.escape(json.dumps(packet.get("warnings") or [], ensure_ascii=False, indent=2))
        source_refs = html.escape(json.dumps(packet.get("source_refs") or {}, ensure_ascii=False, indent=2))
        assets = html.escape(json.dumps(packet.get("asset_refs") or {}, ensure_ascii=False, indent=2))
        cards.append(
            f"""
<article class="card">
  <h2>{html.escape(packet['source_draft_id'])} <small>{html.escape(packet['refine_status'])} / {html.escape(packet['question_type'])}</small></h2>
  <p class="meta">group=<code>{html.escape(packet['source_group_id'])}</code> projection=<code>{html.escape(packet['status_breakdown']['projection_status'])}</code></p>
  <section><h3>context</h3><pre>{html.escape(q.get('context_md',''))}</pre></section>
  <section><h3>stem</h3><pre>{html.escape(q.get('stem_md',''))}</pre></section>
  <section><h3>subquestions</h3><pre>{html.escape(subquestions)}</pre></section>
  <section><h3>options</h3><pre>{html.escape(options)}</pre></section>
  <section><h3>answer</h3><pre>{html.escape(q.get('answer_md',''))}</pre></section>
  <section><h3>explanation</h3><pre>{html.escape(q.get('explanation_md',''))}</pre></section>
  <section><h3>teaching_note</h3><pre>{html.escape(q.get('teaching_note_md',''))}</pre></section>
  <section><h3>render_markdown</h3><pre>{html.escape(q.get('render_markdown',''))}</pre></section>
  <details><summary>condition_groups</summary><pre>{html.escape(json.dumps(packet.get('condition_groups') or [], ensure_ascii=False, indent=2))}</pre></details>
  <details><summary>asset_refs</summary><pre>{assets}</pre></details>
  <details><summary>source_refs</summary><pre>{source_refs}</pre></details>
  <details><summary>warnings</summary><pre>{warnings}</pre></details>
</article>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX Math Refiner Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f3f6fa;color:#111827;line-height:1.5}}
.card{{background:white;border:1px solid #d8dee9;border-radius:8px;padding:16px;margin:18px 0}}
small,.meta{{color:#5f6b7a;font-weight:400}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;overflow:auto}}
section{{border-top:1px solid #eef2f7;padding-top:8px;margin-top:8px}}
code{{background:#eef2f7;padding:2px 5px;border-radius:4px}}
</style>
<h1>DOCX Math Question Refiner Review</h1>
<p>run=<code>{html.escape(summary['run_id'])}</code> drafts=<code>{summary['draft_count']}</code> ready=<code>{summary['refined_ready_count']}</code> needs_review=<code>{summary['needs_review_count']}</code> failed=<code>{summary['refine_failed_count']}</code></p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node4_question_refiner"]
    input_root = workspace_path(args.input_draft_root)
    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    repair_user_template = workspace_path(node["repair_user_prompt_path"]).read_text(encoding="utf-8")
    drafts = load_drafts(input_root, set(args.doc_ids or []), args.doc_id_contains or [], set(args.group_ids or []))
    if args.max_drafts:
        drafts = drafts[: args.max_drafts]

    if args.prepare_only:
        records = []
        for draft in drafts:
            draft_id = str(draft["draft_id"])
            draft_dir = out_root / safe_name(str(draft.get("doc_id") or "")) / "drafts" / draft_id
            input_payload = build_model_input(draft)
            user_prompt = render_template(
                user_template,
                {
                    "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
                    "doc_id": draft.get("doc_id", ""),
                    "source_draft_id": draft_id,
                    "source_group_id": draft.get("source_group_id", ""),
                    "prompt_version": node["prompt_version"],
                },
            )
            write_json(draft_dir / "input_draft.json", draft)
            write_json(draft_dir / "model_input.json", input_payload)
            write_text(draft_dir / "used_system_prompt.md", system_prompt)
            write_text(draft_dir / "used_user_prompt.md", user_prompt)
            write_text(draft_dir / "used_repair_user_prompt_template.md", repair_user_template)
            records.append(
                {
                    "draft_id": draft_id,
                    "source_group_id": draft.get("source_group_id"),
                    "model_called": False,
                    "artifact_path": rel(draft_dir / "model_input.json"),
                    "user_prompt_chars": len(user_prompt),
                }
            )
        summary = {
            "schema": "docx_math_question_refiner.prepare_summary",
            "run_id": args.run_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "node": "node4_question_refiner",
            "model": node["model"],
            "prompt_version": node["prompt_version"],
            "input_draft_root": rel(input_root),
            "out_dir": rel(out_root),
            "prepare_only": True,
            "runtime_import_enabled": False,
            "database_write_enabled": False,
            "draft_count": len(records),
            "records": records,
        }
        write_json(out_root / "prepare_summary.json", summary)
        return summary

    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')} or --api-key")

    records: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                refine_one,
                config=config,
                node=node,
                draft=draft,
                system_prompt=system_prompt,
                user_template=user_template,
                repair_user_template=repair_user_template,
                api_key=api_key,
                out_dir=out_root,
            ): draft
            for draft in drafts
        }
        for future in concurrent.futures.as_completed(future_map):
            records.append(future.result())
    records.sort(key=lambda item: item["draft_id"])
    refined_packets = [read_json(workspace_path(record["artifact_path"])) for record in records]
    summary_counts = {
        "draft_count": len(records),
        "model_called_count": sum(1 for item in records if item.get("model_called")),
        "refined_ready_count": sum(1 for item in refined_packets if item.get("refine_status") == "REFINED_READY"),
        "needs_review_count": sum(1 for item in refined_packets if item.get("refine_status") == "REFINED_NEEDS_REVIEW"),
        "refine_failed_count": sum(1 for item in refined_packets if item.get("refine_status") == "REFINE_FAILED"),
        "repair_called_count": sum(1 for item in records if item.get("repair_called")),
        "repair_parsed_count": sum(1 for item in records if item.get("repair_parsed")),
        "total_tokens": sum(
            int((record.get("usage") or {}).get("total_tokens") or 0)
            + int((record.get("repair_usage") or {}).get("total_tokens") or 0)
            for record in records
        ),
    }
    payload = {
        "schema": "docx_math_refined_question_packets_batch_v0.1",
        "refiner_version": REFINER_VERSION,
        "prompt_version": node["prompt_version"],
        "refined_packets": refined_packets,
        "summary": summary_counts,
    }
    summary = {
        "schema": "docx_math_question_refiner.run_summary",
        "run_id": args.run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node4_question_refiner",
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "input_draft_root": rel(input_root),
        "out_dir": rel(out_root),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": records,
        "refined_packets_json": rel(out_root / "refined_question_packets.json"),
        "review_html": rel(out_root / "review.html"),
        **summary_counts,
    }
    write_json(out_root / "refined_question_packets.json", payload)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(refined_packets, summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/docx_math_question_refiner_v01.yaml")
    parser.add_argument("--input-draft-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-ids", nargs="*", default=[])
    parser.add_argument("--doc-id-contains", nargs="*", default=[])
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--max-drafts", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
