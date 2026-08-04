from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import visual_transcription_core as vision_core
import visual_transcription_pipeline as vision_pipeline
import visual_transcription_strict_eval_adapter as strict_eval_adapter
import vision_prompt_store

from teachbase.infrastructure.artifact_store import write_json as atomic_write_json
from teachbase.infrastructure.model_call_guard import ModelRetryPolicy, run_model_call_with_retry


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-pro-260215"
ACTIVE_TRANSCRIPTION_PROMPT = vision_prompt_store.get_transcription_prompt_bundle()
PROMPT_VERSION = ACTIVE_TRANSCRIPTION_PROMPT["prompt_version"]
RAW_BLOCKS_PROMPT = vision_prompt_store.get_raw_blocks_prompt_bundle()
FIELD_MAPPING_PROMPT = vision_prompt_store.get_field_mapping_prompt_bundle()
FORMAT_NORMALIZE_PROMPT = vision_prompt_store.get_format_normalize_prompt_bundle()
PIPELINE_PROMPT_VERSION = (
    f"{RAW_BLOCKS_PROMPT['prompt_version']}"
    f"+{FIELD_MAPPING_PROMPT['prompt_version']}"
    f"+{FORMAT_NORMALIZE_PROMPT['prompt_version']}"
)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: object) -> None:
    atomic_write_json(path, payload)


def append_jsonl(path: Path, payload: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_live_progress(
    out_dir: Path,
    *,
    total: int,
    records: list[dict],
    current_index: int,
    current_item: dict | None,
    current_record_id: str = "",
    phase: str = "",
    started_at: str = "",
    extra: dict | None = None,
) -> None:
    ok_count = sum(1 for item in records if item.get("status") == "ok")
    failed_count = sum(1 for item in records if item.get("status") == "failed")
    prepared_count = sum(1 for item in records if item.get("status") == "prepared")
    payload = {
        "schema": "visual_transcription_live_progress_v0.1",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "phase": phase,
        "total": int(total),
        "completed": len(records),
        "remaining": max(0, int(total) - len(records)),
        "ok_count": ok_count,
        "failed_count": failed_count,
        "prepared_count": prepared_count,
        "current_index": int(current_index),
        "current_question_id": str((current_item or {}).get("question_id", "") or ""),
        "current_record_id": str(current_record_id or ""),
        "current_started_at": started_at,
        "last_records": [
            {
                "question_id": str(item.get("question_id", "") or ""),
                "record_id": str(item.get("record_id", "") or ""),
                "status": str(item.get("status", "") or ""),
                "error": str(item.get("error", "") or "")[:240],
                "latency_seconds": item.get("latency_seconds", 0),
            }
            for item in records[-8:]
        ],
        "extra": extra or {},
    }
    write_json(out_dir / "live_progress.json", payload)
    append_jsonl(out_dir / "live_progress_events.jsonl", payload)


def restore_latex_control_prefixes(value: object) -> object:
    if isinstance(value, str):
        # Some model outputs use raw LaTeX like \triangle or \because inside JSON strings.
        # JSON decoders treat \t, \b, \f, \r as control escapes, so we restore them back to
        # literal backslash-prefixed macros before storing the transcription.
        return value.replace("\t", "\\t").replace("\b", "\\b").replace("\f", "\\f").replace("\r", "\\r")
    if isinstance(value, list):
        return [restore_latex_control_prefixes(item) for item in value]
    if isinstance(value, dict):
        return {key: restore_latex_control_prefixes(item) for key, item in value.items()}
    return value


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "").strip())
    slug = slug.strip("._-")
    return slug or "item"


def looks_mojibake(text: str) -> bool:
    sample = normalize_text(text)
    if not sample:
        return False
    markers = ("锛", "鈻", "銆", "蟺", "鍒", "渚", "鏁", "瑙", "鐨", "涓", "鍙", "閫")
    marker_hits = sum(sample.count(marker) for marker in markers)
    return marker_hits >= 2


def clean_hint_text(text: str) -> str:
    sample = normalize_text(text)
    if not sample or looks_mojibake(sample):
        return ""
    return sample


def resolve_path(raw_path: str, base_dir: Path | None = None) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    if base_dir is not None:
        return (base_dir / candidate).resolve()
    return candidate.resolve()


