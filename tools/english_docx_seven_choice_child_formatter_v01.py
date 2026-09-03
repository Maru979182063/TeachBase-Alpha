from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from english_docx_grammar_child_formatter_v01 import (
    call_model,
    compact,
    load_prompt,
    read_config,
    read_json,
    render_template,
    sha256_text,
)
from english_docx_parent_child_projection_v02 import safe_rel, write_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "seven_choice_child_formatter_v01.yaml"
BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
CURRENT_BLANK_RE = re.compile(r"\[\[CURRENT_BLANK_(\d+)\]\]")
UNDERLINE_FILL_RE = re.compile(r"\[\[UNDERLINE_FILL_(\d+)\]\](.*?)\[\[/UNDERLINE_FILL_\1\]\]")
REQUIRED_SECTIONS = ["答案", "解析"]


def section_marker(section: str) -> str:
    return f"【{section}】"


def has_required_sections(text: str) -> bool:
    positions = [str(text or "").find(section_marker(section)) for section in REQUIRED_SECTIONS]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def source_blank_no_from_child(child: dict[str, Any]) -> str:
    match = BLANK_RE.search(str(child.get("anchor") or ""))
    if match:
        return match.group(1)
    return re.sub(r"\D+", "", str(child.get("source_item_no") or ""))


def local_blank_no_from_child(child: dict[str, Any]) -> str:
    return re.sub(r"\D+", "", str(child.get("item_no") or "")) or source_blank_no_from_child(child)


def blank_number_map_from_children(children: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in children:
        source_no = source_blank_no_from_child(child)
        local_no = local_blank_no_from_child(child)
        if source_no and local_no:
            out[source_no] = local_no
    return out


def blank_display_map_from_children(children: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "item_id": str(child.get("item_id") or ""),
            "source_blank": source_blank_no_from_child(child),
            "local_blank": local_blank_no_from_child(child),
            "answer": str(child.get("answer") or "").strip(),
        }
        for child in children
    ]


def normalize_context_blanks(
    text: str,
    current_local_no: str,
    number_map: dict[str, str],
    answer_text_by_local: dict[str, str] | None = None,
) -> str:
    value = CURRENT_BLANK_RE.sub(lambda match: f"[[BLANK_{match.group(1)}]]", str(text or "").strip())
    answer_text_by_local = answer_text_by_local or {}
    current_number = int(current_local_no) if str(current_local_no).isdigit() else None

    def repl(match: re.Match[str]) -> str:
        raw_no = match.group(1)
        local_no = number_map.get(raw_no, raw_no)
        if local_no == current_local_no:
            return f"[[CURRENT_BLANK_{local_no}]]"
        if current_number is not None and local_no.isdigit() and int(local_no) < current_number:
            answer_text = answer_text_by_local.get(local_no, "").strip()
            if answer_text:
                return f"[[UNDERLINE_FILL_{local_no}]]{answer_text}[[/UNDERLINE_FILL_{local_no}]]"
        return f"[[BLANK_{local_no}]]"

    return BLANK_RE.sub(repl, value)


def comparable_source_text(text: str) -> str:
    value = CURRENT_BLANK_RE.sub("[[BLANK]]", str(text or ""))
    value = UNDERLINE_FILL_RE.sub("[[BLANK]]", value)
    value = BLANK_RE.sub("[[BLANK]]", value)
    return re.sub(r"\s+", " ", value).strip()


def is_source_backed_context(display_context: str, source_text: str) -> bool:
    context = comparable_source_text(display_context)
    source = comparable_source_text(source_text)
    context = context.replace(" …… ", " ... ")
    if " ... " in context:
        parts = [part.strip() for part in context.split(" ... ") if part.strip()]
        cursor = 0
        for part in parts:
            position = source.find(part, cursor)
            if position < 0:
                return False
            cursor = position + len(part)
        return True
    if "……" in context:
        parts = [part.strip() for part in context.split("……") if part.strip()]
        cursor = 0
        for part in parts:
            position = source.find(part, cursor)
            if position < 0:
                return False
            cursor = position + len(part)
        return bool(parts) and all(part in source for part in parts)
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


def sentence_contains_quote(sentence: str, quote: str) -> bool:
    return contains_evidence_quote_strict(sentence, quote)


def evidence_sentence_indexes(question: str, spans: list[tuple[int, int]], raw_explanation: str) -> list[int]:
    indexes: list[int] = []
    for quote in evidence_quotes_from_raw(raw_explanation):
        for index, (start, end) in enumerate(spans):
            if sentence_contains_quote(question[start:end], quote):
                if index not in indexes:
                    indexes.append(index)
                break
    return sorted(indexes)


def build_candidate_from_sentence_indexes(
    question: str,
    spans: list[tuple[int, int]],
    indexes: list[int],
    local_no: str,
    number_map: dict[str, str],
    answer_text_by_local: dict[str, str] | None,
) -> str:
    if not indexes:
        return ""
    unique_indexes = sorted(set(indexes))
    contiguous = all(b == a + 1 for a, b in zip(unique_indexes, unique_indexes[1:]))
    if contiguous:
        raw = question[spans[unique_indexes[0]][0] : spans[unique_indexes[-1]][1]]
    else:
        raw = " ... ".join(question[spans[index][0] : spans[index][1]].strip() for index in unique_indexes)
    return normalize_context_blanks(raw, local_no, number_map, answer_text_by_local)


