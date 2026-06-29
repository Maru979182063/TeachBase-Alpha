from __future__ import annotations

import json
import re
from pathlib import Path

from compose_legacy_stem_md import compose_legacy_stem_md
from question_visual_structure_contract import SCHEMA_VERSION, normalize_review_flags


FIELD_NAMES = ("stem_text_md", "answer_text_md", "analysis_text_md", "handwriting_text_md")
FIELD_TO_SHORT = {
    "stem_text_md": "stem",
    "answer_text_md": "answer",
    "analysis_text_md": "analysis",
    "handwriting_text_md": "handwriting",
}
FIELD_TO_VISUAL_REF = {
    "stem": "stem_image",
    "answer": "question_image",
    "analysis": "analysis_image",
    "handwriting": "question_image",
}
INLINE_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)
ANSWER_HEADER_RE = re.compile(r"^\s*(?:\[|【)\s*答案\s*(?:\]|】)\s*[:：]?\s*", re.UNICODE)
EXPLANATION_HEADER_RE = re.compile(r"(?:\[|【)\s*(?:解答|解析|分析|证明|详解|点评|思路|结论)\s*(?:\]|】)", re.UNICODE)
SUBQUESTION_MARK_RE = re.compile(r"(?:(?<=^)|(?<=\n)|(?<=\s))(?:\(\d+\)|（\d+）)")
REASONING_CUE_RE = re.compile(
    r"(?:\\because|\\therefore|证明|由此|因为|故|所以|可得|解[:：]|解得|分析[:：]|由.+得)",
    re.UNICODE,
)
RISK_TOKEN_RULES = (
    ("operator", re.compile(r"[+\-±]")),
    ("power_or_index", re.compile(r"[_^]")),
    ("root_or_fraction", re.compile(r"\\sqrt|\\frac")),
    ("equation_system", re.compile(r"\\begin\{cases\}|\\end\{cases\}")),
    ("geometry_symbol", re.compile(r"\\angle|\\triangle|\\parallel|\\perp|\\odot|∠|△|∥|⊥|⊙|▱|□")),
    ("coordinate", re.compile(r"\([^\n]{0,40},[^\n]{0,40}\)")),
    ("line_segment_ref", re.compile(r"\bP[A-Z]\b|\b[A-Z]{2}\b")),
)
OPTION_LINE_RE = re.compile(r"^\s*(?:[（(]?([A-D])[）)]?[.、]?)\s*(.*)$")
OPTION_INLINE_RE = re.compile(r"(?:^|[\s\n])(?:[（(]?([A-D])[）)]?[.、])")


CHOICE_ANSWER_RE = re.compile(r"^\s*(?:(?:故选|故答案为|答案为|选)\s*[:：]?\s*)?\$?([A-D]{1,4})\$?\s*[。.;；]?\s*$")
VISIBLE_ANSWER_HEADER_RE = re.compile(r"^\s*【\s*答案\s*】\s*")
VISIBLE_EXPLANATION_HEADER_RE = re.compile(r"【\s*(?:解答|分析|证明|详解|点评|思路|结论)\s*】")
HANDWRITING_VISUAL_DESCRIPTION_RE = re.compile(
    r"(?:红色|蓝色|紫色|黑色|手写|标注|笔记|空白处|横线处|顶部|左侧|右侧|上方|下方|图片|颜色)",
    re.UNICODE,
)


CHOICE_ANSWER_RE = re.compile(r"^\s*(?:(?:故选|故答案为|答案为|选)\s*[:：]?\s*)?\$?([A-D]{1,4})\$?\s*[。.;；]?\s*$")
VISIBLE_ANSWER_HEADER_RE = re.compile(r"^\s*【\s*答案\s*】\s*")
VISIBLE_EXPLANATION_HEADER_RE = re.compile(r"【\s*(?:解答|分析|证明|详解|点评|思路|结论)\s*】")
TEMPLATE_NOISE_RE = re.compile(r"\b(?:tq_\d+|case_\d+|p\d+)\b|\.png\b|[\\/].+\.png\b", re.IGNORECASE)
ANSWER_WRAPPER_PATTERNS = (
    (re.compile(r"(?P<prefix>^\s*(?:[（(]\d+[）)])?\s*)点\s*(?P<label>[A-Z])\s*的坐标为\s*[:：]?\s*"), r"\g<prefix>\g<label>"),
    (re.compile(r"(?P<prefix>^\s*(?:[（(]\d+[）)])?\s*)正比例函数(?:的)?(?:解析式|表达式)为\s*[:：]?\s*"), r"\g<prefix>"),
    (re.compile(r"(?P<prefix>^\s*(?:[（(]\d+[）)])?\s*)反比例函数(?:的)?(?:解析式|表达式)为\s*[:：]?\s*"), r"\g<prefix>"),
    (re.compile(r"(?P<prefix>^\s*(?:[（(]\d+[）)])?\s*)二次函数(?:的)?(?:解析式|表达式)为\s*[:：]?\s*"), r"\g<prefix>"),
    (re.compile(r"(?P<prefix>^\s*(?:[（(]\d+[）)])?\s*)一次函数(?:的)?(?:解析式|表达式)为\s*[:：]?\s*"), r"\g<prefix>"),
    (re.compile(r"(?P<prefix>^\s*(?:[（(]\d+[）)])?\s*)故(?:答案为|选)\s*[:：]?\s*"), r"\g<prefix>"),
)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "").strip())
    slug = slug.strip("._-")
    return slug or "item"