def resolve_existing_path(raw_path: str, base_dirs: list[Path]) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    for base_dir in base_dirs:
        resolved = (base_dir / candidate).resolve()
        if resolved.exists():
            return resolved
    return (base_dirs[0] / candidate).resolve()


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("empty_model_response")
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    def _load_json(payload: str) -> dict:
        return restore_latex_control_prefixes(json.loads(payload))

    try:
        return _load_json(clean)
    except json.JSONDecodeError:
        pass

    def _repair_json_string_backslashes(payload: str) -> str:
        out: list[str] = []
        in_string = False
        i = 0
        while i < len(payload):
            ch = payload[i]
            if not in_string:
                out.append(ch)
                if ch == '"':
                    in_string = True
                i += 1
                continue

            if ch == '"':
                backslash_count = 0
                j = i - 1
                while j >= 0 and payload[j] == "\\":
                    backslash_count += 1
                    j -= 1
                out.append(ch)
                if backslash_count % 2 == 0:
                    in_string = False
                i += 1
                continue

            if ch == "\n":
                out.append("\\n")
                i += 1
                continue

            if ch == "\r":
                out.append("\\r")
                i += 1
                continue

            if ch != "\\":
                out.append(ch)
                i += 1
                continue

            next_ch = payload[i + 1] if i + 1 < len(payload) else ""
            if next_ch == "\\":
                out.append("\\\\")
                i += 2
                continue
            if next_ch in {'"', "/"}:
                out.append("\\" + next_ch)
                i += 2
                continue
            if next_ch == "u" and i + 5 < len(payload):
                hex_part = payload[i + 2 : i + 6]
                if re.fullmatch(r"[0-9A-Fa-f]{4}", hex_part):
                    out.append(payload[i : i + 6])
                    i += 6
                    continue
            if next_ch in "bfnrt":
                next_next = payload[i + 2] if i + 2 < len(payload) else ""
                if next_next and next_next.isalpha():
                    out.append("\\\\")
                    i += 1
                    continue
                out.append("\\" + next_ch)
                i += 2
                continue

            out.append("\\\\")
            i += 1

        return "".join(out)

    def _load_with_relaxed_backslashes(payload: str) -> dict:
        repaired = _repair_json_string_backslashes(payload)
        return _load_json(repaired)

    start = clean.find("{")
    if start < 0:
        raise ValueError("json_object_not_found")
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(clean)):
        ch = clean[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                block = clean[start : idx + 1]
                try:
                    return _load_json(block)
                except json.JSONDecodeError:
                    return _load_with_relaxed_backslashes(block)
    raise ValueError("json_object_not_closed")


INLINE_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)
MATH_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "：": ":",
        "；": ";",
        "＜": "<",
        "＞": ">",
        "－": "-",
        "＝": "=",
    }
)


def normalize_math_punctuation(text: object) -> object:
    if not isinstance(text, str):
        return text

    def _replace(match: re.Match[str]) -> str:
        block_body = match.group(1)
        inline_body = match.group(2)
        if block_body is not None:
            return "$$" + block_body.translate(MATH_PUNCT_TRANSLATION) + "$$"
        return "$" + inline_body.translate(MATH_PUNCT_TRANSLATION) + "$"

    return INLINE_MATH_RE.sub(_replace, text)


def normalize_math_delimiters(text: object) -> object:
    if not isinstance(text, str):
        return text
    normalized = text.replace("\\[", "$$").replace("\\]", "$$")
    normalized = normalized.replace("\\(", "$").replace("\\)", "$")
    return normalized


def normalize_common_notation(text: object) -> object:
    if not isinstance(text, str):
        return text
    normalized = text
    normalized = normalized.replace("\\neq", "\\ne")
    normalized = normalized.replace("$\\therefore$", "∴")
    normalized = normalized.replace("$\\because$", "∵")
    normalized = normalized.replace("\\therefore", "∴")
    normalized = normalized.replace("\\because", "∵")
    normalized = normalized.replace("[解答]", "【解答】")
    normalized = normalized.replace("[分析]", "【分析】")
    normalized = normalized.replace("[证明]", "【证明】")
    normalized = normalized.replace("[点评]", "【点评】")
    normalized = normalized.replace("[答案]", "【答案】")
    return normalized


def normalize_transcription_fields(parsed: dict) -> dict:
    normalized = dict(parsed)
    for field in ("stem_text_md", "answer_text_md", "analysis_text_md", "handwriting_text_md"):
        value = normalized.get(field, "")
        value = normalize_math_delimiters(value)
        value = normalize_math_punctuation(value)
        value = normalize_common_notation(value)
        normalized[field] = value

    normalized["stem_requires_image"] = bool(normalized.get("stem_requires_image", False))
    normalized["analysis_requires_image"] = bool(normalized.get("analysis_requires_image", False))
    normalized["handwriting_requires_review"] = bool(normalized.get("handwriting_requires_review", False))
    if not isinstance(normalized.get("handwriting_consistency"), dict):
        normalized["handwriting_consistency"] = {}
    uncertain_spans = normalized.get("uncertain_spans", []) or []
    normalized["uncertain_spans"] = uncertain_spans

    for span in uncertain_spans:
        if not isinstance(span, dict):
            continue
        field = str(span.get("field", "") or "").strip().lower()
        reason = normalize_text(span.get("reason", ""))
        text = normalize_text(span.get("text", ""))
        if field == "stem":
            normalized["stem_requires_image"] = True
        if field == "analysis":
            normalized["analysis_requires_image"] = True
        high_risk_text = f"{reason} {text}".lower()
        high_risk = any(
            marker in high_risk_text
            for marker in ("cut off", "incomplete", "truncated", "diagram", "figure", "table")
        )
        if field == "stem" and high_risk:
            normalized["stem_requires_image"] = True
        if field == "analysis" and high_risk:
            normalized["analysis_requires_image"] = True

    return normalized


def derive_record_id(item: dict, source_json_path: Path) -> str:
    explicit = str(item.get("sample_id", "") or item.get("record_id", "")).strip()
    if explicit:
        return safe_slug(explicit)
    parts = [
        safe_slug(item.get("tag", "")),
        safe_slug(source_json_path.parent.name),
        safe_slug(item.get("question_id", "")),
    ]
    return "_".join(part for part in parts if part)


