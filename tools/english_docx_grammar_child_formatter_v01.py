from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from english_docx_parent_child_projection_v02 import render_text, safe_rel, write_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "grammar_child_formatter_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
CURRENT_BLANK_RE = re.compile(r"\[\[CURRENT_BLANK_(\d+)\]\]")
UNDERLINE_FILL_RE = re.compile(r"\[\[UNDERLINE_FILL_(\d+)\]\](.*?)\[\[/UNDERLINE_FILL_\1\]\]")
DETAIL_MARKER_RE = re.compile(r"^\s*【详解】\s*")
TEST_POINT_RE = re.compile(r"(考查[^。；;]*[。；;])")
TRANSLATION_RE = re.compile(r"句意[:：]\s*(.*?。)")
REQUIRED_SECTIONS = ["判断考点", "答案", "翻译", "解析"]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    if text in {"true", "false"}:
        return text == "true"
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        return text


def read_simple_yaml(path: Path) -> dict[str, Any]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = [line.rstrip() for line in raw_lines if line.strip() and not line.lstrip().startswith("#")]
    data: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(" "):
            index += 1
            continue
        key, sep, value = line.partition(":")
        if not sep:
            index += 1
            continue
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = parse_scalar(value)
            index += 1
            continue
        next_index = index + 1
        if next_index < len(lines) and lines[next_index].startswith("  - "):
            items: list[Any] = []
            while next_index < len(lines) and lines[next_index].startswith("  - "):
                items.append(parse_scalar(lines[next_index][4:]))
                next_index += 1
            data[key] = items
        else:
            mapping: dict[str, Any] = {}
            while next_index < len(lines) and lines[next_index].startswith("  "):
                child = lines[next_index].strip()
                child_key, child_sep, child_value = child.partition(":")
                if child_sep:
                    mapping[child_key.strip()] = parse_scalar(child_value)
                next_index += 1
            data[key] = mapping
        index = next_index
    return data


