from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from english_docx_parent_child_projection_v02 import render_text, safe_rel, write_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "reading_child_enhancer_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
REQUIRED_SECTIONS = ["圈", "找", "比", "答案", "翻译"]
STOP_SECTIONS = ["选项词汇清单", "长难句分析"]


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
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1
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


def section_positions(text: str) -> list[int]:
    return [str(text or "").find(section_marker(section)) for section in REQUIRED_SECTIONS]


def has_required_sections(text: str) -> bool:
    positions = section_positions(text)
    return all(pos >= 0 for pos in positions) and positions == sorted(positions)


def truncate_after_translation(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    end = len(value)
    translation_pos = value.find(section_marker("翻译"))
    if translation_pos < 0:
        return value
    for section in STOP_SECTIONS:
        pos = value.find(section_marker(section), translation_pos)
        if pos >= 0:
            end = min(end, pos)
    return value[:end].strip()


def compare_type_from_text(text: str, allowed: set[str]) -> str:
    for value in allowed:
        if value in str(text or ""):
            return value
    return ""


def normalized_source_text(text: str) -> str:
    return "".join(char.lower() for char in str(text or "") if char.isalnum())


def source_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    current: list[str] = []
    for char in str(text or ""):
        if char.isalnum():
            current.append(char.lower())
        elif current:
            tokens.add("".join(current))
            current = []
    if current:
        tokens.add("".join(current))
    return tokens


def keyword_from_question(keyword: str, question: str) -> bool:
    value = str(keyword or "").strip()
    if not value:
        return False
    compact_keyword = normalized_source_text(value)
    compact_question = normalized_source_text(question)
    if compact_keyword and compact_keyword in compact_question:
        return True
    question_tokens = source_tokens(question)
    keyword_tokens = source_tokens(value)
    return bool(keyword_tokens) and keyword_tokens.issubset(question_tokens)


def section_bounds(text: str, section: str) -> tuple[int, int] | None:
    marker = section_marker(section)
    start = str(text or "").find(marker)
    if start < 0:
        return None
    content_start = start + len(marker)
    next_positions = [
        position
        for next_section in REQUIRED_SECTIONS
        if next_section != section
        for position in [str(text or "").find(section_marker(next_section), content_start)]
        if position >= 0
    ]
    content_end = min(next_positions) if next_positions else len(str(text or ""))
    return content_start, content_end


def replace_section_content(text: str, section: str, content: str) -> str:
    value = str(text or "")
    bounds = section_bounds(value, section)
    if not bounds:
        return value
    start, end = bounds
    return value[:start] + str(content or "").strip() + "\n\n" + value[end:].lstrip()


def section_content(text: str, section: str) -> str:
    bounds = section_bounds(str(text or ""), section)
    if not bounds:
        return ""
    start, end = bounds
    return str(text or "")[start:end].strip()


def translation_section_is_clean(text: str) -> bool:
    translation = section_content(text, "翻译")
    if not translation:
        return False
    forbidden = [
        "Question:",
        "question:",
        "问题：",
        "问题:",
        "题干：",
        "题干:",
        "选项A",
        "选项B",
        "选项C",
        "选项D",
        "Option A",
        "Option B",
        "Option C",
        "Option D",
        "->",
        "→",
    ]
    return not any(token in translation for token in forbidden)


def clean_translation_pairs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    pairs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        label = str(item.get("label") or "").strip()
        original = str(item.get("original") or "").strip()
        translation = str(item.get("translation") or "").strip()
        if not role or not original or not translation:
            continue
        pairs.append(
            {
                "role": role,
                "label": label,
                "original": original,
                "translation": translation,
            }
        )
    return pairs


def count_option_labels(text: str) -> int:
    value = str(text or "")
    count = 0
    for index, char in enumerate(value):
        if char not in "ABCDEFG":
            continue
        if index > 0 and value[index - 1].isalpha():
            continue
        if index + 1 >= len(value) or value[index + 1] != ".":
            continue
        if index + 2 < len(value) and not value[index + 2].isspace():
            continue
        count += 1
    return count


def preformatted_item(child: dict[str, Any], allowed_compare_types: set[str]) -> dict[str, Any] | None:
    explanation = truncate_after_translation(str(child.get("explanation") or ""))
    if not has_required_sections(explanation):
        return None
    translation_pairs = clean_translation_pairs(child.get("translation_pairs"))
    if not child.get("evidence_scope") or not child.get("evidence_text") or not translation_pairs:
        return None
    return {
        "item_id": str(child.get("item_id") or ""),
        "item_no": str(child.get("item_no") or ""),
        "source_item_no": str(child.get("source_item_no") or ""),
        "evidence_scope": str(child.get("evidence_scope") or "").strip(),
        "evidence_text": str(child.get("evidence_text") or "").strip(),
        "circle_keywords": [],
        "compare_type": compare_type_from_text(explanation, allowed_compare_types) or "原文概括",
        "translation_pairs": translation_pairs,
        "formatted_explanation": explanation,
        "confidence": "high",
        "source": "preformatted_existing_explanation",
        "warnings": [],
    }


def child_for_model(child: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return {
        "item_id": child.get("item_id"),
        "item_no": child.get("item_no"),
        "source_item_no": child.get("source_item_no"),
        "item_kind": child.get("item_kind"),
        "question": compact(str(child.get("question") or ""), max_chars),
        "options": compact(str(child.get("options") or ""), max_chars),
        "answer": compact(str(child.get("answer") or ""), 200),
        "raw_explanation": compact(str(child.get("explanation") or ""), max_chars),
    }


def render_user_prompt(
    config: dict[str, Any],
    template: str,
    *,
    doc_id: str,
    group: dict[str, Any],
    children: list[dict[str, Any]],
) -> str:
    max_passage_chars = int(config.get("max_passage_chars") or 9000)
    max_child_chars = int(config.get("max_child_text_chars") or 1800)
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
            "children_json": json.dumps([child_for_model(child, max_child_chars) for child in children], ensure_ascii=False, indent=2),
        },
    )


