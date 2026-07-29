from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any


NORMALIZER_VERSION = "docx_run_math_normalizer_v0.1"


ASCII_MATH_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "\\{}^_+-=()[]<>.,:;/* '"
)
EXTRA_MATH_CHARS = set("＝×÷−﹣≤≥±·°′″∠△⊥∥∽≌≠≈π（）")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def is_mathish_char(ch: str) -> bool:
    return ch in ASCII_MATH_CHARS or ch in EXTRA_MATH_CHARS


def contains_latin_or_digit(text: str) -> bool:
    return any(("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch.isdigit() for ch in text)


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def braces_are_balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def math_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text.startswith("\\(", i):
            j = text.find("\\)", i + 2)
            if j >= 0:
                ranges.append((i, j + 2))
                i = j + 2
                continue
        if text.startswith("\\[", i):
            j = text.find("\\]", i + 2)
            if j >= 0:
                ranges.append((i, j + 2))
                i = j + 2
                continue
        if text[i] == "$":
            marker = "$$" if text.startswith("$$", i) else "$"
            j = text.find(marker, i + len(marker))
            if j >= 0:
                ranges.append((i, j + len(marker)))
                i = j + len(marker)
                continue
        i += 1
    return ranges


def in_ranges(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)


def braced_script_end(text: str, marker: int) -> int | None:
    if marker + 1 >= len(text) or text[marker] not in "^_" or text[marker + 1] != "{":
        return None
    depth = 0
    for i in range(marker + 1, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def read_braced(text: str, open_brace: int) -> tuple[str, int] | None:
    if open_brace >= len(text) or text[open_brace] != "{":
        return None
    depth = 0
    start = open_brace + 1
    for i in range(open_brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
    return None


def math_marker_lengths(text: str, start: int, end: int) -> tuple[int, int] | None:
    if text.startswith("$$", start) and text[end - 2 : end] == "$$":
        return 2, 2
    if text.startswith("$", start) and text[end - 1 : end] == "$":
        return 1, 1
    if text.startswith("\\(", start) and text[end - 2 : end] == "\\)":
        return 2, 2
    if text.startswith("\\[", start) and text[end - 2 : end] == "\\]":
        return 2, 2
    return None


def fold_postfix_scripts_into_math(text: str) -> tuple[str, list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    out = text
    for start, end in reversed(math_ranges(out)):
        script_end = braced_script_end(out, end)
        marker_lengths = math_marker_lengths(out, start, end)
        if script_end is None or marker_lengths is None:
            continue
        open_len, close_len = marker_lengths
        body = out[start + open_len : end - close_len]
        script = out[end:script_end]
        before = out[start:script_end]
        after = f"${body}{script}$"
        out = out[:start] + after + out[script_end:]
        actions.append(
            {
                "char_start": start,
                "char_end": script_end,
                "before": before,
                "after": after,
                "action": "fold_word_run_script_postfix_into_existing_math",
            }
        )
    actions.reverse()
    return out, actions


def trim_fragment(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    while start < end and text[start] in "×÷*/.,;:":
        start += 1
    while end > start and text[end - 1] in "+-=＝×÷*/.,;:":
        end -= 1
    return start, end


def can_normalize_fragment(fragment: str) -> bool:
    if "$" in fragment:
        return False
    if "^{" not in fragment and "_{" not in fragment:
        return False
    if not braces_are_balanced(fragment):
        return False
    if not contains_latin_or_digit(fragment):
        return False
    return True


def expand_fragment(text: str, marker: int) -> tuple[int, int] | None:
    start = marker
    while start > 0 and is_mathish_char(text[start - 1]):
        start -= 1
    end = marker + 1
    while end < len(text) and is_mathish_char(text[end]):
        end += 1
    start, end = trim_fragment(text, start, end)
    if end <= start:
        return None
    fragment = text[start:end]
    if not can_normalize_fragment(fragment):
        return None
    return start, end


def normalize_script_content(content: str) -> str:
    content = content.strip()
    if content == "△":
        return r"\triangle "
    if content == "∠":
        return r"\angle "
    if content == "":
        return ""
    out = content.replace("△", r"\triangle ").replace("∠", r"\angle ")
    if has_cjk(out):
        return r"\text{" + out + "}"
    return out


def collapse_chained_subscripts(fragment: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(fragment):
        if i + 1 < len(fragment) and fragment[i] == "_" and fragment[i + 1] == "{":
            first = read_braced(fragment, i + 1)
            if not first:
                out.append(fragment[i])
                i += 1
                continue
            contents = [first[0]]
            j = first[1]
            while j + 1 < len(fragment) and fragment[j] == "_" and fragment[j + 1] == "{":
                nxt = read_braced(fragment, j + 1)
                if not nxt:
                    break
                contents.append(nxt[0])
                j = nxt[1]
            if len(contents) > 1:
                merged = "".join(normalize_script_content(part) for part in contents)
                out.append("_{")
                out.append(merged)
                out.append("}")
                i = j
                continue
            out.append("_{")
            out.append(normalize_script_content(contents[0]))
            out.append("}")
            i = j
            continue
        if i + 1 < len(fragment) and fragment[i] == "^" and fragment[i + 1] == "{":
            first = read_braced(fragment, i + 1)
            if first:
                out.append("^{")
                out.append(normalize_script_content(first[0]))
                out.append("}")
                i = first[1]
                continue
        out.append(fragment[i])
        i += 1
    return "".join(out)


def normalize_math_operators(fragment: str) -> str:
    replacements = {
        "＝": "=",
        "×": r"\times ",
        "÷": r"\div ",
        "−": "-",
        "≤": r"\le ",
        "≥": r"\ge ",
        "∠": r"\angle ",
        "△": r"\triangle ",
        "⊥": r"\perp ",
        "∥": r"\parallel ",
        "∽": r"\sim ",
        "≌": r"\cong ",
        "≠": r"\ne ",
        "≈": r"\approx ",
        "（": "(",
        "）": ")",
        "﹣": "-",
    }
    out = collapse_chained_subscripts(fragment)
    for old, new in replacements.items():
        out = out.replace(old, new)
    out = " ".join(out.split())
    out = out.replace(r"\times  ", r"\times ")
    return out


def merge_adjacent_dollar_math(text: str) -> tuple[str, list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != "$" or text.startswith("$$", i):
            out.append(text[i])
            i += 1
            continue
        end = text.find("$", i + 1)
        if end < 0:
            out.append(text[i])
            i += 1
            continue
        body = text[i + 1 : end]
        j = end + 1
        merged = False
        while j < len(text) and text[j] == "$" and not text.startswith("$$", j):
            next_end = text.find("$", j + 1)
            if next_end < 0:
                break
            body += text[j + 1 : next_end]
            j = next_end + 1
            merged = True
        if merged:
            before = text[i:j]
            after = f"${body}$"
            actions.append(
                {
                    "char_start": i,
                    "char_end": j,
                    "before": before,
                    "after": after,
                    "action": "merge_adjacent_math_spans",
                }
            )
            out.append(after)
            i = j
        else:
            out.append(text[i : end + 1])
            i = end + 1
    return "".join(out), actions


def suspicious_math_markup(text: str) -> list[str]:
    issues: list[str] = []
    if text.count("$") % 2 != 0:
        issues.append("unbalanced_dollar_math")
    for marker in ["$$", "${", "$^", "$_", "$}_{", "}$$", "'$", "$'"]:
        if marker in text:
            issues.append(f"suspicious_marker:{marker}")
    return issues


def validate_candidate_math(markdown: str, *, block_id: str | None) -> list[dict[str, Any]]:
    try:
        import math_formula_library_gate
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "risk_code": "math_validator_unavailable",
                "message": f"{type(exc).__name__}: {exc}",
            }
        ]
    report = math_formula_library_gate.validate_markdown_text(
        markdown,
        field="display_markdown",
        block_ids=[block_id] if block_id else None,
    )
    if bool(report.get("valid", False)):
        return []
    return list(report.get("risks") or [])


def find_run_math_spans(text: str) -> list[tuple[int, int]]:
    existing_math = math_ranges(text)
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text) - 1:
        if text[i] in "^_" and text[i + 1] == "{" and not in_ranges(i, existing_math):
            expanded = expand_fragment(text, i)
            if expanded:
                start, end = expanded
                if not any(not (end <= s or start >= e) for s, e in spans):
                    spans.append((start, end))
                i = end
                continue
        i += 1
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def normalize_block_markdown(markdown: str) -> tuple[str, list[dict[str, Any]]]:
    markdown, actions = fold_postfix_scripts_into_math(markdown)
    spans = find_run_math_spans(markdown)
    if not spans:
        return markdown, actions
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        original = markdown[start:end]
        normalized = normalize_math_operators(original)
        pieces.append(markdown[cursor:start])
        pieces.append(f"${normalized}$")
        actions.append(
            {
                "char_start": start,
                "char_end": end,
                "before": original,
                "after": f"${normalized}$",
                "action": "wrap_word_run_script_fragment_as_math",
            }
        )
        cursor = end
    pieces.append(markdown[cursor:])
    merged, merge_actions = merge_adjacent_dollar_math("".join(pieces))
    actions.extend(merge_actions)
    return merged, actions


def block_has_run_script_formula(block: dict[str, Any]) -> bool:
    for ref in block.get("formula_refs") or []:
        ref_type = str(ref.get("type") or ref.get("status") or "")
        source = str(ref.get("source") or "")
        if ref_type in {"run_superscript", "run_subscript"} or source == "word_run_vert_align":
            return True
    return False


def stream_items(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(payload.get("blocks"), list):
        return "blocks", payload["blocks"]
    if isinstance(payload.get("paragraphs"), list):
        return "paragraphs", payload["paragraphs"]
    return "blocks", []


def normalize_stream(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    out = json.loads(json.dumps(payload, ensure_ascii=False))
    container_key, items = stream_items(out)
    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    touched_blocks = 0
    for block in items:
        if not block_has_run_script_formula(block):
            continue
        before = str(block.get("display_markdown") or "")
        after, block_actions = normalize_block_markdown(before)
        if not block_actions:
            continue
        issues = suspicious_math_markup(after)
        if issues:
            skipped.append(
                {
                    "block_id": block.get("block_id"),
                    "issues": issues,
                    "before": before,
                    "candidate_after": after,
                    "action_count": len(block_actions),
                }
            )
            flags = list(block.get("content_loss_flags") or [])
            if "run_math_normalizer_skipped_unsafe_candidate" not in flags:
                flags.append("run_math_normalizer_skipped_unsafe_candidate")
            block["content_loss_flags"] = flags
            continue
        validator_risks = validate_candidate_math(after, block_id=str(block.get("block_id") or ""))
        if validator_risks:
            skipped.append(
                {
                    "block_id": block.get("block_id"),
                    "issues": ["validator_invalid_candidate"],
                    "validator_risks": validator_risks,
                    "before": before,
                    "candidate_after": after,
                    "action_count": len(block_actions),
                }
            )
            flags = list(block.get("content_loss_flags") or [])
            if "run_math_normalizer_skipped_invalid_candidate" not in flags:
                flags.append("run_math_normalizer_skipped_invalid_candidate")
            block["content_loss_flags"] = flags
            continue
        touched_blocks += 1
        block["display_markdown_before_run_math_normalizer"] = before
        block["display_markdown"] = after
        block["run_math_normalization_actions"] = block_actions
        flags = list(block.get("content_loss_flags") or [])
        if "run_math_normalized" not in flags:
            flags.append("run_math_normalized")
        block["content_loss_flags"] = flags
        actions.append(
            {
                "block_id": block.get("block_id"),
                "formula_refs": block.get("formula_refs") or [],
                "action_count": len(block_actions),
                "before": before,
                "after": after,
                "actions": block_actions,
            }
        )
    out["normalization"] = {
        "schema": NORMALIZER_VERSION,
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "stream_container": container_key,
        "changed_block_count": touched_blocks,
        "action_count": sum(len(item["actions"]) for item in actions),
        "skipped_block_count": len(skipped),
    }
    report = {
        "schema": NORMALIZER_VERSION + "_report",
        "stream_container": container_key,
        "input_item_count": len(items),
        "changed_block_count": touched_blocks,
        "action_count": sum(len(item["actions"]) for item in actions),
        "skipped_block_count": len(skipped),
        "actions": actions,
        "skipped": skipped,
    }
    return out, report


def render_probe_html(report: dict[str, Any], out_path: Path, limit: int | None = None) -> None:
    rows = []
    actions = report.get("actions") or []
    if limit is not None:
        actions = actions[:limit]
    for item in actions:
        rows.append(
            "<section>"
            f"<h2>{html.escape(str(item.get('block_id') or ''))}</h2>"
            "<h3>Before</h3>"
            f"<pre>{html.escape(str(item.get('before') or ''))}</pre>"
            "<h3>After</h3>"
            f"<pre>{html.escape(str(item.get('after') or ''))}</pre>"
            "</section>"
        )
    doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>DOCX Run Math Normalizer Probe</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fb;color:#0f172a}}
section{{background:white;border:1px solid #ccd6e3;border-radius:8px;padding:16px;margin:16px 0}}
pre{{white-space:pre-wrap;font-size:18px;line-height:1.65;background:#f8fafc;border:1px solid #e2e8f0;padding:12px}}
.meta{{color:#475569}}
</style>
</head>
<body>
<h1>DOCX Run Math Normalizer Probe</h1>
<p class="meta">changed blocks={report.get('changed_block_count')} actions={report.get('action_count')}</p>
{''.join(rows)}
</body>
</html>"""
    write_text(out_path, doc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize DOCX run-level superscript/subscript fragments into Markdown math spans.")
    parser.add_argument("--input-block-stream", required=True, type=Path)
    parser.add_argument("--output-root", default=Path("outputs/docx_run_math_normalizer_v0_1"), type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--probe-html", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or dt.datetime.now().strftime("run_math_normalizer_%Y%m%d_%H%M%S")
    out_dir = args.output_root / run_id
    payload = read_json(args.input_block_stream)
    normalized, report = normalize_stream(payload)
    report["source_block_stream"] = str(args.input_block_stream)
    report["output_block_stream"] = str(out_dir / "normalized_block_stream.json")
    write_json(out_dir / "normalized_block_stream.json", normalized)
    write_json(out_dir / "run_math_normalization_report.json", report)
    if args.probe_html:
        render_probe_html(report, out_dir / "index.html")
    print(
        json.dumps(
            {
                "run_id": run_id,
                "out_dir": str(out_dir),
                "artifacts": {
                    "normalized_stream": str(out_dir / "normalized_block_stream.json"),
                    "normalization_report": str(out_dir / "run_math_normalization_report.json"),
                    "preview_html": str(out_dir / "index.html") if args.probe_html else "",
                },
                **normalized["normalization"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