def read_config(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        return read_simple_yaml(path)
    return read_json(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compact(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def load_prompt(config: dict[str, Any], key: str) -> str:
    path = Path(str(config.get(key) or ""))
    if not path.is_absolute():
        path = ROOT / path
    return read_text(path)


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


def call_model(config: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str, timeout: int) -> dict[str, Any]:
    body = {
        "model": config.get("default_model_endpoint_id"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    started = time.time()
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    raw_response = json.loads(raw)
    content = str(raw_response["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "raw_response": raw_response,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "elapsed_seconds": round(time.time() - started, 3),
        "usage": raw_response.get("usage") or {},
    }


def section_marker(section: str) -> str:
    return f"【{section}】"


def has_required_sections(text: str) -> bool:
    positions = [str(text or "").find(section_marker(section)) for section in REQUIRED_SECTIONS]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def parse_formatted_sections(text: str) -> dict[str, str]:
    value = str(text or "")
    sections: dict[str, str] = {}
    markers: list[tuple[str, int, int]] = []
    for section in REQUIRED_SECTIONS:
        marker = section_marker(section)
        position = value.find(marker)
        if position >= 0:
            markers.append((section, position, position + len(marker)))
    markers.sort(key=lambda item: item[1])
    for index, (section, _start, content_start) in enumerate(markers):
        content_end = markers[index + 1][1] if index + 1 < len(markers) else len(value)
        sections[section] = value[content_start:content_end].strip()
    return sections


def blank_no_from_child(child: dict[str, Any]) -> str:
    item_no = re.sub(r"\D+", "", str(child.get("item_no") or ""))
    if item_no:
        return item_no
    anchor_match = BLANK_RE.search(str(child.get("anchor") or ""))
    if anchor_match:
        return anchor_match.group(1)
    source_item_no = str(child.get("source_item_no") or "")
    return re.sub(r"\D+", "", source_item_no)


def source_blank_no_from_child(child: dict[str, Any]) -> str:
    anchor_match = BLANK_RE.search(str(child.get("anchor") or ""))
    if anchor_match:
        return anchor_match.group(1)
    source_item_no = str(child.get("source_item_no") or "")
    return re.sub(r"\D+", "", source_item_no)


def answer_map_from_children(children: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in children:
        blank_no = blank_no_from_child(child)
        answer = str(child.get("answer") or "").strip()
        if blank_no and answer:
            out[blank_no] = answer
    return out


def blank_number_map_from_children(children: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in children:
        source_no = source_blank_no_from_child(child)
        local_no = blank_no_from_child(child)
        if source_no and local_no:
            out[source_no] = local_no
    return out


def blank_display_map_from_children(children: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for child in children:
        rows.append(
            {
                "item_id": str(child.get("item_id") or ""),
                "source_blank": source_blank_no_from_child(child),
                "local_blank": blank_no_from_child(child),
                "answer": str(child.get("answer") or "").strip(),
            }
        )
    return rows


def normalize_display_context(
    text: str,
    current_blank_no: str,
    sibling_answers: dict[str, str],
    blank_number_map: dict[str, str] | None = None,
) -> str:
    number_map = blank_number_map or {}
    value = str(text or "").strip()
    value = CURRENT_BLANK_RE.sub(lambda match: f"[[BLANK_{match.group(1)}]]", value)
    value = UNDERLINE_FILL_RE.sub(lambda match: f"[[BLANK_{match.group(1)}]]", value)
    current_number = int(current_blank_no) if str(current_blank_no).isdigit() else None

    def repl(match: re.Match[str]) -> str:
        raw_blank_no = match.group(1)
        blank_no = number_map.get(raw_blank_no, raw_blank_no)
        if blank_no == current_blank_no:
            return f"[[CURRENT_BLANK_{blank_no}]]"
        if current_number is not None and blank_no.isdigit() and int(blank_no) < current_number:
            answer = sibling_answers.get(blank_no, "")
            if answer:
                return f"[[UNDERLINE_FILL_{blank_no}]]{answer}[[/UNDERLINE_FILL_{blank_no}]]"
        return f"[[BLANK_{blank_no}]]"

    return BLANK_RE.sub(repl, value)


def source_comparable_text(text: str) -> str:
    value = CURRENT_BLANK_RE.sub("[[BLANK]]", str(text or ""))
    value = UNDERLINE_FILL_RE.sub("[[BLANK]]", value)
    value = BLANK_RE.sub("[[BLANK]]", value)
    return re.sub(r"\s+", " ", value).strip()


def is_source_backed_context(display_context: str, source_text: str) -> bool:
    context = source_comparable_text(display_context)
    source = source_comparable_text(source_text)
    return bool(context) and context in source


def sentence_spans(text: str) -> list[tuple[int, int]]:
    value = str(text or "")
    if not value:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(value):
        char = value[index]
        boundary = False
        if char in ".?!。！？":
            next_char = value[index + 1] if index + 1 < len(value) else ""
            boundary = not next_char or next_char.isspace() or next_char in "\"'“”’）)]"
        if char == "\n":
            boundary = True
        if boundary:
            end = index + 1
            if value[start:end].strip():
                spans.append((start, end))
            start = end
            while start < len(value) and value[start].isspace():
                start += 1
            index = start
            continue
        index += 1
    if start < len(value) and value[start:].strip():
        spans.append((start, len(value)))
    return spans or [(0, len(value))]


def context_candidates_for_child(
    child: dict[str, Any],
    sibling_answers: dict[str, str],
    blank_number_map: dict[str, str],
) -> list[str]:
    question = str(child.get("question") or "").strip()
    if not question:
        return []
    local_blank = blank_no_from_child(child)
    source_blank = source_blank_no_from_child(child) or local_blank
    source_marker = f"[[BLANK_{source_blank}]]"
    marker_pos = question.find(source_marker)
    if marker_pos < 0 and local_blank:
        marker_pos = question.find(f"[[BLANK_{local_blank}]]")
    if marker_pos < 0:
        return [normalize_display_context(question, local_blank, sibling_answers, blank_number_map)]
    spans = sentence_spans(question)
    current_index = 0
    for index, (start, end) in enumerate(spans):
        if start <= marker_pos < end:
            current_index = index
            break
    raw_candidates = [
        question[spans[current_index][0] : spans[current_index][1]],
    ]
    if current_index > 0:
        raw_candidates.append(question[spans[current_index - 1][0] : spans[current_index][1]])
    if current_index + 1 < len(spans):
        raw_candidates.append(question[spans[current_index][0] : spans[current_index + 1][1]])
    seen: set[str] = set()
    candidates: list[str] = []
    for raw in raw_candidates:
        normalized = normalize_display_context(raw, local_blank, sibling_answers, blank_number_map)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates[:3]


def clean_raw_explanation(text: str) -> str:
    return DETAIL_MARKER_RE.sub("", str(text or "").strip()).strip()


def review_only_from_raw(
    child: dict[str, Any],
    sibling_answers: dict[str, str],
    issues: list[str],
    blank_number_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    blank_no = blank_no_from_child(child)
    return {
        "item_id": str(child.get("item_id") or ""),
        "item_no": str(child.get("item_no") or ""),
        "source_item_no": str(child.get("source_item_no") or ""),
        "display_context": normalize_display_context(str(child.get("question") or ""), blank_no, sibling_answers, blank_number_map),
        "test_point": "",
        "answer": str(child.get("answer") or "").strip(),
        "translation": "",
        "analysis": "",
        "formatted_explanation": "",
        "confidence": "low",
        "source": "review_only_raw_explanation",
        "warnings": issues[:12],
    }


def child_for_model(
    child: dict[str, Any],
    max_chars: int,
    sibling_answers: dict[str, str],
    blank_number_map: dict[str, str],
) -> dict[str, Any]:
    return {
        "item_id": child.get("item_id"),
        "item_no": child.get("item_no"),
        "source_item_no": child.get("source_item_no"),
        "item_kind": child.get("item_kind"),
        "anchor": child.get("anchor"),
        "question": compact(str(child.get("question") or ""), max_chars),
        "context_candidates": context_candidates_for_child(child, sibling_answers, blank_number_map),
        "answer": compact(str(child.get("answer") or ""), 300),
        "raw_explanation": compact(str(child.get("explanation") or ""), max_chars),
    }


def render_user_prompt(
    config: dict[str, Any],
    template: str,
    *,
    doc_id: str,
    group: dict[str, Any],
    children: list[dict[str, Any]],
    sibling_answers: dict[str, str],
) -> str:
    max_passage_chars = int(config.get("max_passage_chars") or 9000)
    max_child_chars = int(config.get("max_child_text_chars") or 1800)
    blank_number_map = blank_number_map_from_children(children)
    parent = group.get("parent") or {}
    parent_for_model = {
        "kind": group.get("parent_kind"),
        "source_label": compact(str(parent.get("source_label") or ""), 1200),
        "passage": compact(str(parent.get("passage") or ""), max_passage_chars),
        "teaching_note": compact(str(parent.get("teaching_note") or ""), 1200),
    }
    return render_template(
        template,
        {
            "doc_id": doc_id,
            "group_id": str(group.get("group_id") or ""),
            "prompt_version": str(config.get("prompt_version") or ""),
            "parent_json": json.dumps(parent_for_model, ensure_ascii=False, indent=2),
            "sibling_answers_json": json.dumps(sibling_answers, ensure_ascii=False, indent=2),
            "blank_display_map_json": json.dumps(blank_display_map_from_children(children), ensure_ascii=False, indent=2),
            "children_json": json.dumps(
                [child_for_model(child, max_child_chars, sibling_answers, blank_number_map) for child in children],
                ensure_ascii=False,
                indent=2,
            ),
        },
    )


def validate_result(
    parsed: dict[str, Any] | None,
    *,
    doc_id: str,
    group: dict[str, Any],
    children: list[dict[str, Any]],
    sibling_answers: dict[str, str],
) -> tuple[bool, list[str], dict[str, Any]]:
    if not isinstance(parsed, dict):
        return False, ["model_output_not_json_object"], {}
    issues: list[str] = []
    cleaned = dict(parsed)
    if cleaned.get("schema") != "english_docx_grammar_child_formatter_v0.1":
        issues.append("schema_mismatch")
    if str(cleaned.get("doc_id") or "") != doc_id:
        issues.append("doc_id_mismatch")
    if str(cleaned.get("group_id") or "") != str(group.get("group_id") or ""):
        issues.append("group_id_mismatch")
    supplied = {str(child.get("item_id") or ""): child for child in children}
    blank_number_map = blank_number_map_from_children(children)
    items = cleaned.get("items")
    if not isinstance(items, list):
        return False, issues + ["items_not_list"], cleaned
    seen: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"item_{index}_not_object")
            continue
        item_id = str(item.get("item_id") or "")
        source_child = supplied.get(item_id)
        if not source_child:
            issues.append(f"unknown_item_id:{item_id}")
            continue
        if item_id in seen:
            issues.append(f"duplicate_item_id:{item_id}")
        seen.add(item_id)
        if str(item.get("item_no") or "") != str(source_child.get("item_no") or ""):
            issues.append(f"item_no_mismatch:{item_id}")
        if str(item.get("source_item_no") or "") != str(source_child.get("source_item_no") or ""):
            issues.append(f"source_item_no_mismatch:{item_id}")
        answer = str(item.get("answer") or "").strip()
        expected_answer = str(source_child.get("answer") or "").strip()
        if answer != expected_answer:
            issues.append(f"answer_mismatch:{item_id}:{answer}:{expected_answer}")
            answer = expected_answer
        blank_no = blank_no_from_child(source_child)
        raw_display_context = str(item.get("display_context") or "").strip()
        if not raw_display_context:
            issues.append(f"missing_display_context:{item_id}")
        display_context = normalize_display_context(raw_display_context, blank_no, sibling_answers, blank_number_map)
        if f"[[CURRENT_BLANK_{blank_no}]]" not in display_context:
            issues.append(f"missing_current_blank:{item_id}")
        candidate_set = set(context_candidates_for_child(source_child, sibling_answers, blank_number_map))
        if candidate_set and display_context not in candidate_set:
            issues.append(f"display_context_not_from_candidates:{item_id}")
        if not is_source_backed_context(display_context, str(source_child.get("question") or "")):
            issues.append(f"display_context_not_source_backed:{item_id}")
        test_point = str(item.get("test_point") or "").strip()
        if not test_point.startswith("考查"):
            issues.append(f"test_point_not_from_exam_style:{item_id}:{test_point}")
        formatted = str(item.get("formatted_explanation") or "").strip()
        if not has_required_sections(formatted):
            issues.append(f"missing_or_disordered_required_sections:{item_id}")
            section_values = {}
        else:
            section_values = parse_formatted_sections(formatted)
        if section_values:
            test_point = test_point or section_values.get("判断考点", "").strip()
        translation = str(item.get("translation") or "").strip()
        if not translation and section_values:
            translation = section_values.get("翻译", "").strip()
        if not translation:
            issues.append(f"missing_translation:{item_id}")
        analysis = str(item.get("analysis") or "").strip()
        if not analysis and section_values:
            analysis = section_values.get("解析", "").strip()
        if not analysis:
            issues.append(f"missing_analysis:{item_id}")
        if section_values:
            if section_values.get("答案", "").strip() != answer:
                issues.append(f"formatted_answer_mismatch:{item_id}:{section_values.get('答案', '').strip()}:{answer}")
            if not section_values.get("翻译", "").strip():
                issues.append(f"formatted_missing_translation:{item_id}")
            if not section_values.get("解析", "").strip():
                issues.append(f"formatted_missing_analysis:{item_id}")
        if "【详解】" in formatted:
            issues.append(f"forbidden_detail_section:{item_id}")
        normalized_items.append(
            {
                "item_id": item_id,
                "item_no": str(item.get("item_no") or ""),
                "source_item_no": str(item.get("source_item_no") or ""),
                "display_context": display_context,
                "test_point": test_point,
                "answer": answer,
                "translation": translation,
                "analysis": analysis,
                "formatted_explanation": formatted,
                "confidence": str(item.get("confidence") or "low"),
                "source": "model",
                "warnings": [],
            }
        )
    missing = sorted(set(supplied) - seen)
    for item_id in missing:
        issues.append(f"missing_item_id:{item_id}")
    cleaned["items"] = normalized_items
    if not isinstance(cleaned.get("warnings"), list):
        cleaned["warnings"] = []
    return not issues, issues, cleaned


def append_retry_feedback(base_prompt: str, issues: list[str], attempt: int) -> str:
    return (
        base_prompt
        + "\n\nValidation feedback for retry "
        + str(attempt)
        + ":\n"
        + json.dumps(issues[:80], ensure_ascii=False, indent=2)
        + "\n\nRegenerate the whole JSON. Do not omit any field. Do not let formatted_explanation miss any required section."
    )


def merge_items(group: dict[str, Any], enhanced_items: list[dict[str, Any]], status: str) -> dict[str, Any]:
    by_id = {item["item_id"]: item for item in enhanced_items}
    merged = dict(group)
    children = []
    for child in group.get("children") or []:
        updated = dict(child)
        item = by_id.get(str(child.get("item_id") or ""))
        if item:
            updated["raw_explanation"] = updated.get("explanation") or ""
            updated["display_context"] = item.get("display_context") or ""
            updated["test_point"] = item.get("test_point") or ""
            updated["translation"] = item.get("translation") or ""
            updated["analysis"] = item.get("analysis") or ""
            updated["formatted_explanation"] = item.get("formatted_explanation") or ""
            updated["grammar_formatting"] = {
                "status": status if not item.get("warnings") else "needs_review",
                "source": item.get("source"),
                "confidence": item.get("confidence"),
                "warnings": item.get("warnings") or [],
            }
        children.append(updated)
    merged["children"] = children
    return merged


def process_group(
    *,
    config: dict[str, Any],
    group: dict[str, Any],
    doc_id: str,
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
    no_model: bool,
) -> dict[str, Any]:
    group_id = str(group.get("group_id") or "")
    if str(group.get("parent_kind") or "") != "grammar_cloze":
        return {"group_id": group_id, "status": "skipped_non_grammar_cloze", "group": group, "issues": [], "usage": {}}
    children = [child for child in group.get("children") or [] if isinstance(child, dict) and str(child.get("item_kind") or "") == "grammar_blank"]
    sibling_answers = answer_map_from_children(children)
    blank_number_map = blank_number_map_from_children(children)
    if no_model:
        enhanced = [review_only_from_raw(child, sibling_answers, ["no_model"], blank_number_map) for child in children]
        return {"group_id": group_id, "status": "needs_review", "group": merge_items(group, enhanced, "needs_review"), "issues": ["no_model"], "usage": {}}

    base_prompt = render_user_prompt(config, user_template, doc_id=doc_id, group=group, children=children, sibling_answers=sibling_answers)
    prompt = base_prompt
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": base_prompt})
    timeout = int((config.get("runner") or {}).get("per_group_timeout_seconds") or 240)
    max_attempts = int((config.get("runner") or {}).get("max_group_attempts") or 3)
    last_issues: list[str] = []
    last_usage: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        try:
            (raw_dir / f"attempt{attempt}.prompt.md").write_text(prompt, encoding="utf-8")
            result = call_model(config, system_prompt, prompt, api_key, timeout)
            last_usage = result.get("usage") or {}
            write_json(raw_dir / f"attempt{attempt}.raw.json", result["raw_response"])
            (raw_dir / f"attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            if result.get("parsed") is not None:
                write_json(raw_dir / f"attempt{attempt}.parsed.json", result["parsed"])
            ok, issues, cleaned = validate_result(
                result.get("parsed"),
                doc_id=doc_id,
                group=group,
                children=children,
                sibling_answers=sibling_answers,
            )
            if ok:
                enhanced = cleaned.get("items") or []
                return {
                    "group_id": group_id,
                    "status": "ok",
                    "group": merge_items(group, enhanced, "ok"),
                    "issues": [],
                    "warnings": cleaned.get("warnings") or [],
                    "usage": last_usage,
                    "elapsed_seconds": result.get("elapsed_seconds"),
                    "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
                }
            last_issues = issues
            write_json(raw_dir / f"attempt{attempt}.issues.json", issues)
            prompt = append_retry_feedback(base_prompt, issues, attempt + 1)
        except Exception as exc:  # noqa: BLE001
            last_issues = [repr(exc)]
            write_json(raw_dir / f"attempt{attempt}.exception.json", {"error": repr(exc)})
            prompt = append_retry_feedback(base_prompt, last_issues, attempt + 1)
    enhanced = [review_only_from_raw(child, sibling_answers, last_issues or ["model_failed"], blank_number_map) for child in children]
    return {
        "group_id": group_id,
        "status": "needs_review",
        "group": merge_items(group, enhanced, "needs_review"),
        "issues": last_issues or ["model_failed"],
        "usage": last_usage,
    }


def render_field(title: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {html.escape(class_name)}"><h4>{html.escape(title)}</h4>{render_text(text)}</section>'


def render_review_html(out_dir: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    groups_html: list[str] = []
    for group in records:
        parent = group.get("parent") or {}
        children_html: list[str] = []
        for child in group.get("children") or []:
            status = (child.get("grammar_formatting") or {}).get("status") or ""
            warnings = (child.get("grammar_formatting") or {}).get("warnings") or []
            warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings)
            children_html.append(
                '<article class="child">'
                f'<h3>第 {html.escape(str(child.get("item_no") or ""))} 空 <small>{html.escape(status)}</small></h3>'
                f'{render_field("题目原文", child.get("display_context") or child.get("question") or "", "context")}'
                f'{render_field("格式化解析", child.get("formatted_explanation") or child.get("explanation") or "", "formatted")}'
                + (f'<ul class="warnings">{warning_html}</ul>' if warning_html else "")
                + "</article>"
            )
        groups_html.append(
            '<section class="group">'
            f'<h2>{html.escape(str(group.get("group_id") or ""))}</h2>'
            f'{render_field("父级文章", parent.get("passage") or "", "passage")}'
            + "".join(children_html)
            + "</section>"
        )
    css = """
body{margin:0;background:#f5f7fb;color:#172033;font:16px/1.72 "Times New Roman",SimSun,"Microsoft YaHei",serif}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #dbe3ef;padding:18px 28px;z-index:2}
h1{margin:0;font:700 22px/1.3 "Microsoft YaHei",sans-serif}.meta{color:#64748b;font:13px/1.4 "Microsoft YaHei",sans-serif;margin-top:6px}
main{max-width:1400px;margin:0 auto;padding:24px 28px 80px}.group{background:#fff;border:1px solid #d9e2ee;border-radius:10px;margin:0 0 22px;padding:18px 22px}
h2{margin:0 0 12px;font:700 20px/1.35 "Microsoft YaHei",sans-serif}.field{margin:0 0 13px}.field h4{margin:0 0 5px;color:#0f766e;font:700 15px/1.4 "Microsoft YaHei",sans-serif}.field p{margin:0 0 8px;white-space:pre-wrap;overflow-wrap:anywhere}
.passage{padding:12px 14px;background:#fbfdff;border:1px solid #e5ebf3;border-radius:8px}.context{background:#fffef5;border-left:3px solid #ca8a04;padding:8px 10px}.child{border-top:1px solid #e5ebf3;padding:16px 0}.child h3{margin:0 0 10px;color:#1d4ed8;font:700 17px/1.35 "Microsoft YaHei",sans-serif}.child h3 small{color:#64748b;font-size:12px}
.formatted{background:#fff;border-left:3px solid #0f766e;padding:8px 10px}.warnings{color:#b45309}.current-blank{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:2px solid #111827;vertical-align:-.08em;background:#fff7cc}.filled-blank{display:inline-block;min-width:5.2em;height:1.05em;margin:0 .18em;padding:0 .35em;border-bottom:1.5px solid #111827;text-align:center;line-height:1;vertical-align:-.08em;text-decoration:none}.blank{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:1.5px solid #111827;vertical-align:-.08em}
"""
    html_text = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Grammar child formatter review</title><style>{css}</style></head>"
        f'<body><header><h1>Grammar Child Formatter Review</h1><div class="meta">{html.escape(json.dumps(summary, ensure_ascii=False))}</div></header>'
        f'<main>{"".join(groups_html)}</main></body></html>'
    )
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_config(args.config)
    payload = read_json(args.input_projection)
    doc_id = args.doc_id or str(payload.get("doc_id") or args.input_projection.parent.name)
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/english_docx_grammar_child_formatter_v0_1")
    out_dir = out_root / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    groups = [record for record in payload.get("records") or [] if isinstance(record, dict)]
    if args.group_ids:
        wanted = {item.strip() for item in args.group_ids.split(",") if item.strip()}
        groups = [group for group in groups if str(group.get("group_id") or "") in wanted]
    if args.max_groups:
        groups = groups[: args.max_groups]
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.no_model:
        raise RuntimeError("missing_api_key")
    max_workers = max(1, int(args.max_workers or (config.get("runner") or {}).get("max_workers") or 1))
    results: list[dict[str, Any]] = []
    if max_workers == 1:
        for group in groups:
            results.append(
                process_group(
                    config=config,
                    group=group,
                    doc_id=doc_id,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    api_key=api_key,
                    out_dir=out_dir,
                    no_model=args.no_model,
                )
            )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    process_group,
                    config=config,
                    group=group,
                    doc_id=doc_id,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    api_key=api_key,
                    out_dir=out_dir,
                    no_model=args.no_model,
                )
                for group in groups
            ]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
    order = {str(group.get("group_id") or ""): index for index, group in enumerate(groups)}
    results.sort(key=lambda item: order.get(str(item.get("group_id") or ""), 10**9))
    records = [item.get("group") for item in results if item.get("group")]
    usage = Counter()
    for result in results:
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int):
                usage[key] += value
    summary = {
        "schema_version": "english_docx_grammar_child_formatter_summary.v0.1",
        "pipeline_id": config.get("pipeline_id"),
        "run_id": args.run_id,
        "doc_id": doc_id,
        "group_count": len(groups),
        "child_count": sum(len((group or {}).get("children") or []) for group in records),
        "status_counts": dict(Counter(str(item.get("status") or "") for item in results)),
        "issue_count": sum(len(item.get("issues") or []) for item in results),
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": config.get("prompt_version"),
        "prompt_hashes": {
            "system": sha256_text(system_prompt),
            "user": sha256_text(user_template),
        },
        "artifacts": {
            "formatted": safe_rel(out_dir / "grammar_child_formatted.json"),
            "review_html": safe_rel(out_dir / "index.html"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
    }
    output = {
        "schema_version": "english_docx_grammar_child_formatter_results.v0.1",
        "doc_id": doc_id,
        "run_id": args.run_id,
        "source_parent_child_projection": safe_rel(args.input_projection),
        "records": records,
        "results": results,
    }
    write_json(out_dir / "grammar_child_formatted.json", output)
    write_json(out_dir / "summary.json", summary)
    render_review_html(out_dir, records, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Format grammar cloze child questions after parent-child projection.")
    parser.add_argument("--input-projection", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