def restore_latex_control_prefixes(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\t", "\\t").replace("\b", "\\b").replace("\f", "\\f")
    if isinstance(value, list):
        return [restore_latex_control_prefixes(item) for item in value]
    if isinstance(value, dict):
        return {key: restore_latex_control_prefixes(item) for key, item in value.items()}
    return value


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
                    return _load_json(_repair_json_string_backslashes(block))
    raise ValueError("json_object_not_closed")


def resolve_existing_path(raw_path: str, base_dirs: list[Path]) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    for base_dir in base_dirs:
        resolved = (base_dir / candidate).resolve()
        if resolved.exists():
            return resolved
    return (base_dirs[0] / candidate).resolve()


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


def _apply_safe_string_normalization(text: str, field: str) -> tuple[str, list[dict]]:
    current = str(text or "")
    log: list[dict] = []

    replacements = (
        ("strip_bom", "\ufeff", ""),
        ("normalize_crlf", "\r\n", "\n"),
        ("normalize_cr", "\r", "\n"),
        ("literal_backslash_crlf", "\\r\\n", "\n"),
        ("literal_backslash_newline", "\\n", "\n"),
        ("literal_backslash_cr", "\\r", "\n"),
        ("display_math_open_bracket", "\\[", "$$"),
        ("display_math_close_bracket", "\\]", "$$"),
        ("inline_math_open_paren", "\\(", "$"),
        ("inline_math_close_paren", "\\)", "$"),
        ("normalize_multiply_symbol", "脳", "×"),
        ("normalize_middle_dot_symbol", "·", "×"),
        ("normalize_bullet_symbol", "•", "×"),
    )
    for op, before, after in replacements:
        if before in current:
            current = current.replace(before, after)
            log.append({"field": field, "op": op})

    sized_latex = re.sub(r"\\left\s*([()\[\]{}])", r"\1", current)
    sized_latex = re.sub(r"\\right\s*([()\[\]{}])", r"\1", sized_latex)
    sized_latex = sized_latex.replace("\night)", ")").replace("\night]", "]").replace("\night}", "}")
    if sized_latex != current:
        current = sized_latex
        log.append({"field": field, "op": "strip_latex_sizing_wrappers"})

    lines = current.split("\n")
    trimmed_lines = [line.rstrip() for line in lines]
    if trimmed_lines != lines:
        current = "\n".join(trimmed_lines)
        log.append({"field": field, "op": "trim_line_trailing_space"})

    collapsed = re.sub(r"\n{3,}", "\n\n", current)
    if collapsed != current:
        current = collapsed
        log.append({"field": field, "op": "collapse_excess_blank_lines"})

    return current, log


def _normalize_compare_text_clean(text: str) -> str:
    current = normalize_text(text)
    current = ANSWER_HEADER_RE.sub("", current)
    current = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff\\]+", "", current)
    return current.lower()


def _normalize_compare_text(text: str) -> str:
    current = normalize_text(text)
    current = ANSWER_HEADER_RE.sub("", current)
    current = re.sub(r"[`$【】\[\]（）()：:；;，,。.\s]+", "", current)
    return current.lower()


def _extract_leading_answer_block(text: str) -> tuple[str, str] | None:
    current = str(text or "")
    if not (ANSWER_HEADER_RE.match(current) or VISIBLE_ANSWER_HEADER_RE.match(current)):
        return None
    body = VISIBLE_ANSWER_HEADER_RE.sub("", current, count=1)
    body = ANSWER_HEADER_RE.sub("", body, count=1).lstrip()
    if not body:
        return None

    explanation_match = EXPLANATION_HEADER_RE.search(body)
    if explanation_match and explanation_match.start() > 0:
        answer_part = body[: explanation_match.start()].strip()
        remainder = body[explanation_match.start() :].lstrip()
        if answer_part:
            return answer_part, remainder

    first_line, sep, tail = body.partition("\n")
    if sep and normalize_text(first_line):
        return first_line.strip(), tail.lstrip()
    return None


def _looks_like_reasoning_answer(text: str) -> bool:
    current = str(text or "")
    compact = normalize_text(current)
    if not compact:
        return False
    line_count = len([line for line in current.split("\n") if line.strip()])
    if VISIBLE_EXPLANATION_HEADER_RE.search(current) or EXPLANATION_HEADER_RE.search(current):
        return True
    if line_count >= 3 and REASONING_CUE_RE.search(current):
        return True
    if len(compact) >= 120 and REASONING_CUE_RE.search(current):
        return True
    return False


def _normalize_short_answer_content(text: str) -> tuple[str, list[dict]]:
    current = str(text or "")
    log: list[dict] = []
    match = CHOICE_ANSWER_RE.match(current)
    if match:
        normalized = match.group(1)
        if normalized != current:
            current = normalized
            log.append({"field": "answer_text_md", "op": "unwrap_choice_answer"})
    return current, log