def source_evidence_sentences(source_text: str, raw_explanation: str) -> list[str]:
    source = str(source_text or "")
    spans = sentence_spans(source)
    source_sentences = [source[start:end].strip() for start, end in spans if source[start:end].strip()]
    out: list[str] = []
    for quote in evidence_quotes_from_raw(raw_explanation):
        quote_fragments = [
            fragment.strip()
            for fragment in re.split(r"(?<=[.!?])\s*(?=[A-Z])", quote)
            if len(evidence_words(fragment)) >= 4
        ] or [quote]
        for fragment in quote_fragments:
            for sentence in source_sentences:
                if contains_evidence_quote_strict(sentence, fragment):
                    best_sentence = re.sub(r"^\s*\[\[BLANK_\d+\]\]\s*", "", sentence).strip()
                    if best_sentence and best_sentence not in out:
                        out.append(best_sentence)
                    break
    return out


def context_candidates_for_child(
    child: dict[str, Any],
    number_map: dict[str, str],
    answer_text_by_local: dict[str, str] | None = None,
    raw_explanation: str = "",
) -> list[str]:
    question = str(child.get("question") or "").strip()
    if not question:
        return []
    local_no = local_blank_no_from_child(child)
    source_no = source_blank_no_from_child(child) or local_no
    source_marker = f"[[BLANK_{source_no}]]"
    marker_pos = question.find(source_marker)
    if marker_pos < 0:
        marker_pos = question.find(f"[[BLANK_{local_no}]]")
    if marker_pos < 0:
        return [normalize_context_blanks(question, local_no, number_map, answer_text_by_local)]
    spans = sentence_spans(question)
    current_index = 0
    for index, (start, end) in enumerate(spans):
        if start <= marker_pos < end:
            current_index = index
            break
    index_sets = [
        [current_index],
        [max(0, current_index - 1), current_index],
        [current_index, min(len(spans) - 1, current_index + 1)],
        [max(0, current_index - 1), current_index, min(len(spans) - 1, current_index + 1)],
        [max(0, current_index - 2), max(0, current_index - 1), current_index],
        [
            max(0, current_index - 2),
            max(0, current_index - 1),
            current_index,
            min(len(spans) - 1, current_index + 1),
        ],
    ]
    seen: set[str] = set()
    candidates: list[str] = []
    for indexes in index_sets:
        unique_indexes = sorted(set(indexes))
        start = spans[unique_indexes[0]][0]
        end = spans[unique_indexes[-1]][1]
        candidate = normalize_context_blanks(question[start:end], local_no, number_map, answer_text_by_local)
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    evidence_indexes = evidence_sentence_indexes(question, spans, raw_explanation)
    if evidence_indexes:
        bridge_indexes = sorted(set(evidence_indexes + [current_index]))
        if bridge_indexes[-1] - bridge_indexes[0] <= 4:
            bridge_indexes = list(range(bridge_indexes[0], bridge_indexes[-1] + 1))
        candidate = build_candidate_from_sentence_indexes(
            question,
            spans,
            bridge_indexes,
            local_no,
            number_map,
            answer_text_by_local,
        )
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates[:8]