def _build_prompt_blocks(question: dict, record_id: str) -> tuple[str, str]:
    context_lines = [f"- record_id: {record_id}", f"- question_id: {question.get('question_id', '')}"]
    for label, value in (
        ("checkpoint", clean_hint_text(question.get("checkpoint", ""))),
        ("component_label", clean_hint_text(question.get("component_label", ""))),
        ("local_number", clean_hint_text(question.get("local_number", ""))),
    ):
        if value:
            context_lines.append(f"- {label}: {value}")

    hint_lines = []
    for label, value in (
        ("auto_stem_text", clean_hint_text(question.get("stem_text", ""))),
        ("auto_answer_text", clean_hint_text(question.get("answer_text", ""))),
        ("auto_analysis_text", clean_hint_text(question.get("analysis_text", ""))),
    ):
        if value:
            hint_lines.append(f"- {label}: {value}")

    return "\n".join(context_lines), "\n".join(hint_lines) if hint_lines else "- none"


def _render_transcription_prompt(question: dict, record_id: str, variant: str) -> str:
    bundle = vision_prompt_store.get_transcription_prompt_bundle(variant)
    context_block, hint_block = _build_prompt_blocks(question, record_id)
    return vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "CONTEXT_LINES": context_block,
            "HINT_LINES": hint_block,
        },
    )


def build_active_prompt(question: dict, record_id: str) -> str:
    return _render_transcription_prompt(question, record_id, ACTIVE_TRANSCRIPTION_PROMPT["variant"])


def build_raw_blocks_prompt(question: dict, record_id: str) -> str:
    context_block, hint_block = _build_prompt_blocks(question, record_id)
    return vision_prompt_store.render_template(
        RAW_BLOCKS_PROMPT["user_template"],
        {
            "CONTEXT_LINES": context_block,
            "HINT_LINES": hint_block,
        },
    )


def build_field_mapping_prompt(question: dict, record_id: str, raw_blocks_payload: dict) -> str:
    context_block, hint_block = _build_prompt_blocks(question, record_id)
    raw_blocks_json = json.dumps(raw_blocks_payload, ensure_ascii=False, indent=2)
    return vision_prompt_store.render_template(
        FIELD_MAPPING_PROMPT["user_template"],
        {
            "CONTEXT_LINES": context_block,
            "HINT_LINES": hint_block,
            "RAW_BLOCKS_JSON": raw_blocks_json,
        },
    )


def build_format_normalize_prompt(question: dict, record_id: str, field_mapping_payload: dict) -> str:
    context_block, hint_block = _build_prompt_blocks(question, record_id)
    field_mapping_json = json.dumps(field_mapping_payload, ensure_ascii=False, indent=2)
    return vision_prompt_store.render_template(
        FORMAT_NORMALIZE_PROMPT["user_template"],
        {
            "CONTEXT_LINES": context_block,
            "HINT_LINES": hint_block,
            "FIELD_MAPPING_JSON": field_mapping_json,
        },
    )


def build_prompt(question: dict, record_id: str) -> str:
    context_lines = [f"- record_id: {record_id}", f"- question_id: {question.get('question_id', '')}"]
    for label, value in (
        ("checkpoint", clean_hint_text(question.get("checkpoint", ""))),
        ("component_label", clean_hint_text(question.get("component_label", ""))),
        ("local_number", clean_hint_text(question.get("local_number", ""))),
    ):
        if value:
            context_lines.append(f"- {label}: {value}")

    hint_lines = []
    for label, value in (
        ("auto_stem_text", clean_hint_text(question.get("stem_text", ""))),
        ("auto_answer_text", clean_hint_text(question.get("answer_text", ""))),
        ("auto_analysis_text", clean_hint_text(question.get("analysis_text", ""))),
    ):
        if value:
            hint_lines.append(f"- {label}: {value}")

    return (
        "You are a strict K12 teacher-handout transcription assistant.\n"
        "Task: transcribe one question from images into structured fields.\n"
        "The images are the source of truth. The auto text hints are noisy and may be wrong.\n"
        "Return JSON only. Do not add commentary or markdown fences.\n\n"
        "You may receive up to three images in this order:\n"
        "1. question_image: the full question crop\n"
        "2. stem_image: the stem-focused crop when available\n"
        "3. analysis_image: the answer/analysis-focused crop when available\n\n"
        "Rules:\n"
        "1. Preserve visible wording as faithfully as possible.\n"
        "2. Use Markdown for prose.\n"
        "3. Use standard LaTeX for math. Use $...$ for inline math and $$...$$ for display math when needed. Inside math, use ASCII punctuation such as , () [] : ; < > = - instead of full-width Chinese punctuation.\n"
        "4. Do not invent unreadable text. If uncertain, keep the readable part and list the uncertain span.\n"
        "5. If the stem or analysis depends on a diagram, table, figure, or a cropped / incomplete image, still transcribe visible text and set the matching *_requires_image field to true.\n"
        "6. analysis_text_md must preserve every teacher-side explanation block that belongs to this question, including labels such as 分析, 解答, 证明, 思路, 点评, 结论. Merge them into one field in reading order. Do not drop one block just because another explanation block is present.\n"
        "7. For objective answers, keep only the answer content, such as A, C, $\\frac{3}{4}$, or $\\sqrt{2}$.\n"
        "8. If there is no standalone answer field, use an empty string for answer_text_md.\n"
        "9. If a diagram is the main evidence and text alone is insufficient, do not hallucinate the missing geometry conditions.\n\n"
        "Context:\n"
        f"{chr(10).join(context_lines)}\n\n"
        "Optional helper hints. Ignore them when they conflict with the image:\n"
        f"{chr(10).join(hint_lines) if hint_lines else '- none'}\n\n"
        "Output schema:\n"
        "{\n"
        '  "record_id": "...",\n'
        '  "question_id": "...",\n'
        '  "stem_text_md": "...",\n'
        '  "answer_text_md": "...",\n'
        '  "analysis_text_md": "...",\n'
        '  "stem_requires_image": true,\n'
        '  "analysis_requires_image": true,\n'
        '  "uncertain_spans": [\n'
        '    {"field": "stem|answer|analysis", "text": "...", "reason": "formula|symbol|diagram|table|other"}\n'
        "  ]\n"
        "}\n"
    )


