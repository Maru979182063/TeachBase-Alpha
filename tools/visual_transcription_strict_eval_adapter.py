from __future__ import annotations

import re

from visual_transcription_core import FIELD_NAMES, FIELD_TO_SHORT


INLINE_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)
INLINE_TOKEN_MATH_RE = re.compile(r"\$([A-Za-z0-9_]+)\$")
TEXT_TRANSLATION = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "＜": "<",
        "＞": ">",
        "＝": "=",
        "＋": "+",
        "－": "-",
        "×": "×",
        "脳": "×",
        "·": "×",
        "•": "×",
        "∴": "∴",
        "∵": "∵",
    }
)
HEADING_REPLACEMENTS = (
    ("[解答]", "【解答】"),
    ("[分析]", "【分析】"),
    ("[证明]", "【证明】"),
    ("[点评]", "【点评】"),
    ("[答案]", "【答案】"),
)


def normalize_escape_sequences(text: object) -> object:
    if not isinstance(text, str):
        return text
    normalized = text
    normalized = normalized.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    normalized = normalized.replace("\\[", "$$").replace("\\]", "$$")
    normalized = normalized.replace("\\(", "$").replace("\\)", "$")
    return normalized


def normalize_common_notation(text: object) -> object:
    if not isinstance(text, str):
        return text
    normalized = text.translate(TEXT_TRANSLATION)
    normalized = normalized.replace("\\neq", "\\ne")
    normalized = normalized.replace("$\\therefore$", "∴")
    normalized = normalized.replace("$\\because$", "∵")
    normalized = normalized.replace("\\therefore", "∴")
    normalized = normalized.replace("\\because", "∵")
    for before, after in HEADING_REPLACEMENTS:
        normalized = normalized.replace(before, after)
    return normalized


def normalize_math_segments(text: object) -> object:
    if not isinstance(text, str):
        return text

    def _replace(match: re.Match[str]) -> str:
        body = match.group(1) if match.group(1) is not None else match.group(2)
        body = re.sub(r"\s+", " ", body or "").strip()
        body = re.sub(r"\s*([=<>])\s*", r"\1", body)
        return f"${body}$"

    normalized = INLINE_MATH_RE.sub(_replace, text)
    normalized = INLINE_TOKEN_MATH_RE.sub(lambda m: m.group(1), normalized)
    return normalized


def normalize_text_spacing(text: object) -> object:
    if not isinstance(text, str):
        return text
    normalized = text
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"\$ +", "$", normalized)
    normalized = re.sub(r" +\$", "$", normalized)
    normalized = re.sub(r"([,;:.])([^\s\n])", r"\1\2", normalized)
    return normalized.strip()


def _extract_display_fields(transcription: dict) -> dict[str, str]:
    display = (
        transcription.get("display_normalized_text", {})
        if isinstance(transcription.get("display_normalized_text"), dict)
        else {}
    )
    fields = {}
    for field in FIELD_NAMES:
        fields[field] = str(display.get(field, transcription.get(field, "")) or "")
    return fields


def build_strict_eval_view(transcription: dict) -> dict:
    fields = _extract_display_fields(transcription)
    normalized_fields = {}
    normalization_log = []
    for field, value in fields.items():
        current = normalize_escape_sequences(value)
        current = normalize_common_notation(current)
        current = normalize_math_segments(current)
        current = normalize_text_spacing(current)
        normalized_fields[field] = current
        if current != value:
            normalization_log.append(
                {
                    "field": FIELD_TO_SHORT[field],
                    "op": "strict_eval_normalize",
                }
            )
    return {
        "fields": normalized_fields,
        "metadata": {
            "adapter_version": "strict_eval_v0.2",
            "normalization_log": normalization_log,
        },
    }


def normalize_transcription_fields(transcription: dict) -> dict:
    normalized = dict(transcription)
    strict_view = build_strict_eval_view(transcription)
    normalized.update(strict_view["fields"])
    normalized["strict_eval_adapter"] = strict_view["metadata"]
    return normalized