def parse_option_map(options_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current = ""
    parts: list[str] = []
    for line in str(options_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        marker = stripped[:2]
        if len(marker) == 2 and marker[0] in "ABCDEFG" and marker[1] in ".．":
            if current:
                out[current] = " ".join(parts).strip()
            current = marker[0]
            parts = [stripped[2:].strip()]
        elif current:
            parts.append(stripped)
    if current:
        out[current] = " ".join(parts).strip()
    return out


def option_letters_from_map(option_map: dict[str, str]) -> list[str]:
    return [letter for letter in "ABCDEFG" if option_map.get(letter)]


def normalize_letters(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[\s,，、/]+", str(value or ""))
    letters: list[str] = []
    for item in raw:
        letter = str(item or "").strip().upper()[:1]
        if letter in "ABCDEFG" and letter not in letters:
            letters.append(letter)
    return letters


def options_text_from_letters(option_map: dict[str, str], letters: list[str]) -> str:
    lines: list[str] = []
    for letter in letters:
        text = option_map.get(letter, "").strip()
        if text:
            lines.append(f"{letter}. {text}")
    return "\n\n".join(lines)


def cjk_count(text: str) -> int:
    return sum(1 for char in str(text or "") if "\u4e00" <= char <= "\u9fff")


def evidence_quotes_from_raw(raw_explanation: str) -> list[str]:
    text = str(raw_explanation or "")
    quotes = re.findall(r"[“\"]([^”\"]{24,})[”\"]", text)
    out: list[str] = []
    for quote in quotes:
        normalized = re.sub(r"\s+", " ", quote).strip()
        normalized = re.sub(r"(?<=[.!?])\s*[(（][\u4e00-\u9fff].*$", "", normalized).strip()
        if len(normalized) < 24:
            continue
        ascii_letters = sum(1 for char in normalized if char.isascii() and char.isalpha())
        if ascii_letters < 12:
            continue
        if normalized not in out:
            out.append(normalized)
    return out


def contains_evidence_quote(text: str, quotes: list[str]) -> bool:
    normalized_text = re.sub(r"\s+", " ", str(text or ""))
    for quote in quotes:
        if quote in normalized_text:
            return True
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]+", quote) if len(word) > 2]
        if len(words) >= 6:
            hits = sum(1 for word in words if word in normalized_text)
            if hits >= max(6, int(len(words) * 0.7)):
                return True
    return not quotes


def translation_glosses_from_raw(raw_explanation: str) -> list[str]:
    text = str(raw_explanation or "")
    out: list[str] = []
    for match in re.finditer(r"[(（]([^()（）]{4,160}[\u4e00-\u9fff][^()（）]{0,160})[)）]", text):
        value = re.sub(r"\s+", "", match.group(1)).strip()
        cjk = "".join(char for char in value if "\u4e00" <= char <= "\u9fff")
        if len(cjk) < 6:
            continue
        if value not in out:
            out.append(value)
    return out[:4]


def contains_translation_glosses(text: str, glosses: list[str]) -> bool:
    normalized_cjk = "".join(char for char in str(text or "") if "\u4e00" <= char <= "\u9fff")
    for gloss in glosses:
        cjk = "".join(char for char in gloss if "\u4e00" <= char <= "\u9fff")
        if not cjk:
            continue
        window = cjk[: min(18, len(cjk))]
        if len(window) >= 6 and window not in normalized_cjk:
            return False
    return True


def evidence_words(value: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z'-]+", str(value or "")) if len(word) > 2]


def contains_evidence_quote_strict(text: str, quote: str) -> bool:
    normalized_text = comparable_source_text(text).lower()
    normalized_quote = comparable_source_text(quote).lower()
    if normalized_quote and normalized_quote in normalized_text:
        return True
    words = evidence_words(quote)
    if len(words) < 6:
        return contains_evidence_quote(text, [quote])
    prefix = words[: min(8, len(words))]
    cursor = 0
    misses = 0
    for word in prefix:
        position = normalized_text.find(word, cursor)
        if position < 0:
            misses += 1
            if misses > 1:
                return False
            continue
        cursor = position + len(word)
    hits = sum(1 for word in words if word in normalized_text)
    return hits >= max(6, int(len(words) * 0.65))


def has_answer_conclusion(text: str, answer: str) -> bool:
    if not answer:
        return True
    value = re.sub(r"\s+", "", str(text or ""))
    patterns = [
        f"故选{answer}",
        f"因此选{answer}",
        f"所以选{answer}",
        f"答案为{answer}",
        f"选{answer}",
    ]
    return any(pattern in value for pattern in patterns)


def candidate_contains_required_evidence(display_context: str, candidates: list[str], quotes: list[str]) -> bool:
    relevant_quotes = [quote for quote in quotes if any(contains_evidence_quote_strict(candidate, quote) for candidate in candidates)]
    if not relevant_quotes:
        return True
    return all(contains_evidence_quote_strict(display_context, quote) for quote in relevant_quotes)


def answer_text_map_from_children(children: list[dict[str, Any]], option_map: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in children:
        local_no = local_blank_no_from_child(child)
        answer = str(child.get("answer") or "").strip()
        answer_text = option_map.get(answer, "").strip()
        if local_no and answer_text:
            out[local_no] = answer_text
    return out


def paragraph_context_for_child(
    parent_passage: str,
    child: dict[str, Any],
    number_map: dict[str, str],
    answer_text_by_local: dict[str, str],
) -> str:
    passage = str(parent_passage or "")
    if not passage.strip():
        return ""
    source_no = source_blank_no_from_child(child)
    marker = f"[[BLANK_{source_no}]]"
    local_no = local_blank_no_from_child(child)
    marker_pos = passage.find(marker)
    if marker_pos < 0:
        marker_pos = passage.find(f"[[BLANK_{local_no}]]")
    if marker_pos < 0:
        return ""
    start = passage.rfind("\n\n", 0, marker_pos)
    start = 0 if start < 0 else start + 2
    end = passage.find("\n\n", marker_pos)
    end = len(passage) if end < 0 else end
    return normalize_context_blanks(passage[start:end], local_no, number_map, answer_text_by_local)


def child_for_model(
    child: dict[str, Any],
    max_chars: int,
    number_map: dict[str, str],
    answer_text_by_local: dict[str, str],
    parent_passage: str = "",
) -> dict[str, Any]:
    question = str(child.get("question") or "")
    source_evidence_quotes = source_evidence_sentences(parent_passage or question, str(child.get("explanation") or ""))
    return {
        "item_id": child.get("item_id"),
        "item_no": child.get("item_no"),
        "source_item_no": child.get("source_item_no"),
        "item_kind": child.get("item_kind"),
        "anchor": child.get("anchor"),
        "question": compact(question, max_chars),
        "source_paragraph_context": compact(
            paragraph_context_for_child(parent_passage, child, number_map, answer_text_by_local),
            max_chars,
        ),
        "source_evidence_quotes": source_evidence_quotes,
        "context_hints": context_candidates_for_child(
            child,
            number_map,
            answer_text_by_local,
            str(child.get("explanation") or ""),
        ),
        "answer": compact(str(child.get("answer") or ""), 20),
        "raw_explanation": compact(str(child.get("explanation") or ""), max_chars),
    }


def render_user_prompt(config: dict[str, Any], template: str, *, doc_id: str, group: dict[str, Any], children: list[dict[str, Any]]) -> str:
    max_passage_chars = int(config.get("max_passage_chars") or 9000)
    max_child_chars = int(config.get("max_child_text_chars") or 2200)
    parent = group.get("parent") or {}
    number_map = blank_number_map_from_children(children)
    option_map = parse_option_map(str(parent.get("options") or ""))
    answer_text_by_local = answer_text_map_from_children(children, option_map)
    parent_for_model = {
        "kind": group.get("parent_kind"),
        "source_label": compact(str(parent.get("source_label") or ""), 1200),
        "passage": compact(str(parent.get("passage") or ""), max_passage_chars),
        "options": str(parent.get("options") or ""),
    }
    return render_template(
        template,
        {
            "doc_id": doc_id,
            "group_id": str(group.get("group_id") or ""),
            "prompt_version": str(config.get("prompt_version") or ""),
            "parent_json": json.dumps(parent_for_model, ensure_ascii=False, indent=2),
            "blank_display_map_json": json.dumps(blank_display_map_from_children(children), ensure_ascii=False, indent=2),
            "children_json": json.dumps(
                [
                    child_for_model(
                        child,
                        max_child_chars,
                        number_map,
                        answer_text_by_local,
                        str(parent.get("passage") or ""),
                    )
                    for child in children
                ],
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
    prefer_full_paragraph_max_chars: int = 1100,
) -> tuple[bool, list[str], dict[str, Any]]:
    if not isinstance(parsed, dict):
        return False, ["model_output_not_json_object"], {}
    issues: list[str] = []
    cleaned = dict(parsed)
    if cleaned.get("schema") != "english_docx_seven_choice_child_formatter_v0.1":
        issues.append("schema_mismatch")
    if str(cleaned.get("doc_id") or "") != doc_id:
        issues.append("doc_id_mismatch")
    if str(cleaned.get("group_id") or "") != str(group.get("group_id") or ""):
        issues.append("group_id_mismatch")
    parent_options = str((group.get("parent") or {}).get("options") or "").strip()
    parent_passage = str((group.get("parent") or {}).get("passage") or "").strip()
    option_map = parse_option_map(parent_options)
    supplied = {str(child.get("item_id") or ""): child for child in children}
    number_map = blank_number_map_from_children(children)
    answer_text_by_local = answer_text_map_from_children(children, option_map)
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
        display_context = str(item.get("display_context") or "").strip()
        source_text_for_context = parent_passage or str(source_child.get("question") or "")
        if not is_source_backed_context(display_context, source_text_for_context):
            issues.append(f"display_context_not_source_backed:{item_id}")
        local_no = local_blank_no_from_child(source_child)
        if f"[[CURRENT_BLANK_{local_no}]]" not in display_context:
            issues.append(f"missing_current_blank:{item_id}")
        paragraph_context = paragraph_context_for_child(parent_passage, source_child, number_map, answer_text_by_local)
        options = str(item.get("options") or "").strip()
        available_letters = option_letters_from_map(option_map)
        selected_letters = normalize_letters(item.get("selected_option_letters"))
        excluded_letters = normalize_letters(item.get("excluded_option_letters"))
        expected_set = set(available_letters)
        if len(available_letters) >= 7:
            if len(selected_letters) != 4:
                issues.append(f"selected_option_count_mismatch:{item_id}:{selected_letters}")
            if len(excluded_letters) != 3:
                issues.append(f"excluded_option_count_mismatch:{item_id}:{excluded_letters}")
            if answer not in selected_letters:
                issues.append(f"answer_not_in_selected_options:{item_id}:{answer}:{selected_letters}")
            if answer in excluded_letters:
                issues.append(f"answer_in_excluded_options:{item_id}:{answer}:{excluded_letters}")
            if set(selected_letters) | set(excluded_letters) != expected_set:
                issues.append(f"option_partition_mismatch:{item_id}:{selected_letters}:{excluded_letters}")
            if set(selected_letters) & set(excluded_letters):
                issues.append(f"option_partition_overlap:{item_id}:{selected_letters}:{excluded_letters}")
            selected_letters = [letter for letter in available_letters if letter not in set(excluded_letters)]
            excluded_letters = [letter for letter in available_letters if letter in set(excluded_letters)]
        else:
            selected_letters = available_letters
            excluded_letters = []
        normalized_options = options_text_from_letters(option_map, selected_letters)
        if not normalized_options:
            issues.append(f"empty_selected_options:{item_id}")
        answer_option_text = str(item.get("answer_option_text") or "").strip()
        if expected_answer in option_map and option_map[expected_answer] and option_map[expected_answer] not in answer_option_text:
            issues.append(f"answer_option_text_mismatch:{item_id}")
        analysis = str(item.get("analysis") or "").strip()
        if not analysis:
            issues.append(f"missing_analysis:{item_id}")
        if cjk_count(analysis) < 12:
            issues.append(f"analysis_not_chinese:{item_id}")
        formatted = str(item.get("formatted_explanation") or "").strip()
        if not has_required_sections(formatted):
            issues.append(f"missing_or_disordered_required_sections:{item_id}")
        if cjk_count(formatted) < 16:
            issues.append(f"formatted_explanation_not_chinese:{item_id}")
        if expected_answer and not has_answer_conclusion(analysis + "\n" + formatted, expected_answer):
            issues.append(f"analysis_missing_conclusion:{item_id}")
        raw_quotes = evidence_quotes_from_raw(str(source_child.get("explanation") or ""))
        source_quotes = source_evidence_sentences(source_text_for_context, str(source_child.get("explanation") or ""))
        if source_quotes and not all(contains_evidence_quote_strict(display_context, quote) for quote in source_quotes):
            issues.append(f"display_context_evidence_quote_missing:{item_id}")
        if (
            paragraph_context
            and len(paragraph_context) <= prefer_full_paragraph_max_chars
            and f"[[CURRENT_BLANK_{local_no}]]" in paragraph_context
            and all(contains_evidence_quote_strict(paragraph_context, quote) for quote in source_quotes)
            and comparable_source_text(display_context) != comparable_source_text(paragraph_context)
        ):
            issues.append(f"display_context_should_use_full_paragraph:{item_id}")
        if raw_quotes and not contains_evidence_quote(analysis + "\n" + formatted, raw_quotes):
            issues.append(f"evidence_quote_missing:{item_id}")
        raw_translation_glosses = translation_glosses_from_raw(str(source_child.get("explanation") or ""))
        if raw_translation_glosses and not contains_translation_glosses(formatted, raw_translation_glosses):
            issues.append(f"translation_gloss_missing:{item_id}")
        normalized_items.append(
            {
                "item_id": item_id,
                "item_no": str(item.get("item_no") or ""),
                "source_item_no": str(item.get("source_item_no") or ""),
                "display_context": display_context,
                "selected_option_letters": selected_letters,
                "excluded_option_letters": excluded_letters,
                "options": normalized_options,
                "answer": answer,
                "answer_option_text": answer_option_text,
                "analysis": analysis,
                "formatted_explanation": formatted,
                "confidence": str(item.get("confidence") or "low"),
                "source": "model",
                "warnings": [],
            }
        )
    for item_id in sorted(set(supplied) - seen):
        issues.append(f"missing_item_id:{item_id}")
    cleaned["items"] = normalized_items
    if not isinstance(cleaned.get("warnings"), list):
        cleaned["warnings"] = []
    return not issues, issues, cleaned


def retry_issue_details(group: dict[str, Any], children: list[dict[str, Any]], issues: list[str]) -> list[dict[str, Any]]:
    parent_passage = str((group.get("parent") or {}).get("passage") or "")
    option_map = parse_option_map(str((group.get("parent") or {}).get("options") or ""))
    number_map = blank_number_map_from_children(children)
    answer_text_by_local = answer_text_map_from_children(children, option_map)
    by_id = {str(child.get("item_id") or ""): child for child in children}
    details: list[dict[str, Any]] = []
    for issue in issues:
        parts = str(issue).split(":")
        if len(parts) < 2:
            continue
        item_id = parts[1]
        child = by_id.get(item_id)
        if not child:
            continue
        details.append(
            {
                "issue": issue,
                "item_id": item_id,
                "item_no": child.get("item_no"),
                "current_blank": f"[[CURRENT_BLANK_{local_blank_no_from_child(child)}]]",
                "preferred_source_paragraph_context": paragraph_context_for_child(
                    parent_passage,
                    child,
                    number_map,
                    answer_text_by_local,
                ),
                "required_display_context_evidence": source_evidence_sentences(
                    parent_passage or str(child.get("question") or ""),
                    str(child.get("explanation") or ""),
                ),
                "required_translation_glosses_from_raw_explanation": translation_glosses_from_raw(
                    str(child.get("explanation") or "")
                ),
            }
        )
    return details


def append_retry_feedback(
    base_prompt: str,
    issues: list[str],
    attempt: int,
    details: list[dict[str, Any]] | None = None,
) -> str:
    return (
        base_prompt
        + "\n\nValidation feedback for retry "
        + str(attempt)
        + ":\n"
        + json.dumps(issues[:80], ensure_ascii=False, indent=2)
        + ("\n\nIssue details:\n" + json.dumps(details, ensure_ascii=False, indent=2) if details else "")
        + "\n\nRegenerate the whole JSON. Select display_context from the parent passage. Use ` ... ` only between source-backed fragments when needed."
    )


def review_only_from_raw(
    child: dict[str, Any],
    group: dict[str, Any],
    issues: list[str],
    number_map: dict[str, str],
    answer_text_by_local: dict[str, str],
) -> dict[str, Any]:
    candidates = context_candidates_for_child(
        child,
        number_map,
        answer_text_by_local,
        str(child.get("explanation") or ""),
    )
    option_map = parse_option_map(str((group.get("parent") or {}).get("options") or ""))
    available_letters = option_letters_from_map(option_map)
    answer = str(child.get("answer") or "").strip()
    selected_letters = [letter for letter in available_letters if letter == answer] + [
        letter for letter in available_letters if letter != answer
    ][:3]
    selected_letters = selected_letters[:4]
    excluded_letters = [letter for letter in available_letters if letter not in selected_letters]
    return {
        "item_id": str(child.get("item_id") or ""),
        "item_no": str(child.get("item_no") or ""),
        "source_item_no": str(child.get("source_item_no") or ""),
        "display_context": next(
            (
                candidate
                for candidate in candidates
                if candidate_contains_required_evidence(
                    candidate,
                    candidates,
                    evidence_quotes_from_raw(str(child.get("explanation") or "")),
                )
            ),
            candidates[0] if candidates else str(child.get("question") or ""),
        ),
        "selected_option_letters": selected_letters,
        "excluded_option_letters": excluded_letters,
        "options": options_text_from_letters(option_map, selected_letters),
        "answer": answer,
        "answer_option_text": "",
        "analysis": "",
        "formatted_explanation": "",
        "confidence": "low",
        "source": "review_only_raw_explanation",
        "warnings": issues[:12],
    }


def local_numbered_parent(parent: dict[str, Any], children: list[dict[str, Any]]) -> dict[str, Any]:
    local_parent = dict(parent)
    blanks = [
        child
        for child in children
        if isinstance(child, dict) and str(child.get("item_kind") or "") == "seven_choice_blank"
    ]
    number_map = blank_number_map_from_children(blanks)
    passage = str(local_parent.get("passage") or "")
    local_parent["passage_source"] = passage
    local_parent["passage_local_numbered"] = normalize_context_blanks(passage, "", number_map, {})
    local_parent["blank_number_map"] = number_map
    answer_lines: list[str] = []
    explanation_lines: list[str] = []
    for child in blanks:
        local_no = local_blank_no_from_child(child)
        answer = str(child.get("answer") or "").strip()
        if local_no or answer:
            answer_lines.append(f"{local_no}. {answer}".strip())
        explanation = str(child.get("explanation") or "").strip()
        if explanation:
            explanation_lines.append(
                f"{local_no}. {normalize_context_blanks(explanation, '', number_map, {})}".strip()
            )
    local_parent["answer_key_local"] = "\n".join(answer_lines)
    local_parent["raw_explanations_local_numbered"] = "\n\n".join(explanation_lines)
    return local_parent


def merge_items(group: dict[str, Any], enhanced_items: list[dict[str, Any]], status: str) -> dict[str, Any]:
    by_id = {item["item_id"]: item for item in enhanced_items}
    merged = dict(group)
    source_children = [child for child in group.get("children") or [] if isinstance(child, dict)]
    merged["parent"] = local_numbered_parent(group.get("parent") or {}, source_children)
    children = []
    for child in source_children:
        updated = dict(child)
        item = by_id.get(str(child.get("item_id") or ""))
        if item:
            raw_explanation_source = str(updated.get("explanation") or "")
            number_map = (merged.get("parent") or {}).get("blank_number_map") or {}
            updated["raw_explanation_source"] = raw_explanation_source
            updated["raw_explanation_local_numbered"] = normalize_context_blanks(
                raw_explanation_source,
                "",
                number_map,
                {},
            )
            updated["raw_explanation"] = updated["raw_explanation_local_numbered"]
            for key in [
                "display_context",
                "selected_option_letters",
                "excluded_option_letters",
                "options",
                "answer_option_text",
                "analysis",
                "formatted_explanation",
            ]:
                updated[key] = item.get(key) or ""
            updated["seven_choice_formatting"] = {
                "status": status if not item.get("warnings") else "needs_review",
                "source": item.get("source"),
                "confidence": item.get("confidence"),
                "warnings": item.get("warnings") or [],
            }
        children.append(updated)
    merged["children"] = children
    return merged


def render_text(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = re.sub(
        r"\[\[BLANK_UNLABELED_\d+\]\]&lt;u&gt;(.*?)&lt;/u&gt;\[\[BLANK_UNLABELED_\d+\]\]",
        lambda match: f'<span class="filled-blank">{match.group(1)}</span>',
        escaped,
    )
    escaped = re.sub(
        r"&lt;u&gt;(.*?)&lt;/u&gt;",
        lambda match: f'<span class="filled-blank">{match.group(1)}</span>',
        escaped,
    )
    escaped = re.sub(
        r"\[\[BLANK_UNLABELED_\d+\]\]",
        '<span class="blank"></span>',
        escaped,
    )
    escaped = re.sub(
        r"\[\[UNDERLINE_FILL_(\d+)\]\](.*?)\[\[/UNDERLINE_FILL_\1\]\]",
        lambda match: f'<span class="filled-blank" title="BLANK_{match.group(1)}">{match.group(2)}</span>',
        escaped,
    )
    escaped = re.sub(
        r"\[\[CURRENT_BLANK_(\d+)\]\]",
        lambda match: f'<span class="current-blank" title="CURRENT_BLANK_{match.group(1)}">{match.group(1)}</span>',
        escaped,
    )
    escaped = re.sub(
        r"\[\[BLANK_(\d+)\]\]",
        lambda match: f'<span class="blank" title="BLANK_{match.group(1)}">{match.group(1)}</span>',
        escaped,
    )
    return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"


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
    if str(group.get("parent_kind") or "") != "seven_choices_five":
        return {"group_id": group_id, "status": "skipped_non_seven_choices_five", "group": group, "issues": [], "usage": {}}
    children = [child for child in group.get("children") or [] if isinstance(child, dict) and str(child.get("item_kind") or "") == "seven_choice_blank"]
    number_map = blank_number_map_from_children(children)
    option_map = parse_option_map(str((group.get("parent") or {}).get("options") or ""))
    answer_text_by_local = answer_text_map_from_children(children, option_map)
    if no_model:
        enhanced = [review_only_from_raw(child, group, ["no_model"], number_map, answer_text_by_local) for child in children]
        return {"group_id": group_id, "status": "needs_review", "group": merge_items(group, enhanced, "needs_review"), "issues": ["no_model"], "usage": {}}
    base_prompt = render_user_prompt(config, user_template, doc_id=doc_id, group=group, children=children)
    prompt = base_prompt
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": base_prompt})
    timeout = int((config.get("runner") or {}).get("per_group_timeout_seconds") or 240)
    max_attempts = int((config.get("runner") or {}).get("max_group_attempts") or 3)
    last_issues: list[str] = []
    last_usage: dict[str, Any] = {}
    last_cleaned: dict[str, Any] = {}
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
                prefer_full_paragraph_max_chars=int(config.get("prefer_full_paragraph_max_chars") or 1100),
            )
            if cleaned.get("items"):
                last_cleaned = cleaned
            if ok:
                return {
                    "group_id": group_id,
                    "status": "ok",
                    "group": merge_items(group, cleaned.get("items") or [], "ok"),
                    "issues": [],
                    "warnings": cleaned.get("warnings") or [],
                    "usage": last_usage,
                    "elapsed_seconds": result.get("elapsed_seconds"),
                    "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
                }
            last_issues = issues
            write_json(raw_dir / f"attempt{attempt}.issues.json", issues)
            prompt = append_retry_feedback(base_prompt, issues, attempt + 1, retry_issue_details(group, children, issues))
        except Exception as exc:  # noqa: BLE001
            last_issues = [repr(exc)]
            write_json(raw_dir / f"attempt{attempt}.exception.json", {"error": repr(exc)})
            prompt = append_retry_feedback(base_prompt, last_issues, attempt + 1, retry_issue_details(group, children, last_issues))
    if last_cleaned.get("items"):
        flagged_items = []
        for item in last_cleaned.get("items") or []:
            flagged = dict(item)
            flagged["warnings"] = last_issues[:12]
            flagged_items.append(flagged)
        return {
            "group_id": group_id,
            "status": "needs_review",
            "group": merge_items(group, flagged_items, "needs_review"),
            "issues": last_issues or ["model_failed"],
            "usage": last_usage,
        }
    enhanced = [review_only_from_raw(child, group, last_issues or ["model_failed"], number_map, answer_text_by_local) for child in children]
    return {"group_id": group_id, "status": "needs_review", "group": merge_items(group, enhanced, "needs_review"), "issues": last_issues or ["model_failed"], "usage": last_usage}


def render_field(title: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {html.escape(class_name)}"><h4>{html.escape(title)}</h4>{render_text(text)}</section>'


def normalized_parent_passage_for_review(group: dict[str, Any]) -> str:
    parent = group.get("parent") or {}
    if str(parent.get("passage_local_numbered") or "").strip():
        return str(parent.get("passage_local_numbered") or "")
    children = [
        child
        for child in group.get("children") or []
        if isinstance(child, dict) and str(child.get("item_kind") or "") == "seven_choice_blank"
    ]
    return normalize_context_blanks(
        str(parent.get("passage") or ""),
        "",
        blank_number_map_from_children(children),
        {},
    )


def render_review_html(out_dir: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    groups_html: list[str] = []
    for group in records:
        parent = group.get("parent") or {}
        parent_passage = normalized_parent_passage_for_review(group)
        children_html: list[str] = []
        for child in group.get("children") or []:
            status = (child.get("seven_choice_formatting") or {}).get("status") or ""
            warnings = (child.get("seven_choice_formatting") or {}).get("warnings") or []
            warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings)
            raw_explanation = child.get("raw_explanation") or child.get("explanation") or ""
            children_html.append(
                '<article class="child">'
                f'<h3>第 {html.escape(str(child.get("item_no") or ""))} 空 <small>{html.escape(status)}</small></h3>'
                f'{render_field("题目原文", child.get("display_context") or child.get("question") or "", "context")}'
                f'{render_field("四选项", child.get("options") or (parent.get("options") or ""), "options")}'
                f'{render_field("格式化解析", child.get("formatted_explanation") or child.get("explanation") or "", "formatted")}'
                + (f'<ul class="warnings">{warning_html}</ul>' if warning_html else "")
                + "</article>"
            )
        groups_html.append(
            '<section class="group">'
            f'<h2>{html.escape(str(group.get("group_id") or ""))}</h2>'
            f'{render_field("父级文章（组内编号）", parent_passage, "passage")}'
            f'{render_field("原始完整选项（A-G）", parent.get("options") or "", "source-options")}'
            f'{render_field("父级答案（组内编号）", parent.get("answer_key_local") or "", "answer-key")}'
            f'{render_field("父级原始解析（组内编号）", parent.get("raw_explanations_local_numbered") or "", "parent-raw-explanations")}'
            + "".join(children_html)
            + "</section>"
        )
    html_text = f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Seven Choice Child Formatter Review</title>
<style>
body{{margin:0;background:#f6f7fb;color:#111827;font-family:Arial,'Microsoft YaHei',sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:24px}}
.group,.child{{background:#fff;border:1px solid #d8dee9;border-radius:8px;margin:0 0 18px;padding:16px}}
h1{{font-size:28px;margin:0 0 12px}}h2{{font-size:22px;margin:0 0 12px;color:#1d4ed8}}h3{{font-size:20px;margin:0 0 12px;color:#1d4ed8}}h4{{font-size:17px;margin:0 0 8px;color:#00796b}}
.field{{border-top:1px solid #e5e7eb;padding-top:10px;margin-top:10px}}.formatted{{background:#fff7ed;border-left:3px solid #f97316;padding:8px 10px}}.raw-explanation{{background:#f8fafc;border-left:3px solid #94a3b8;padding:8px 10px}}.source-options{{background:#f8fafc;padding:8px 10px}}.warnings{{color:#b45309}}
.current-blank{{display:inline-block;width:5.2em;height:1.05em;margin:0 .18em;border-bottom:2px solid #111827;vertical-align:-.08em;background:#fff7cc;text-align:center;line-height:1;color:#111827}}
.blank{{display:inline-block;width:5.2em;height:1.05em;margin:0 .18em;border-bottom:1.5px solid #111827;vertical-align:-.08em;text-align:center;line-height:1;color:#111827}}
.filled-blank{{display:inline;border-bottom:1.5px solid #111827;padding:0 .12em;margin:0 .12em;color:#111827;text-decoration:none}}
p{{font-family:Georgia,'Times New Roman','SimSun',serif;font-size:20px;line-height:1.75;margin:0 0 8px;white-space:normal}}
small{{font-size:14px;color:#64748b}}
</style></head><body><main>
<h1>Seven Choice Child Formatter Review</h1>
{''.join(groups_html)}
</main></body></html>"""
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")


def run_group_batch(worker_args: list[dict[str, Any]], max_workers: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if max_workers <= 1:
        for item in worker_args:
            results.append(process_group(**item))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_group, **item) for item in worker_args]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: str(item.get("group_id") or ""))
    return results


def result_is_ok(result: dict[str, Any] | None) -> bool:
    return bool(result) and str(result.get("status") or "") == "ok" and not (result.get("issues") or [])


def result_issue_count(result: dict[str, Any] | None) -> int:
    if not result:
        return 10_000
    return len(result.get("issues") or [])


def should_replace_result(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    if not new:
        return False
    if result_is_ok(new) and not result_is_ok(old):
        return True
    return (not result_is_ok(old)) and result_issue_count(new) < result_issue_count(old)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-projection", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--out-root", type=Path, default=None)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--fallback-rounds", type=int, default=-1)
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    started = time.time()
    config = read_config(args.config)
    parent_child = read_json(args.input_projection)
    doc_id = args.doc_id or str(parent_child.get("doc_id") or args.input_projection.parent.name)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not args.no_model and not api_key:
        raise SystemExit(f"missing api key env: {config.get('api_key_env')}")
    groups = [group for group in parent_child.get("records") or [] if str(group.get("parent_kind") or "") == "seven_choices_five"]
    if args.group_ids.strip():
        wanted = {item.strip() for item in args.group_ids.split(",") if item.strip()}
        groups = [group for group in groups if str(group.get("group_id") or "") in wanted]
    if args.max_groups:
        groups = groups[: args.max_groups]
    output_root = args.out_root or Path(str(config.get("owned_output_root") or "outputs/english_docx_seven_choice_child_formatter_v0_1"))
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    out_dir = output_root / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_args = [
        {
            "config": config,
            "group": group,
            "doc_id": doc_id,
            "system_prompt": system_prompt,
            "user_template": user_template,
            "api_key": api_key,
            "out_dir": out_dir,
            "no_model": args.no_model,
        }
        for group in groups
    ]
    max_workers = args.max_workers or int((config.get("runner") or {}).get("max_workers") or 1)
    max_workers = 1 if args.no_model else max_workers
    results = run_group_batch(worker_args, max_workers)
    group_by_id = {str(group.get("group_id") or ""): group for group in groups}
    results_by_id = {str(result.get("group_id") or ""): result for result in results}
    fallback_rounds = 0 if args.no_model else (
        args.fallback_rounds
        if args.fallback_rounds >= 0
        else int((config.get("runner") or {}).get("fallback_rounds") or 0)
    )
    fallback_trace: list[dict[str, Any]] = []
    for fallback_round in range(1, fallback_rounds + 1):
        failed_ids = [
            group_id
            for group_id, result in results_by_id.items()
            if not result_is_ok(result)
        ]
        if not failed_ids:
            break
        fallback_dir = out_dir / f"fallback_round_{fallback_round}"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_args = [
            {
                "config": config,
                "group": group_by_id[group_id],
                "doc_id": doc_id,
                "system_prompt": system_prompt,
                "user_template": user_template,
                "api_key": api_key,
                "out_dir": fallback_dir,
                "no_model": args.no_model,
            }
            for group_id in failed_ids
            if group_id in group_by_id
        ]
        fallback_results = run_group_batch(fallback_args, min(max_workers, max(1, len(fallback_args))))
        for new_result in fallback_results:
            group_id = str(new_result.get("group_id") or "")
            old_result = results_by_id.get(group_id)
            replaced = should_replace_result(old_result, new_result)
            fallback_trace.append(
                {
                    "round": fallback_round,
                    "group_id": group_id,
                    "old_status": old_result.get("status") if old_result else None,
                    "old_issues": old_result.get("issues") if old_result else [],
                    "new_status": new_result.get("status"),
                    "new_issues": new_result.get("issues") or [],
                    "replaced": replaced,
                    "trace_dir": safe_rel(fallback_dir),
                }
            )
            if replaced:
                new_result["fallback_round"] = fallback_round
                results_by_id[group_id] = new_result
    if fallback_trace:
        write_json(out_dir / "fallback_trace.json", {"items": fallback_trace})
    results = [results_by_id[str(group.get("group_id") or "")] for group in groups if str(group.get("group_id") or "") in results_by_id]
    records = [result.get("group") for result in results if result.get("group")]
    payload = {
        "schema_version": "english_docx_seven_choice_child_formatter_results.v0.1",
        "doc_id": doc_id,
        "run_id": args.run_id,
        "source_parent_child_projection": safe_rel(args.input_projection),
        "records": records,
        "results": [{key: value for key, value in result.items() if key != "group"} for result in results],
    }
    write_json(out_dir / "seven_choice_child_formatted.json", payload)
    summary = {
        "schema_version": "english_docx_seven_choice_child_formatter_summary.v0.1",
        "pipeline_id": str(config.get("pipeline_id") or ""),
        "run_id": args.run_id,
        "doc_id": doc_id,
        "group_count": len(results),
        "child_count": sum(len((result.get("group") or {}).get("children") or []) for result in results),
        "status_counts": dict(Counter(result.get("status") for result in results)),
        "issue_count": sum(len(result.get("issues") or []) for result in results),
        "usage": {
            "completion_tokens": sum(int((result.get("usage") or {}).get("completion_tokens") or 0) for result in results),
            "prompt_tokens": sum(int((result.get("usage") or {}).get("prompt_tokens") or 0) for result in results),
            "total_tokens": sum(int((result.get("usage") or {}).get("total_tokens") or 0) for result in results),
        },
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": str(config.get("prompt_version") or ""),
        "fallback_rounds_configured": fallback_rounds,
        "fallback_actions": fallback_trace,
        "artifacts": {
            "formatted": safe_rel(out_dir / "seven_choice_child_formatted.json"),
            "review_html": safe_rel(out_dir / "index.html"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
    }
    write_json(out_dir / "summary.json", summary)
    render_review_html(out_dir, records, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