def build_prompt_v2(question: dict, record_id: str) -> str:
    context_lines = [f"- record_id: {record_id}", f"- question_id: {question.get('question_id', '')}"]
    for label, value in (
        ("checkpoint", clean_hint_text(question.get("checkpoint", ""))),
        ("component_label", clean_hint_text(question.get("component_label", ""))),
        ("local_number", clean_hint_text(question.get("local_number", ""))),
    ):
        if value:
            context_lines.append(f"- {label}: {value}")

    hint_lines = []
    for label, value in (
        ("auto_stem_text", clean_hint_text(question.get("stem_text", ""))),
        ("auto_answer_text", clean_hint_text(question.get("answer_text", ""))),
        ("auto_analysis_text", clean_hint_text(question.get("analysis_text", ""))),
    ):
        if value:
            hint_lines.append(f"- {label}: {value}")

    return (
        "You are a strict K12 teacher-handout transcription assistant.\n"
        "Task: transcribe one question from images into structured fields.\n"
        "The images are the source of truth. The auto text hints are noisy and may be wrong.\n"
        "Literal-copy mode is required: copy visible text, symbols, and line order faithfully.\n"
        "Return JSON only. Do not add commentary or markdown fences.\n\n"
        "You may receive up to three images in this order:\n"
        "1. question_image: the full question crop\n"
        "2. stem_image: the stem-focused crop when available\n"
        "3. analysis_image: the answer/analysis-focused crop when available\n\n"
        "Rules:\n"
        "1. Preserve visible wording as faithfully as possible. Do not summarize, rewrite, explain, or convert visible content into your own wording.\n"
        "2. Use Markdown for prose.\n"
        "3. Use standard LaTeX for math. Always use $...$ for inline math and $$...$$ for display math. Never use \\(...\\) or \\[...\\].\n"
        "4. Inside math, use ASCII punctuation such as , () [] : ; < > = - instead of full-width Chinese punctuation.\n"
        "5. Keep special visible labels and symbols when they are readable, such as 【例1】, 【分析】, 【解答】, 【证明】, ∵, ∴, ⊙, △, ▱, and option labels like A. B. C. D.\n"
        "6. Do not invent unreadable or missing text. If the crop starts mid-sentence, ends early, or hides part of a field, transcribe only the visible fragment. Do not infer, and do not add notes like 'only visible options' or 'image missing text' inside the field.\n"
        "7. If a field is not explicitly visible, leave that field as an empty string. In particular, if there is no standalone answer region, answer_text_md must be empty even if the answer can be inferred from analysis.\n"
        "8. If the stem or analysis depends on a diagram, table, figure, or a cropped / incomplete image, still transcribe visible text and set the matching *_requires_image field to true.\n"
        "9. analysis_text_md must preserve every teacher-side explanation block that belongs to this question, including labels such as 分析, 解答, 证明, 思路, 点评, 结论. Merge them into one field in reading order. Do not drop one block just because another explanation block is present.\n"
        "10. Keep line structure close to the source. For systems, grouped equations, or proof conditions, preserve the original grouping. When needed, use $$\\begin{cases} ... \\\\ ... \\end{cases}$$.\n"
        "11. For geometry or figure-dependent answers, do not describe the picture in natural language unless those words are already visible in the source. If the source only says '如图', keep '如图'.\n"
        "12. For objective answers, keep only the answer content, such as A, C, $\\frac{3}{4}$, or $\\sqrt{2}$.\n"
        "13. If a diagram is the main evidence and text alone is insufficient, do not hallucinate the missing geometry conditions.\n\n"
        "Context:\n"
        f"{chr(10).join(context_lines)}\n\n"
        "Optional helper hints. Ignore them when they conflict with the image:\n"
        f"{chr(10).join(hint_lines) if hint_lines else '- none'}\n\n"
        "Output schema:\n"
        "{\n"
        '  "record_id": "...",\n'
        '  "question_id": "...",\n'
        '  "stem_text_md": "...",\n'
        '  "answer_text_md": "...",\n'
        '  "analysis_text_md": "...",\n'
        '  "stem_requires_image": true,\n'
        '  "analysis_requires_image": true,\n'
        '  "uncertain_spans": [\n'
        '    {"field": "stem|answer|analysis", "text": "...", "reason": "formula|symbol|diagram|table|other"}\n'
        "  ]\n"
        "}\n"
    )