def validate_result(
    parsed: dict[str, Any] | None,
    *,
    doc_id: str,
    group: dict[str, Any],
    children: list[dict[str, Any]],
    allowed_compare_types: set[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    if not isinstance(parsed, dict):
        return False, ["model_output_not_json_object"], {}
    issues: list[str] = []
    cleaned = dict(parsed)
    if cleaned.get("schema") != "english_docx_reading_child_enhancer_v0.1":
        issues.append("schema_mismatch")
    if str(cleaned.get("doc_id") or "") != doc_id:
        issues.append("doc_id_mismatch")
    if str(cleaned.get("group_id") or "") != str(group.get("group_id") or ""):
        issues.append("group_id_mismatch")
    supplied = {str(child.get("item_id") or ""): child for child in children}
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
        compare_type = str(item.get("compare_type") or "").strip()
        if compare_type not in allowed_compare_types:
            issues.append(f"invalid_compare_type:{item_id}:{compare_type}")
        formatted = truncate_after_translation(str(item.get("formatted_explanation") or ""))
        if not has_required_sections(formatted):
            issues.append(f"missing_or_disordered_required_sections:{item_id}")
        if not translation_section_is_clean(formatted):
            issues.append(f"dirty_translation_section:{item_id}")
        for stop in STOP_SECTIONS:
            if section_marker(stop) in formatted:
                issues.append(f"forbidden_section:{item_id}:{stop}")
        circle_keywords = item.get("circle_keywords") or []
        if not isinstance(circle_keywords, list):
            circle_keywords = []
        normalized_circle_keywords: list[str] = []
        for value in circle_keywords:
            keyword = str(value).strip()
            if not keyword:
                continue
            if not keyword_from_question(keyword, str(source_child.get("question") or "")):
                issues.append(f"circle_keyword_not_from_question:{item_id}:{keyword}")
                continue
            normalized_circle_keywords.append(keyword)
        if not normalized_circle_keywords:
            issues.append(f"missing_question_source_circle_keywords:{item_id}")
        formatted = replace_section_content(formatted, "圈", ", ".join(normalized_circle_keywords))
        translation_pairs = clean_translation_pairs(item.get("translation_pairs"))
        option_count = count_option_labels(source_child.get("options"))
        if not translation_pairs:
            issues.append(f"missing_translation_pairs:{item_id}")
        elif len([pair for pair in translation_pairs if pair["role"] == "question"]) != 1:
            issues.append(f"missing_question_translation_pair:{item_id}")
        elif len([pair for pair in translation_pairs if pair["role"] == "option"]) < max(1, option_count):
            issues.append(f"missing_option_translation_pairs:{item_id}")
        normalized_items.append(
            {
                "item_id": item_id,
                "item_no": str(item.get("item_no") or ""),
                "source_item_no": str(item.get("source_item_no") or ""),
                "evidence_scope": str(item.get("evidence_scope") or "").strip(),
                "evidence_text": str(item.get("evidence_text") or "").strip(),
                "circle_keywords": normalized_circle_keywords,
                "compare_type": compare_type,
                "translation_pairs": translation_pairs,
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


def fallback_item(child: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    raw = str(child.get("explanation") or "").strip()
    return {
        "item_id": str(child.get("item_id") or ""),
        "item_no": str(child.get("item_no") or ""),
        "source_item_no": str(child.get("source_item_no") or ""),
        "evidence_scope": "",
        "evidence_text": "",
        "circle_keywords": [],
        "compare_type": "",
        "translation_pairs": [],
        "formatted_explanation": raw,
        "confidence": "low",
        "source": "fallback_raw_explanation",
        "warnings": issues[:8],
    }


def render_translation_pairs(pairs: Any) -> str:
    cleaned = clean_translation_pairs(pairs)
    if not cleaned:
        return ""
    rows: list[str] = []
    for pair in cleaned:
        label = str(pair.get("label") or "").strip()
        prefix = f"{label}. " if label else ""
        rows.append(
            '<div class="translation-pair">'
            f'<div class="translation-original">{html.escape(prefix + str(pair.get("original") or ""))}</div>'
            f'<div class="translation-cn">{html.escape(str(pair.get("translation") or ""))}</div>'
            "</div>"
        )
    return (
        '<section class="field translation-pairs">'
        '<h4>翻译结构</h4>'
        + "".join(rows)
        + "</section>"
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
            updated["evidence_scope"] = item.get("evidence_scope") or ""
            updated["evidence_text"] = item.get("evidence_text") or ""
            updated["circle_keywords"] = item.get("circle_keywords") or []
            updated["compare_type"] = item.get("compare_type") or ""
            updated["translation_pairs"] = item.get("translation_pairs") or []
            updated["formatted_explanation"] = item.get("formatted_explanation") or ""
            updated["explanation_enhancement"] = {
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
    if str(group.get("parent_kind") or "") != "reading":
        return {"group_id": group_id, "status": "skipped_non_reading", "group": group, "issues": [], "usage": {}}
    allowed_compare_types = set(config.get("allowed_compare_types") or ["原词复现", "同义转换", "原文概括"])
    children = [child for child in group.get("children") or [] if isinstance(child, dict)]
    preformatted: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for child in children:
        item = preformatted_item(child, allowed_compare_types)
        if item:
            preformatted[item["item_id"]] = item
        else:
            pending.append(child)
    if not pending:
        enhanced = [preformatted[str(child.get("item_id") or "")] for child in children]
        return {"group_id": group_id, "status": "ok_preformatted", "group": merge_items(group, enhanced, "ok"), "issues": [], "usage": {}}
    if no_model:
        enhanced = list(preformatted.values()) + [fallback_item(child, ["no_model"]) for child in pending]
        return {"group_id": group_id, "status": "needs_review", "group": merge_items(group, enhanced, "needs_review"), "issues": ["no_model"], "usage": {}}

    prompt = render_user_prompt(config, user_template, doc_id=doc_id, group=group, children=pending)
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": prompt})
    timeout = int((config.get("runner") or {}).get("per_group_timeout_seconds") or 240)
    max_attempts = int((config.get("runner") or {}).get("max_group_attempts") or 3)
    last_issues: list[str] = []
    last_usage: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        try:
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
                children=pending,
                allowed_compare_types=allowed_compare_types,
            )
            if ok:
                enhanced_by_id = {item["item_id"]: item for item in cleaned.get("items") or []}
                enhanced = []
                for child in children:
                    child_id = str(child.get("item_id") or "")
                    enhanced.append(preformatted.get(child_id) or enhanced_by_id[child_id])
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
        except Exception as exc:  # noqa: BLE001
            last_issues = [repr(exc)]
            write_json(raw_dir / f"attempt{attempt}.exception.json", {"error": repr(exc)})
    enhanced = list(preformatted.values()) + [fallback_item(child, last_issues or ["model_failed"]) for child in pending]
    return {
        "group_id": group_id,
        "status": "needs_review",
        "group": merge_items(group, enhanced, "needs_review"),
        "issues": last_issues or ["model_failed"],
        "usage": last_usage,
    }


def render_review_html(out_dir: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    groups_html: list[str] = []
    for group in records:
        parent = group.get("parent") or {}
        children_html: list[str] = []
        for child in group.get("children") or []:
            status = (child.get("explanation_enhancement") or {}).get("status") or ""
            warnings = (child.get("explanation_enhancement") or {}).get("warnings") or []
            warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings)
            children_html.append(
                '<article class="child">'
                f'<h3>第 {html.escape(str(child.get("item_no") or ""))} 题 <small>{html.escape(status)}</small></h3>'
                f'{render_field("定位范围", child.get("evidence_scope") or "", "evidence-scope")}'
                f'{render_field("定位材料", child.get("evidence_text") or "", "evidence")}'
                f'{render_field("题干", child.get("question") or "")}'
                f'{render_field("选项", child.get("options") or "")}'
                f'{render_field("答案", child.get("answer") or "", "answer")}'
                f'{render_translation_pairs(child.get("translation_pairs") or [])}'
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
.passage{padding:12px 14px;background:#fbfdff;border:1px solid #e5ebf3;border-radius:8px}.child{border-top:1px solid #e5ebf3;padding:16px 0}.child h3{margin:0 0 10px;color:#1d4ed8;font:700 17px/1.35 "Microsoft YaHei",sans-serif}.child h3 small{color:#64748b;font-size:12px}
.md-table-wrap{overflow-x:auto;margin:8px 0 12px}.md-table{width:100%;border-collapse:collapse;background:#fff;font-size:15px;line-height:1.55}.md-table th,.md-table td{border:1px solid #d7e0ec;padding:8px 10px;vertical-align:top;text-align:left}.md-table th{background:#eef4fb;font-weight:700;color:#0f2742}.md-table tbody tr:nth-child(even){background:#fbfdff}
.answer{background:#fff9eb;border:1px solid #f2e2bd;border-radius:8px;padding:8px 10px}.evidence{background:#f8fafc;border-left:3px solid #64748b;padding:8px 10px}.formatted{background:#fff;border-left:3px solid #0f766e;padding:8px 10px}.warnings{color:#b45309}
.translation-pairs{background:#fbfdff;border:1px solid #dce8f7;border-radius:8px;padding:10px 12px}.translation-pair{padding:6px 0;border-bottom:1px solid #edf2f7}.translation-pair:last-child{border-bottom:0}.translation-original{color:#0f172a;font-weight:600}.translation-cn{color:#b45309;margin-top:2px}
"""
    html_text = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Reading child enhancement review</title><style>{css}</style></head>"
        f'<body><header><h1>Reading Child Enhancement Review</h1><div class="meta">{html.escape(json.dumps(summary, ensure_ascii=False))}</div></header>'
        f'<main>{"".join(groups_html)}</main></body></html>'
    )
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")


def render_field(title: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {html.escape(class_name)}"><h4>{html.escape(title)}</h4>{render_text(text)}</section>'


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_config(args.config)
    payload = read_json(args.input_projection)
    doc_id = args.doc_id or str(payload.get("doc_id") or args.input_projection.parent.name)
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/english_docx_reading_child_enhancer_v0_1")
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
    runner = config.get("runner") or {}
    max_workers = int(args.max_workers or runner.get("max_workers") or 1)
    no_model = bool(args.no_model)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
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
                no_model=no_model,
            )
            for group in groups
        ]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    order = {str(group.get("group_id") or ""): index for index, group in enumerate(groups)}
    results.sort(key=lambda item: order.get(str(item.get("group_id") or ""), 10**9))
    records = [item.get("group") for item in results if item.get("group")]
    usage = Counter()
    for result in results:
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int):
                usage[key] += value
    status_counts = Counter(str(item.get("status") or "unknown") for item in results)
    output = {
        "schema_version": "english_docx_reading_child_enhancer_results.v0.1",
        "doc_id": doc_id,
        "run_id": args.run_id,
        "source_parent_child_projection": safe_rel(args.input_projection),
        "records": records,
        "results": results,
    }
    write_json(out_dir / "reading_child_enhanced.json", output)
    summary = {
        "schema_version": "english_docx_reading_child_enhancer_summary.v0.1",
        "pipeline_id": "english_docx_reading_child_enhancer_v01",
        "run_id": args.run_id,
        "doc_id": doc_id,
        "group_count": len(groups),
        "child_count": sum(len((group or {}).get("children") or []) for group in records),
        "status_counts": dict(status_counts),
        "issue_count": sum(len(item.get("issues") or []) for item in results),
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": config.get("prompt_version"),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "enhanced": safe_rel(out_dir / "reading_child_enhanced.json"),
            "review_html": safe_rel(out_dir / "index.html"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
    }
    write_json(out_dir / "summary.json", summary)
    render_review_html(out_dir, records, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enhance reading child explanations with evidence and fixed sections.")
    parser.add_argument("--input-projection", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