def _strip_template_noise_lines(text: str, field: str) -> tuple[str, list[dict], list[dict]]:
    current = str(text or "")
    kept_lines: list[str] = []
    flags: list[dict] = []
    log: list[dict] = []
    for line in current.split("\n"):
        compact = normalize_text(line)
        if compact and TEMPLATE_NOISE_RE.search(compact):
            alpha_ratio = len(re.findall(r"[A-Za-z0-9_./\\-]", compact)) / max(len(compact), 1)
            if alpha_ratio >= 0.35:
                flags.append(
                    {
                        "field": FIELD_TO_SHORT.get(field, field),
                        "code": "template_noise_line_removed",
                        "detail": compact[:120],
                    }
                )
                log.append({"field": field, "op": "strip_template_noise_line"})
                continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip(), flags, log


def _normalize_answer_wrapper_phrases(text: str) -> tuple[str, list[dict]]:
    current = str(text or "")
    log: list[dict] = []
    if not current.strip():
        return current, log

    updated_lines: list[str] = []
    changed = False
    for line in current.split("\n"):
        new_line = line
        for pattern, replacement in ANSWER_WRAPPER_PATTERNS:
            replaced = pattern.sub(replacement, new_line, count=1)
            if replaced != new_line:
                new_line = replaced
                changed = True
        new_line = re.sub(r"\s{2,}", " ", new_line).strip()
        updated_lines.append(new_line)
    if changed:
        log.append({"field": "answer_text_md", "op": "strip_answer_wrapper_phrase"})
    return "\n".join(updated_lines).strip(), log


def _strip_non_analysis_prefix(text: str) -> tuple[str, list[dict], list[dict]]:
    current = str(text or "")
    header_match = VISIBLE_EXPLANATION_HEADER_RE.search(current) or EXPLANATION_HEADER_RE.search(current)
    if not header_match or header_match.start() <= 0:
        return current, [], []

    prefix = current[: header_match.start()].strip()
    remainder = current[header_match.start() :].lstrip()
    if not prefix or not remainder:
        return current, [], []
    if REASONING_CUE_RE.search(prefix):
        return current, [], []

    looks_like_statement_prefix = (
        any(marker in prefix for marker in ("①", "②", "③", "④", "⑤", "⑥"))
        or _count_subquestion_markers(prefix) >= 1
    )
    if not looks_like_statement_prefix:
        return current, [], []

    flags = [
        {
            "field": "analysis",
            "code": "analysis_leading_non_analysis_stripped",
            "detail": normalize_text(prefix)[:120],
        }
    ]
    log = [{"field": "analysis_text_md", "op": "strip_non_analysis_prefix"}]
    return remainder, flags, log


def _strip_embedded_duplicate_answer_headers(answer_text: str, analysis_text: str) -> tuple[str, list[dict], list[dict]]:
    compare_answer = _normalize_compare_text_clean(answer_text)
    if not compare_answer or not analysis_text.strip():
        return analysis_text, [], []

    flags: list[dict] = []
    log: list[dict] = []

    pattern = re.compile(
        r"(?P<prefix>\n+)\s*(?:\[|【)\s*答案\s*(?:\]|】)\s*[:：]?\s*(?P<answer>[^\n]+?)\s*(?=\n+\s*(?:\[|【)\s*(?:解答|解析|分析|证明|详解|点评|思路|结论)\s*(?:\]|】))",
        re.UNICODE,
    )

    def _repl(match: re.Match[str]) -> str:
        answer_part = str(match.group("answer") or "")
        if _normalize_compare_text_clean(answer_part) and _normalize_compare_text_clean(answer_part) in compare_answer:
            flags.append(
                {
                    "field": "analysis",
                    "code": "embedded_answer_duplication_removed",
                    "detail": answer_part.strip(),
                }
            )
            log.append({"field": "analysis_text_md", "op": "strip_embedded_answer_header"})
            return match.group("prefix")
        return match.group(0)

    cleaned = pattern.sub(_repl, analysis_text)
    return cleaned, flags, log


def _count_subquestion_markers(text: str) -> int:
    markers = SUBQUESTION_MARK_RE.findall(str(text or ""))
    return len(markers)