def build_prompt_v3(question: dict, record_id: str) -> str:
    context_lines = [f"- record_id: {record_id}", f"- question_id: {question.get('question_id', '')}"]
    for label, value in (
        ("checkpoint", clean_hint_text(question.get("checkpoint", ""))),
        ("component_label", clean_hint_text(question.get("component_label", ""))),
        ("local_number", clean_hint_text(question.get("local_number", ""))),
    ):
        if value:
            context_lines.append(f"- {label}: {value}")

    hint_lines = []
    for label, value in (
        ("auto_stem_text", clean_hint_text(question.get("stem_text", ""))),
        ("auto_answer_text", clean_hint_text(question.get("answer_text", ""))),
        ("auto_analysis_text", clean_hint_text(question.get("analysis_text", ""))),
    ):
        if value:
            hint_lines.append(f"- {label}: {value}")

    return (
        "You are a strict K12 teacher-handout transcription assistant.\n"
        "Task: transcribe one question from images into structured fields.\n"
        "The images are the source of truth. The auto text hints are noisy and may be wrong.\n"
        "Literal-copy mode is required: copy visible text, symbols, and line order faithfully.\n"
        "Return JSON only. Do not add commentary or markdown fences.\n\n"
        "You may receive up to three images in this order:\n"
        "1. question_image: the full question crop\n"
        "2. stem_image: the stem-focused crop when available\n"
        "3. analysis_image: the answer/analysis-focused crop when available\n\n"
        "Rules:\n"
        "1. Preserve visible wording as faithfully as possible. Do not summarize, rewrite, explain, or convert visible content into your own wording.\n"
        "2. Use Markdown for prose.\n"
        "3. Use standard LaTeX for math. Always use $...$ for inline math and $$...$$ for display math. Never use \\(...\\) or \\[...\\].\n"
        "4. Inside math, use ASCII punctuation such as , () [] : ; < > = - instead of full-width Chinese punctuation.\n"
        "5. Keep special visible labels and symbols when they are readable, such as example headers, analysis headers, answer headers, proof headers, option labels, circled item markers, and geometry symbols.\n"
        "6. Do not invent unreadable or missing text. If the crop starts mid-sentence, ends early, or hides part of a field, transcribe only the visible fragment. Do not infer, and do not add notes like 'only visible options' or 'image missing text' inside the field.\n"
        "7. If a field is not explicitly visible, leave that field as an empty string. In particular, if there is no standalone answer region, answer_text_md must be empty even if the answer can be inferred from analysis.\n"
        "8. If the stem or analysis depends on a diagram, table, figure, or a cropped / incomplete image, still transcribe visible text and set the matching *_requires_image field to true.\n"
        "9. analysis_text_md must preserve every teacher-side explanation block that belongs to this question, including labels such as 分析, 解答, 证明, 思路, 点评, 结论. Merge them into one field in reading order. Do not drop one block just because another explanation block is present.\n"
        "10. Keep line structure close to the source. For options, systems, grouped equations, or proof conditions, preserve the original grouping and line breaks when visible. When needed, use $$\\begin{cases} ... \\\\ ... \\end{cases}$$.\n"
        "11. For geometry or figure-dependent answers, do not describe the picture in natural language unless those words are already visible in the source. If the source only says '如图', keep '如图'.\n"
        "12. For objective answers, keep only the answer content, such as A, C, $\\frac{3}{4}$, or $\\sqrt{2}$.\n"
        "13. answer_text_md must contain only the standalone answer block. Do not copy proof steps, derivations, or long explanation sentences into answer_text_md.\n"
        "14. If the source has multiple subquestions like (1) (2) (3), preserve the visible subquestion indexes in answer_text_md and analysis_text_md. Do not drop an earlier subquestion answer while keeping a later one.\n"
        "15. Never drop visible math object labels or geometry point names such as A, B, C, D, E, F, G, M, N, P, Q, or vector / angle labels.\n"
        "16. If answer_text_md already captures the standalone answer, do not repeat a leading 答案 header inside analysis_text_md. Keep the explanation blocks only.\n"
        "17. If a diagram is the main evidence and text alone is insufficient, do not hallucinate the missing geometry conditions.\n\n"
        "Context:\n"
        f"{chr(10).join(context_lines)}\n\n"
        "Optional helper hints. Ignore them when they conflict with the image:\n"
        f"{chr(10).join(hint_lines) if hint_lines else '- none'}\n\n"
        "Output schema:\n"
        "{\n"
        '  "record_id": "...",\n'
        '  "question_id": "...",\n'
        '  "stem_text_md": "...",\n'
        '  "answer_text_md": "...",\n'
        '  "analysis_text_md": "...",\n'
        '  "stem_requires_image": true,\n'
        '  "analysis_requires_image": true,\n'
        '  "uncertain_spans": [\n'
        '    {"field": "stem|answer|analysis", "text": "...", "reason": "formula|symbol|diagram|table|other"}\n'
        "  ]\n"
        "}\n"
    )


def build_prompt(question: dict, record_id: str) -> str:
    return _render_transcription_prompt(question, record_id, "v1")


def build_prompt_v2(question: dict, record_id: str) -> str:
    return _render_transcription_prompt(question, record_id, "v2")


