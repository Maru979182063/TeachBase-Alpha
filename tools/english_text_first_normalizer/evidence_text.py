from __future__ import annotations

import unicodedata
from typing import Any


SURFACE_BLANK_CHARS = {"_", "\uFF3F", "\u2014", "\uFF0D", "\u2013", "\u2500", "\u2501"}
META_LINE_MARKERS = ("_refs", "page_image_refs", "visual_refs", "writing_surface_refs")


def normalize_evidence_text(text: str) -> str:
    """Normalize text for evidence containment checks, not semantic parsing."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    out: list[str] = []
    for char in normalized:
        if char in SURFACE_BLANK_CHARS:
            out.append("_")
            continue
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith("P") or category.startswith("S"):
            if char == "_":
                out.append(char)
            continue
        out.append(char.lower())
    return "".join(out)


def strip_markdown_prefix(line: str) -> str:
    stripped = str(line or "").strip()
    while stripped.startswith("#"):
        stripped = stripped[1:].lstrip()
    if len(stripped) >= 2 and stripped[0] in {"-", "*", "+"} and stripped[1].isspace():
        stripped = stripped[2:].strip()
    return stripped


def is_markdown_heading(line: str) -> bool:
    stripped = str(line or "").lstrip()
    return stripped.startswith("#")


def is_metadata_line(line: str) -> bool:
    stripped = str(line or "").strip()
    return stripped.startswith("packet_") or any(marker in stripped for marker in META_LINE_MARKERS)


def meaningful_content_lines(text: str, *, min_normalized_chars: int = 8) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        if not raw_line.strip() or is_markdown_heading(raw_line) or is_metadata_line(raw_line):
            continue
        line = strip_markdown_prefix(raw_line)
        if len(normalize_evidence_text(line)) >= min_normalized_chars:
            lines.append(line)
    return lines


def _evidence_chunks(text: str, *, min_chunk_chars: int = 6) -> list[str]:
    """Return longer normalized script chunks for mixed Chinese/English source lines.

    This is still an evidence-containment check. It allows a model to split an
    original mixed line like "D. Justify a comparison. 证明一个比较的合理性。"
    into a translation field containing "D. 证明一个比较的合理性。", while keeping
    short labels such as "D" from acting as evidence by themselves.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_kind = ""

    def char_kind(char: str) -> str:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF:
            return "cjk"
        if char.isascii() and char.isalnum():
            return "latin"
        if char == "_":
            return "blank"
        return "other"

    def flush() -> None:
        nonlocal current
        if not current:
            return
        chunk = normalize_evidence_text("".join(current))
        if len(chunk) >= min_chunk_chars:
            chunks.append(chunk)
        current = []

    for raw_char in unicodedata.normalize("NFKC", str(text or "")):
        kind = char_kind(raw_char)
        if kind == "other" or raw_char.isspace():
            flush()
            current_kind = ""
            continue
        if current_kind and kind != current_kind:
            flush()
        current_kind = kind
        current.append(raw_char)
    flush()
    return chunks


def line_supported_by_source(source_norm: str, line: str, *, long_line_probe_chars: int = 80) -> bool:
    line_norm = normalize_evidence_text(line)
    if not line_norm:
        return True
    probes = [line_norm]
    if len(line_norm) > long_line_probe_chars + 20:
        probes = [line_norm[:long_line_probe_chars], line_norm[-long_line_probe_chars:]]
    if any(probe and probe in source_norm for probe in probes):
        return True

    chunks = _evidence_chunks(line)
    if not chunks:
        return False
    supported_chunks = [chunk for chunk in chunks if chunk in source_norm]
    supported_chars = sum(len(chunk) for chunk in supported_chunks)
    substantial_chars = sum(len(chunk) for chunk in chunks)
    return bool(supported_chunks) and supported_chars / max(substantial_chars, 1) >= 0.8


def unsupported_lines(
    *,
    source_text: str,
    output_text: str,
    max_examples: int = 8,
    long_line_probe_chars: int = 80,
) -> list[str]:
    source_norm = normalize_evidence_text(source_text)
    unsupported: list[str] = []
    for line in meaningful_content_lines(output_text):
        if not line_supported_by_source(source_norm, line, long_line_probe_chars=long_line_probe_chars):
            unsupported.append(line)
        if len(unsupported) >= max_examples:
            break
    return unsupported


def blank_run_count(text: str, *, min_run_length: int = 3) -> int:
    count = 0
    run = 0
    for char in unicodedata.normalize("NFKC", str(text or "")):
        if char in SURFACE_BLANK_CHARS:
            run += 1
            continue
        if run >= min_run_length:
            count += 1
        run = 0
    if run >= min_run_length:
        count += 1
    return count


def markdown_table_surface_present(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for index in range(len(lines) - 1):
        if "|" not in lines[index] or "|" not in lines[index + 1]:
            continue
        separator = lines[index + 1].strip().strip("|").replace(" ", "")
        if separator and all(char in {"-", ":", "|"} for char in separator):
            return True
    return False


def join_text_values(values: list[Any]) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if item is not None)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.extend(str(child) for child in item.values() if child is not None)
                elif item is not None:
                    parts.append(str(item))
        else:
            parts.append(str(value))
    return "\n".join(parts)