def sanitize_field_boundaries(display_fields: dict[str, str]) -> tuple[dict[str, str], list[dict], list[dict]]:
    sanitized = dict(display_fields)
    flags: list[dict] = []
    log: list[dict] = []

    answer_text = str(sanitized.get("answer_text_md", "") or "")
    analysis_text = str(sanitized.get("analysis_text_md", "") or "")
    stem_text = str(sanitized.get("stem_text_md", "") or "")

    stem_text, stem_noise_flags, stem_noise_log = _strip_template_noise_lines(stem_text, "stem_text_md")
    if stem_noise_log:
        sanitized["stem_text_md"] = stem_text
        log.extend(stem_noise_log)
    flags.extend(stem_noise_flags)

    answer_text, answer_noise_flags, answer_noise_log = _strip_template_noise_lines(answer_text, "answer_text_md")
    if answer_noise_log:
        sanitized["answer_text_md"] = answer_text
        log.extend(answer_noise_log)
    flags.extend(answer_noise_flags)

    analysis_text, analysis_noise_flags, analysis_noise_log = _strip_template_noise_lines(analysis_text, "analysis_text_md")
    if analysis_noise_log:
        sanitized["analysis_text_md"] = analysis_text
        log.extend(analysis_noise_log)
    flags.extend(analysis_noise_flags)

    stripped_answer = VISIBLE_ANSWER_HEADER_RE.sub("", answer_text, count=1)
    stripped_answer = ANSWER_HEADER_RE.sub("", stripped_answer, count=1).lstrip()
    if stripped_answer != answer_text:
        sanitized["answer_text_md"] = stripped_answer
        answer_text = stripped_answer
        log.append({"field": "answer_text_md", "op": "strip_answer_header"})

    answer_text, answer_shape_log = _normalize_short_answer_content(answer_text)
    if answer_shape_log:
        sanitized["answer_text_md"] = answer_text
        log.extend(answer_shape_log)

    answer_text, answer_wrapper_log = _normalize_answer_wrapper_phrases(answer_text)
    if answer_wrapper_log:
        sanitized["answer_text_md"] = answer_text
        log.extend(answer_wrapper_log)

    stripped_analysis, prefix_flags, prefix_log = _strip_non_analysis_prefix(analysis_text)
    if stripped_analysis != analysis_text:
        sanitized["analysis_text_md"] = stripped_analysis
        analysis_text = stripped_analysis
    flags.extend(prefix_flags)
    log.extend(prefix_log)

    leading_answer = _extract_leading_answer_block(analysis_text)
    if leading_answer:
        answer_part, remainder = leading_answer
        if answer_text and _normalize_compare_text_clean(answer_part) == _normalize_compare_text_clean(answer_text):
            sanitized["analysis_text_md"] = remainder
            analysis_text = remainder
            log.append({"field": "analysis_text_md", "op": "strip_duplicate_leading_answer_header"})
            flags.append(
                {
                    "field": "analysis",
                    "code": "leading_answer_duplication_removed",
                    "detail": answer_part,
                }
            )

    cleaned_analysis, embedded_flags, embedded_log = _strip_embedded_duplicate_answer_headers(answer_text, analysis_text)
    if cleaned_analysis != analysis_text:
        sanitized["analysis_text_md"] = cleaned_analysis
        analysis_text = cleaned_analysis
    flags.extend(embedded_flags)
    log.extend(embedded_log)

    if answer_text and _looks_like_reasoning_answer(answer_text):
        flags.append(
            {
                "field": "answer",
                "code": "answer_contains_reasoning",
                "detail": normalize_text(answer_text)[:120],
            }
        )

    stem_subquestions = _count_subquestion_markers(stem_text)
    answer_subquestions = _count_subquestion_markers(answer_text)
    if stem_subquestions >= 2 and answer_text.strip() and answer_subquestions < stem_subquestions:
        flags.append(
            {
                "field": "answer",
                "code": "answer_subquestion_count_mismatch",
                "detail": f"stem={stem_subquestions},answer={answer_subquestions}",
            }
        )

    return sanitized, flags, log


def safe_normalize_transcription_payload(
    payload: dict,
    *,
    record_id: str = "",
    question_id: str = "",
    visual_refs: dict | None = None,
    prompt_version: str = "",
    model_name: str = "",
    question_context: dict | None = None,
) -> dict:
    raw_container = payload.get("raw_text", {}) if isinstance(payload.get("raw_text"), dict) else {}
    display_container = (
        payload.get("display_normalized_text", {})
        if isinstance(payload.get("display_normalized_text"), dict)
        else {}
    )

    raw_fields: dict[str, str] = {}
    display_fields: dict[str, str] = {}
    normalization_log: list[dict] = []
    for field in FIELD_NAMES:
        raw_value = raw_container.get(field, display_container.get(field, payload.get(field, "")))
        raw_fields[field] = str(raw_value or "")
        display_value, field_log = _apply_safe_string_normalization(raw_fields[field], field)
        display_fields[field] = display_value
        normalization_log.extend(field_log)

    display_fields, boundary_flags, boundary_log = sanitize_field_boundaries(display_fields)
    normalization_log.extend(boundary_log)

    normalized_uncertain = normalize_uncertain_spans(payload.get("uncertain_spans", []) or [])
    normalized_visual_refs = build_visual_refs(visual_refs or payload.get("visual_refs") or {})
    normalized_payload = dict(payload)
    normalized_payload.update(display_fields)
    normalized_payload["record_id"] = record_id or str(payload.get("record_id", "") or "")
    normalized_payload["question_id"] = question_id or str(payload.get("question_id", "") or "")
    normalized_payload["stem_requires_image"] = bool(payload.get("stem_requires_image", False))
    normalized_payload["analysis_requires_image"] = bool(payload.get("analysis_requires_image", False))
    normalized_payload["uncertain_spans"] = normalized_uncertain
    normalized_payload["raw_text"] = raw_fields
    normalized_payload["display_normalized_text"] = display_fields
    normalized_payload["normalization_log"] = normalization_log
    normalized_payload["field_boundary_flags"] = boundary_flags
    normalized_payload["visual_refs"] = normalized_visual_refs
    normalized_payload["structure_mapping"] = build_structure_mapping(display_fields, boundary_flags)
    normalized_payload["risk_spans"] = detect_risk_spans(
        display_fields,
        normalized_uncertain,
        normalized_visual_refs,
    )
    normalized_payload["handwriting_requires_review"] = bool(payload.get("handwriting_requires_review", False))
    normalized_payload["handwriting_consistency"] = normalize_handwriting_consistency(
        payload.get("handwriting_consistency", {}) or {}
    )
    normalized_payload["quality_gate"] = build_quality_gate(
        display_fields,
        boundary_flags,
        normalized_payload["risk_spans"],
    )
    apply_handwriting_gate(normalized_payload["quality_gate"], normalized_payload)
    normalized_payload["source_of_truth"] = "rendered_image"
    normalized_payload["contract_version"] = "general_vision_v0.1"
    normalized_payload["prompt_version"] = prompt_version or str(payload.get("prompt_version", "") or "")
    normalized_payload["model_name"] = model_name or str(payload.get("model_name", "") or "")
    if question_context:
        qvs = build_question_visual_structure(question_context, normalized_payload)
        normalized_payload["question_visual_structure"] = qvs
        normalized_payload["legacy_stem_md"] = qvs.get("legacy_stem_md", "")
    return normalized_payload