def build_prompt_v3(question: dict, record_id: str) -> str:
    return _render_transcription_prompt(question, record_id, "v3")


def safe_normalize_transcription_fields(
    parsed: dict,
    *,
    record_id: str = "",
    question_id: str = "",
    visual_refs: dict | None = None,
    prompt_version: str = "",
    model_name: str = "",
) -> dict:
    return vision_core.safe_normalize_transcription_payload(
        parsed,
        record_id=record_id,
        question_id=question_id,
        visual_refs=visual_refs,
        prompt_version=prompt_version,
        model_name=model_name,
    )


def normalize_transcription_fields(parsed: dict) -> dict:
    return strict_eval_adapter.normalize_transcription_fields(parsed)


def model_operation_id(label: str, model: str, prompt: str, image_paths: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(label.encode("utf-8"))
    digest.update(model.encode("utf-8"))
    digest.update(prompt.encode("utf-8"))
    for image_path in image_paths:
        digest.update(str(image_path).encode("utf-8"))
    return f"{label}:{model}:{digest.hexdigest()[:16]}"


def _call_model_with_system_once(
    api_key: str,
    model: str,
    system_prompt: str,
    prompt: str,
    image_paths: list[Path],
) -> dict:
    user_content: list[dict] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        user_content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionResetError) as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    content = payload["choices"][0]["message"]["content"]
    return {
        "raw_response": payload,
        "raw_content": content,
        "usage": payload.get("usage", {}) or {},
    }


def call_model_with_system(
    api_key: str,
    model: str,
    system_prompt: str,
    prompt: str,
    image_paths: list[Path],
    *,
    checkpoint_path: Path | None = None,
    operation_label: str = "visual_transcription_model_node",
) -> dict:
    return run_model_call_with_retry(
        lambda: _call_model_with_system_once(api_key, model, system_prompt, prompt, image_paths),
        operation_id=model_operation_id(operation_label, model, prompt, image_paths),
        checkpoint_path=checkpoint_path,
        policy=ModelRetryPolicy(max_attempts=3, initial_delay_seconds=1.0, backoff_multiplier=2.5, max_delay_seconds=2.5),
        sleep=time.sleep,
        metadata={"node": operation_label, "model": model, "image_count": len(image_paths)},
    )


def call_model(api_key: str, model: str, prompt: str, image_paths: list[Path], *, checkpoint_path: Path | None = None) -> dict:
    return call_model_with_system(
        api_key,
        model,
        ACTIVE_TRANSCRIPTION_PROMPT["system_prompt"],
        prompt,
        image_paths,
        checkpoint_path=checkpoint_path,
        operation_label="legacy_visual_transcription_model_node",
    )


def call_raw_blocks_model(api_key: str, model: str, prompt: str, image_paths: list[Path], *, checkpoint_path: Path | None = None) -> dict:
    return call_model_with_system(
        api_key,
        model,
        RAW_BLOCKS_PROMPT["system_prompt"],
        prompt,
        image_paths,
        checkpoint_path=checkpoint_path,
        operation_label="raw_blocks_model_node",
    )


def call_field_mapping_model(api_key: str, model: str, prompt: str, image_paths: list[Path], *, checkpoint_path: Path | None = None) -> dict:
    return call_model_with_system(
        api_key,
        model,
        FIELD_MAPPING_PROMPT["system_prompt"],
        prompt,
        image_paths,
        checkpoint_path=checkpoint_path,
        operation_label="field_mapping_model_node",
    )


def call_format_normalize_model(api_key: str, model: str, prompt: str, image_paths: list[Path], *, checkpoint_path: Path | None = None) -> dict:
    return call_model_with_system(
        api_key,
        model,
        FORMAT_NORMALIZE_PROMPT["system_prompt"],
        prompt,
        image_paths,
        checkpoint_path=checkpoint_path,
        operation_label="format_normalize_model_node",
    )


def load_source_questions(source_json_path: Path) -> dict[str, dict]:
    payload = read_json(source_json_path)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    return {str(question["question_id"]): question for question in questions}


def build_items_from_manifest(manifest_path: Path) -> list[dict]:
    payload = read_json(manifest_path)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    normalized: list[dict] = []
    base_dirs = [manifest_path.parent.resolve(), Path.cwd().resolve()]
    for item in items:
        normalized.append(
            {
                "sample_id": str(item.get("sample_id", "")).strip(),
                "source_transcription_json": str(
                    resolve_existing_path(item["source_transcription_json"], base_dirs)
                ),
                "question_id": str(item["question_id"]),
                "tag": str(item.get("tag", "")).strip(),
            }
        )
    return normalized


def build_items_from_args(source_json_path: Path, question_ids: list[str], record_prefix: str) -> list[dict]:
    prefix = safe_slug(record_prefix) if record_prefix else ""
    items: list[dict] = []
    for question_id in question_ids:
        sample_id = f"{prefix}_{question_id}" if prefix else question_id
        items.append(
            {
                "sample_id": sample_id,
                "source_transcription_json": str(source_json_path.resolve()),
                "question_id": question_id,
                "tag": prefix,
            }
        )
    return items


def collect_image_paths(question: dict) -> list[Path]:
    ordered_keys = ["question_image", "stem_image", "analysis_image"]
    paths: list[Path] = []
    seen: set[str] = set()
    for key in ordered_keys:
        raw = str(question.get(key, "") or "").strip()
        if not raw or raw in seen:
            continue
        path = Path(raw)
        if path.exists():
            paths.append(path)
            seen.add(raw)
    return paths


def summarize_record(item: dict, status: str, parsed: dict | None = None, error: str = "") -> dict:
    summary = {
        "record_id": item["record_id"],
        "question_id": item["question_id"],
        "source_transcription_json": item["source_transcription_json"],
        "status": status,
        "tag": item.get("tag", ""),
    }
    if parsed:
        summary.update(
            {
                "stem_text_md": parsed.get("stem_text_md", ""),
                "answer_text_md": parsed.get("answer_text_md", ""),
                "analysis_text_md": parsed.get("analysis_text_md", ""),
                "handwriting_text_md": parsed.get("handwriting_text_md", ""),
                "handwriting_requires_review": parsed.get("handwriting_requires_review", False),
                "handwriting_consistency": parsed.get("handwriting_consistency", {}),
                "stem_requires_image": parsed.get("stem_requires_image", False),
                "analysis_requires_image": parsed.get("analysis_requires_image", False),
                "uncertain_span_count": len(parsed.get("uncertain_spans", []) or []),
                "latency_seconds": item.get("latency_seconds", 0.0),
                "usage_total_tokens": (item.get("usage", {}) or {}).get("total_tokens", 0),
                "usage_prompt_tokens": (item.get("usage", {}) or {}).get("prompt_tokens", 0),
                "usage_completion_tokens": (item.get("usage", {}) or {}).get("completion_tokens", 0),
            }
        )
    if error:
        summary["error"] = error
    return summary


def print_json(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def aggregate_usage(records: list[dict]) -> dict:
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "image_tokens": 0,
    }
    for record in records:
        usage = record.get("usage", {}) or {}
        for key in totals:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                totals[key] += value
    return totals