def normalize_handwriting_consistency(value: object) -> dict:
    if not isinstance(value, dict):
        return {
            "status": "not_checked",
            "summary": "",
            "conflict_spans": [],
        }
    status = str(value.get("status", "") or "not_checked").strip().lower()
    if status not in {"consistent", "inconsistent", "uncertain", "not_checked"}:
        status = "uncertain"
    conflict_spans = value.get("conflict_spans", []) or []
    if not isinstance(conflict_spans, list):
        conflict_spans = []
    return {
        "status": status,
        "summary": str(value.get("summary", "") or ""),
        "conflict_spans": [item for item in conflict_spans if isinstance(item, dict)],
    }


def _extract_option_sections(stem_text: str) -> tuple[str, list[dict]]:
    lines = str(stem_text or "").splitlines()
    stem_lines: list[str] = []
    options: list[dict] = []
    current: dict | None = None
    matched_line_mode = False
    for line in lines:
        match = OPTION_LINE_RE.match(line)
        if match:
            matched_line_mode = True
            option_key = str(match.group(1) or "").upper()
            option_body = str(match.group(2) or "").rstrip()
            current = {
                "option_key": option_key,
                "option_text_md": f"{option_key}. {option_body}".rstrip(),
            }
            options.append(current)
            continue
        if current is not None:
            addition = line.rstrip()
            if addition:
                current["option_text_md"] = f"{current['option_text_md']}\n{addition}".rstrip()
            continue
        stem_lines.append(line.rstrip())

    if matched_line_mode and options:
        return "\n".join(stem_lines).strip(), options

    matches = list(OPTION_INLINE_RE.finditer(str(stem_text or "")))
    if len(matches) < 2:
        return str(stem_text or "").strip(), []

    stem_body = str(stem_text or "")[: matches[0].start()].strip()
    sections: list[dict] = []
    for idx, match in enumerate(matches):
        key = str(match.group(1) or "").upper()
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(str(stem_text or ""))
        chunk = str(stem_text or "")[start:end].strip()
        sections.append({"option_key": key, "option_text_md": chunk})
    return stem_body, sections