def aggregate_latency(records: list[dict]) -> dict:
    values = [
        float(record.get("latency_seconds"))
        for record in records
        if isinstance(record.get("latency_seconds"), (int, float))
    ]
    if not values:
        return {
            "count": 0,
            "avg_seconds": 0.0,
            "max_seconds": 0.0,
            "min_seconds": 0.0,
        }
    return {
        "count": len(values),
        "avg_seconds": round(sum(values) / len(values), 3),
        "max_seconds": round(max(values), 3),
        "min_seconds": round(min(values), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Use a visual model to transcribe teacher-handout questions field by field.")
    parser.add_argument("--manifest")
    parser.add_argument("--source-transcription-json")
    parser.add_argument("--question-ids", default="")
    parser.add_argument("--record-prefix", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    raw_dir = out_dir / "raw"
    ensure_dir(raw_dir)

    if args.manifest:
        items = build_items_from_manifest(Path(args.manifest).resolve())
    else:
        if not args.source_transcription_json:
            raise SystemExit("missing_source_transcription_json")
        question_ids = [item.strip() for item in args.question_ids.split(",") if item.strip()]
        if not question_ids:
            raise SystemExit("missing_question_ids")
        items = build_items_from_args(Path(args.source_transcription_json), question_ids, args.record_prefix)

    if args.limit and args.limit > 0:
        items = items[: args.limit]

    source_cache: dict[str, dict[str, dict]] = {}
    records: list[dict] = []
    write_live_progress(
        out_dir,
        total=len(items),
        records=records,
        current_index=0,
        current_item=None,
        phase="initialized",
        extra={"prepare_only": bool(args.prepare_only), "model": args.model},
    )

    for index, item in enumerate(items, start=1):
        source_json_path = Path(item["source_transcription_json"]).resolve()
        record_id = derive_record_id(item, source_json_path)
        current_started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        write_live_progress(
            out_dir,
            total=len(items),
            records=records,
            current_index=index,
            current_item=item,
            current_record_id=record_id,
            phase="question_started",
            started_at=current_started_at,
        )
        if str(source_json_path) not in source_cache:
            source_cache[str(source_json_path)] = load_source_questions(source_json_path)
        source_questions = source_cache[str(source_json_path)]
        question = source_questions.get(item["question_id"])
        if not question:
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "failed",
                    "error": "question_not_found",
                    "tag": item.get("tag", ""),
                }
            )
            write_live_progress(
                out_dir,
                total=len(items),
                records=records,
                current_index=index,
                current_item=item,
                current_record_id=record_id,
                phase="question_finished",
                started_at=current_started_at,
            )
            continue

        if not args.prepare_only and not args.api_key:
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "failed",
                    "error": "missing_api_key",
                    "tag": item.get("tag", ""),
                }
            )
            write_live_progress(
                out_dir,
                total=len(items),
                records=records,
                current_index=index,
                current_item=item,
                current_record_id=record_id,
                phase="question_finished",
                started_at=current_started_at,
            )
            continue

        pipeline_result = vision_pipeline.run_question_pipeline(
            item=item,
            question=question,
            source_json_path=source_json_path,
            record_id=record_id,
            model_name=args.model,
            prompt_version=PIPELINE_PROMPT_VERSION,
            api_key=str(args.api_key or ""),
            prepare_only=bool(args.prepare_only),
            raw_blocks_prompt_builder=build_raw_blocks_prompt,
            raw_blocks_call_model_fn=call_raw_blocks_model,
            field_mapping_prompt_builder=build_field_mapping_prompt,
            field_mapping_call_model_fn=call_field_mapping_model,
            format_normalize_prompt_builder=build_format_normalize_prompt,
            format_normalize_call_model_fn=call_format_normalize_model,
            extract_json_fn=extract_json_block,
            checkpoint_root=raw_dir / "model_call_checkpoints",
        )

        prepared_payload = pipeline_result.get("prepared_payload", {}) or {}
        write_json(raw_dir / f"{record_id}.prepared.json", prepared_payload)

        raw_blocks_response = pipeline_result.get("raw_blocks_response", {}) or {}
        raw_blocks_content = str(pipeline_result.get("raw_blocks_content", "") or "")
        field_mapping_response = pipeline_result.get("field_mapping_response", {}) or {}
        field_mapping_content = str(pipeline_result.get("field_mapping_content", "") or "")
        format_normalize_response = pipeline_result.get("format_normalize_response", {}) or {}
        format_normalize_content = str(pipeline_result.get("format_normalize_content", "") or "")
        record = pipeline_result.get("record", {}) or {}
        status = str(record.get("status", "") or "")

        if raw_blocks_response:
            if status == "ok":
                write_json(raw_dir / f"{record_id}.raw_blocks.response.json", raw_blocks_response)
            else:
                write_json(raw_dir / f"{record_id}.raw_blocks.response_failed_parse.json", raw_blocks_response)
        if raw_blocks_content:
            target_name = "raw_blocks.response.txt" if status == "ok" else "raw_blocks.response_failed_parse.txt"
            (raw_dir / f"{record_id}.{target_name}").write_text(raw_blocks_content, encoding="utf-8")

        if field_mapping_response:
            if status == "ok":
                write_json(raw_dir / f"{record_id}.field_mapping.response.json", field_mapping_response)
            else:
                write_json(raw_dir / f"{record_id}.field_mapping.response_failed_parse.json", field_mapping_response)
        if field_mapping_content:
            target_name = "field_mapping.response.txt" if status == "ok" else "field_mapping.response_failed_parse.txt"
            (raw_dir / f"{record_id}.{target_name}").write_text(field_mapping_content, encoding="utf-8")
        if format_normalize_response:
            if status == "ok":
                write_json(raw_dir / f"{record_id}.format_normalize.response.json", format_normalize_response)
            else:
                write_json(
                    raw_dir / f"{record_id}.format_normalize.response_failed_parse.json",
                    format_normalize_response,
                )
        if format_normalize_content:
            target_name = "format_normalize.response.txt" if status == "ok" else "format_normalize.response_failed_parse.txt"
            (raw_dir / f"{record_id}.{target_name}").write_text(format_normalize_content, encoding="utf-8")

        records.append(record)
        write_live_progress(
            out_dir,
            total=len(items),
            records=records,
            current_index=index,
            current_item=item,
            current_record_id=record_id,
            phase="question_finished",
            started_at=current_started_at,
            extra={"status": status},
        )
        time.sleep(max(args.sleep_seconds, 0.0))

    ok_records = [item for item in records if item["status"] == "ok"]
    gate_decisions = [
        ((item.get("transcription", {}) or {}).get("quality_gate", {}) or {}).get("ingest_decision", "allow")
        for item in ok_records
    ]
    summary = {
        "model": args.model,
        "prompt_version": PIPELINE_PROMPT_VERSION,
        "runtime_contract": "general_vision_v0.1",
        "pipeline_topology": vision_pipeline.PIPELINE_TOPOLOGY,
        "question_count": len(records),
        "ok_count": len(ok_records),
        "prepared_count": sum(1 for item in records if item["status"] == "prepared"),
        "failed_count": sum(1 for item in records if item["status"] == "failed"),
        "usage_totals": vision_core.aggregate_usage(ok_records),
        "latency_summary": vision_core.aggregate_latency(records),
        "ingest_gate_counts": {
            "allow": sum(1 for item in gate_decisions if item == "allow"),
            "allow_with_review": sum(1 for item in gate_decisions if item == "allow_with_review"),
            "block": sum(1 for item in gate_decisions if item == "block"),
        },
        "records": records,
    }
    write_json(out_dir / "visual_transcription_results.json", summary)
    compact = []
    for item in records:
        compact.append(
            vision_core.summarize_record(
                item,
                status=item["status"],
                parsed=item.get("transcription"),
                error=item.get("error", ""),
            )
        )
    write_json(out_dir / "visual_transcription_compact.json", compact)
    write_live_progress(
        out_dir,
        total=len(items),
        records=records,
        current_index=len(items),
        current_item=None,
        phase="completed",
        extra={
            "ok_count": summary["ok_count"],
            "failed_count": summary["failed_count"],
            "prepared_count": summary["prepared_count"],
        },
    )
    print_json(
        {
            "out_dir": str(out_dir),
            "question_count": len(records),
            "ok_count": summary["ok_count"],
            "prepared_count": summary["prepared_count"],
            "failed_count": summary["failed_count"],
            "usage_totals": summary["usage_totals"],
            "latency_summary": summary["latency_summary"],
        }
    )


if __name__ == "__main__":
    main()