def build_question_visual_structure(question_context: dict, payload: dict) -> dict:
    question_uid = str(question_context.get("question_uid", "") or question_context.get("question_id", "") or payload.get("question_id", "")).strip()
    gating = question_context.get("gating_result", {}) if isinstance(question_context.get("gating_result"), dict) else {}
    staged_assets = [dict(item) for item in (question_context.get("staged_visual_assets", []) or []) if isinstance(item, dict)]
    option_blocks = [dict(item) for item in (question_context.get("option_visual_blocks", []) or []) if isinstance(item, dict)]
    stem_md_raw = str(payload.get("stem_text_md", "") or "")
    answer_md = str(payload.get("answer_text_md", "") or "")
    analysis_md = str(payload.get("analysis_text_md", "") or "")
    stem_md, parsed_options = _extract_option_sections(stem_md_raw)

    detection_by_key = {
        str(item.get("option_key", "") or "").upper(): item
        for item in option_blocks
        if str(item.get("option_key", "") or "").upper()
    }
    attached_assets_by_key: dict[str, list[dict]] = {}
    candidate_assets_by_key: dict[str, list[dict]] = {}
    review_flags: list[str] = list(question_context.get("option_detection_review_flags", []) or [])
    for asset in staged_assets:
        candidate_key = str(asset.get("candidate_option_key", "") or asset.get("option_key", "") or "").upper()
        if candidate_key:
            candidate_assets_by_key.setdefault(candidate_key, []).append(asset)
        if str(asset.get("asset_role", "") or "") == "option" and str(asset.get("attach_status", "") or "") == "attached":
            option_key = str(asset.get("option_key", "") or "").upper()
            attached_assets_by_key.setdefault(option_key, []).append(asset)
        review_flags.extend(asset.get("review_flags", []) or [])

    ordered_keys: list[str] = []
    for option in parsed_options:
        key = str(option.get("option_key", "") or "").upper()
        if key and key not in ordered_keys:
            ordered_keys.append(key)
    for block in option_blocks:
        key = str(block.get("option_key", "") or "").upper()
        if key and key not in ordered_keys:
            ordered_keys.append(key)
    for key in attached_assets_by_key:
        if key not in ordered_keys:
            ordered_keys.append(key)

    text_by_key = {str(item.get("option_key", "") or "").upper(): str(item.get("option_text_md", "") or "") for item in parsed_options}
    options: list[dict] = []
    content_blocks: list[dict] = []
    block_order = 1
    if stem_md.strip():
        content_blocks.append(
            {
                "block_id": "blk_stem_001",
                "block_order": block_order,
                "scope": "stem",
                "option_key": None,
                "block_type": "markdown",
                "text_md": stem_md.strip(),
                "asset_id": None,
                "display_ref": None,
                "confidence": 0.95,
                "review_flags": [],
            }
        )
        block_order += 1

    stem_inline_assets = [
        asset
        for asset in staged_assets
        if str(asset.get("asset_role", "") or "") == "stem"
        and str(asset.get("placement_scope", "") or "") == "after_stem"
    ]
    for asset_index, asset in enumerate(stem_inline_assets, start=1):
        content_blocks.append(
            {
                "block_id": f"blk_stem_img_{asset_index:03d}",
                "block_order": block_order,
                "scope": "stem",
                "option_key": None,
                "block_type": "image",
                "text_md": None,
                "asset_id": asset.get("asset_id"),
                "display_ref": asset.get("display_ref"),
                "storage_key": asset.get("storage_key"),
                "asset_role": asset.get("asset_role"),
                "confidence": float(asset.get("confidence", 0.8) or 0.8),
                "review_flags": list(asset.get("review_flags", []) or []),
            }
        )
        block_order += 1

    for index, option_key in enumerate(ordered_keys, start=1):
        detection = detection_by_key.get(option_key, {})
        attached_assets = attached_assets_by_key.get(option_key, [])
        candidate_assets = candidate_assets_by_key.get(option_key, [])
        option_text_md = text_by_key.get(option_key, f"{option_key}.")
        block_ids: list[str] = []
        text_block_id = f"blk_opt_{option_key}_text_001"
        content_blocks.append(
            {
                "block_id": text_block_id,
                "block_order": block_order,
                "scope": "option",
                "option_key": option_key,
                "block_type": "markdown",
                "text_md": option_text_md.strip(),
                "asset_id": None,
                "display_ref": None,
                "confidence": float(detection.get("confidence", 0.9) or 0.9),
                "review_flags": list(detection.get("review_flags", []) or []),
            }
        )
        block_ids.append(text_block_id)
        block_order += 1
        for asset_index, asset in enumerate(attached_assets, start=1):
            img_block_id = f"blk_opt_{option_key}_img_{asset_index:03d}"
            content_blocks.append(
                {
                    "block_id": img_block_id,
                    "block_order": block_order,
                    "scope": "option",
                    "option_key": option_key,
                    "block_type": "image",
                    "text_md": None,
                    "asset_id": asset.get("asset_id"),
                    "display_ref": asset.get("display_ref"),
                    "storage_key": asset.get("storage_key"),
                    "asset_role": asset.get("asset_role"),
                    "confidence": float(asset.get("confidence", detection.get("confidence", 0.8)) or 0.8),
                    "review_flags": list(asset.get("review_flags", []) or []),
                }
            )
            block_ids.append(img_block_id)
            block_order += 1
        attach_status = "attached" if attached_assets else ("no_image" if not candidate_assets else str(candidate_assets[0].get("attach_status", "not_attached_unassigned") or "not_attached_unassigned"))
        options.append(
            {
                "option_key": option_key,
                "option_order": int(detection.get("option_order", index) or index),
                "option_text_md": option_text_md.strip(),
                "block_ids": block_ids,
                "asset_ids": [str(asset.get("asset_id", "") or "") for asset in attached_assets if str(asset.get("asset_id", "") or "")],
                "requires_image": bool(candidate_assets),
                "bbox_space": str(detection.get("bbox_space", "") or ""),
                "bbox_json": detection.get("option_bbox", {}) if isinstance(detection.get("option_bbox"), dict) else {},
                "image_width": int(detection.get("image_width", 0) or 0),
                "image_height": int(detection.get("image_height", 0) or 0),
                "confidence": float(detection.get("confidence", 0.0) or 0.0),
                "attach_status": attach_status,
                "review_flags": list(detection.get("review_flags", []) or []),
            }
        )
        review_flags.extend(detection.get("review_flags", []) or [])

    if answer_md.strip():
        content_blocks.append(
            {
                "block_id": "blk_answer_001",
                "block_order": block_order,
                "scope": "answer",
                "option_key": None,
                "block_type": "markdown",
                "text_md": answer_md.strip(),
                "asset_id": None,
                "display_ref": None,
                "confidence": 1.0,
                "review_flags": [],
            }
        )
        block_order += 1
    if analysis_md.strip():
        content_blocks.append(
            {
                "block_id": "blk_analysis_001",
                "block_order": block_order,
                "scope": "analysis",
                "option_key": None,
                "block_type": "markdown",
                "text_md": analysis_md.strip(),
                "asset_id": None,
                "display_ref": None,
                "confidence": 1.0,
                "review_flags": [],
            }
        )
        block_order += 1

    analysis_inline_assets = [
        asset
        for asset in staged_assets
        if str(asset.get("asset_role", "") or "") == "analysis"
        and str(asset.get("placement_scope", "") or "") == "after_analysis"
    ]
    for asset_index, asset in enumerate(analysis_inline_assets, start=1):
        content_blocks.append(
            {
                "block_id": f"blk_analysis_img_{asset_index:03d}",
                "block_order": block_order,
                "scope": "analysis",
                "option_key": None,
                "block_type": "image",
                "text_md": None,
                "asset_id": asset.get("asset_id"),
                "display_ref": asset.get("display_ref"),
                "storage_key": asset.get("storage_key"),
                "asset_role": asset.get("asset_role"),
                "confidence": float(asset.get("confidence", 0.8) or 0.8),
                "review_flags": list(asset.get("review_flags", []) or []),
            }
        )
        block_order += 1

    legacy_stem_md, legacy_flags = compose_legacy_stem_md(stem_md, options, content_blocks, staged_assets)
    review_flags.extend(legacy_flags)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "visual_transcription_core",
        "runtime_run_id": "",
        "question_uid": question_uid,
        "stem_md": stem_md.strip(),
        "answer_md": answer_md,
        "analysis_md": analysis_md,
        "legacy_stem_md": legacy_stem_md,
        "gating": gating,
        "options": options,
        "content_blocks": content_blocks,
        "visual_assets": staged_assets,
        "review_flags": normalize_review_flags(review_flags),
    }


def apply_handwriting_gate(quality_gate: dict, payload: dict) -> None:
    handwriting_text = str(payload.get("handwriting_text_md", "") or "").strip()
    if not handwriting_text:
        return
    consistency = payload.get("handwriting_consistency", {}) or {}
    status = str(consistency.get("status", "") or "not_checked")
    uncertain_handwriting = any(
        str(span.get("field", "") or "") == "handwriting"
        for span in payload.get("uncertain_spans", []) or []
    )
    reason_detail = ""
    if status in {"inconsistent", "uncertain"}:
        reason_detail = status
    elif uncertain_handwriting:
        reason_detail = "uncertain_handwriting_span"
    elif bool(payload.get("handwriting_requires_review", False)):
        reason_detail = "handwriting_requires_review"
    if not reason_detail:
        return
    reasons = quality_gate.setdefault("review_reasons", [])
    reasons.append(
        {
            "level": "review",
            "code": "handwriting_consistency_review",
            "detail": reason_detail,
        }
    )
    if quality_gate.get("ingest_decision") == "allow":
        quality_gate["ingest_decision"] = "allow_with_review"
    quality_gate["needs_human_review"] = True


def normalize_uncertain_spans(spans: list[dict] | object) -> list[dict]:
    if not isinstance(spans, list):
        return []
    normalized: list[dict] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        field = str(span.get("field", "") or "").strip().lower()
        if field not in {"stem", "answer", "analysis", "handwriting"}:
            continue
        normalized.append(
            {
                "field": field,
                "text": str(span.get("text", "") or ""),
                "reason": str(span.get("reason", "") or "other"),
                "source": str(span.get("source", "") or "model_uncertain"),
            }
        )
    return normalized


def build_visual_refs(question_like: dict) -> dict:
    refs = {}
    for key in ("question_image", "stem_image", "analysis_image"):
        refs[key] = str(question_like.get(key, "") or "")
    return refs


def build_structure_mapping(display_fields: dict[str, str], boundary_flags: list[dict] | None = None) -> dict:
    flag_map: dict[str, list[str]] = {"stem": [], "answer": [], "analysis": []}
    for item in boundary_flags or []:
        field = str(item.get("field", "") or "")
        code = str(item.get("code", "") or "")
        if field in flag_map and code:
            flag_map[field].append(code)

    fields = []
    for field in FIELD_NAMES:
        text = str(display_fields.get(field, "") or "")
        short_field = FIELD_TO_SHORT[field]
        confidence = 1.0 if text.strip() else 0.0
        field_flags = flag_map.get(short_field, [])
        if field_flags and confidence > 0.0:
            if any(code in {"answer_contains_reasoning", "answer_subquestion_count_mismatch", "template_noise_line_removed"} for code in field_flags):
                confidence = 0.35
            else:
                confidence = 0.7
        fields.append(
            {
                "field": short_field,
                "source_key": field,
                "block_type": short_field,
                "text_present": bool(text.strip()),
                "confidence": confidence,
                "flags": field_flags,
            }
        )
    return {
        "schema_version": "general_vision_v0.1",
        "fields": fields,
    }


def detect_risk_spans(
    display_fields: dict[str, str],
    uncertain_spans: list[dict],
    visual_refs: dict[str, str],
) -> list[dict]:
    risk_spans: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    def _append(field: str, text: str, reason: str, source: str) -> None:
        cleaned_text = str(text or "").strip()
        key = (field, cleaned_text, reason, source)
        if not cleaned_text or key in seen:
            return
        seen.add(key)
        visual_ref_key = FIELD_TO_VISUAL_REF.get(field, "question_image")
        evidence_ref = visual_refs.get(visual_ref_key, "") or visual_refs.get("question_image", "")
        risk_spans.append(
            {
                "field": field,
                "text": cleaned_text,
                "reason": reason,
                "source": source,
                "visual_ref_key": visual_ref_key,
                "evidence_ref": evidence_ref,
            }
        )

    for span in uncertain_spans:
        _append(
            str(span.get("field", "") or ""),
            str(span.get("text", "") or ""),
            str(span.get("reason", "") or "other"),
            str(span.get("source", "") or "model_uncertain"),
        )

    for field_key, text in display_fields.items():
        short_field = FIELD_TO_SHORT[field_key]
        for match in INLINE_MATH_RE.finditer(str(text or "")):
            math_text = match.group(1) if match.group(1) is not None else match.group(2) or ""
            for reason, pattern in RISK_TOKEN_RULES:
                if pattern.search(math_text):
                    _append(short_field, math_text, reason, "auto_high_risk")
                    break

    return risk_spans


def build_quality_gate(
    display_fields: dict[str, str],
    boundary_flags: list[dict],
    risk_spans: list[dict],
) -> dict:
    reasons: list[dict] = []
    block_codes: set[str] = set()
    review_codes: set[str] = set()

    def _push(level: str, code: str, detail: str = "") -> None:
        reasons.append({"level": level, "code": code, "detail": detail})
        if level == "block":
            block_codes.add(code)
        elif level == "review":
            review_codes.add(code)

    for flag in boundary_flags:
        code = str(flag.get("code", "") or "")
        detail = str(flag.get("detail", "") or "")
        if code in {"answer_contains_reasoning", "answer_subquestion_count_mismatch"}:
            _push("block", code, detail)
        elif code in {"template_noise_line_removed", "analysis_leading_non_analysis_stripped"}:
            _push("review", code, detail)

    stem_text = str(display_fields.get("stem_text_md", "") or "")
    answer_text = str(display_fields.get("answer_text_md", "") or "")
    analysis_text = str(display_fields.get("analysis_text_md", "") or "")
    handwriting_text = str(display_fields.get("handwriting_text_md", "") or "")

    if TEMPLATE_NOISE_RE.search(stem_text):
        _push("block", "stem_template_noise_residual", normalize_text(stem_text)[:120])

    geometry_risks = [item for item in risk_spans if str(item.get("reason", "") or "") in {"geometry_symbol", "line_segment_ref"}]
    proof_like = bool(re.search(r"(?:证明|\\because|\\therefore|∵|∴)", analysis_text))
    if proof_like and len(geometry_risks) >= 4:
        _push("block", "geometry_proof_dense_risk", f"geometry_risk_spans={len(geometry_risks)}")

    if answer_text.strip() and not analysis_text.strip() and len(answer_text.strip()) >= 80:
        _push("review", "answer_only_long_text", answer_text[:120])

    uncertain_risks = [item for item in risk_spans if str(item.get("source", "") or "") == "model_uncertain"]
    non_handwriting_risks = [item for item in risk_spans if str(item.get("field", "") or "") != "handwriting"]
    if len(risk_spans) >= 18 and uncertain_risks:
        _push(
            "review",
            "high_risk_span_density",
            f"risk_spans={len(risk_spans)}, uncertain_spans={len(uncertain_risks)}",
        )
    elif len(non_handwriting_risks) >= 16 and uncertain_risks:
        _push(
            "review",
            "non_handwriting_high_risk_density",
            f"non_handwriting_risk_spans={len(non_handwriting_risks)}, uncertain_spans={len(uncertain_risks)}",
        )

    if handwriting_text.strip() and HANDWRITING_VISUAL_DESCRIPTION_RE.search(handwriting_text):
        _push("review", "handwriting_visual_description_residual", normalize_text(handwriting_text)[:160])

    if block_codes:
        decision = "block"
    elif review_codes:
        decision = "allow_with_review"
    else:
        decision = "allow"

    return {
        "rule_version": "general_gate_v0.1",
        "ingest_decision": decision,
        "needs_human_review": decision != "allow",
        "review_reasons": reasons,
        "blocked": decision == "block",
    }


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
                "risk_span_count": len(parsed.get("risk_spans", []) or []),
                "ingest_decision": ((parsed.get("quality_gate", {}) or {}).get("ingest_decision", "allow")),
                "needs_human_review": bool((parsed.get("quality_gate", {}) or {}).get("needs_human_review", False)),
                "latency_seconds": item.get("latency_seconds", 0.0),
                "usage_total_tokens": (item.get("usage", {}) or {}).get("total_tokens", 0),
                "usage_prompt_tokens": (item.get("usage", {}) or {}).get("prompt_tokens", 0),
                "usage_completion_tokens": (item.get("usage", {}) or {}).get("completion_tokens", 0),
            }
        )
    if error:
        summary["error"] = error
    return summary


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
