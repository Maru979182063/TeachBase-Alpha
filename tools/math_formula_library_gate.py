from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KATEX_VALIDATOR = ROOT / "tools" / "katex_validate_math.cjs"
VALIDATOR_SCHEMA = "math_formula_library_gate_v0.1"
PATCH_SCHEMA = "latex_span_patch_actions_v0.1"
KNOWN_JOINED_MACROS = {
    "infty",
    "leqslant",
    "geqslant",
    "notin",
    "because",
    "therefore",
    "triangle",
    "parallel",
}


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def _find_unescaped(text: str, token: str, start: int) -> int:
    cursor = start
    token_len = len(token)
    while cursor <= len(text) - token_len:
        if text.startswith(token, cursor) and not _is_escaped(text, cursor):
            return cursor
        cursor += 1
    return -1


def extract_math_spans(markdown: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = str(markdown or "")
    spans: list[dict[str, Any]] = []
    delimiter_errors: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(text):
        if text.startswith("$$", cursor) and not _is_escaped(text, cursor):
            close = _find_unescaped(text, "$$", cursor + 2)
            if close < 0:
                delimiter_errors.append(
                    {
                        "risk_code": "math_delimiter_unclosed",
                        "char_start": cursor,
                        "char_end": len(text),
                        "source_span": text[cursor:],
                        "tex": text[cursor + 2 :],
                        "message": "Unclosed display math delimiter $$.",
                    }
                )
                break
            spans.append(
                {
                    "char_start": cursor,
                    "char_end": close + 2,
                    "source_span": text[cursor : close + 2],
                    "tex": text[cursor + 2 : close],
                    "display": True,
                    "delimiter": "$$",
                }
            )
            cursor = close + 2
            continue
        if text[cursor] == "$" and not _is_escaped(text, cursor):
            close = _find_unescaped(text, "$", cursor + 1)
            if close < 0:
                delimiter_errors.append(
                    {
                        "risk_code": "math_delimiter_unclosed",
                        "char_start": cursor,
                        "char_end": len(text),
                        "source_span": text[cursor:],
                        "tex": text[cursor + 1 :],
                        "message": "Unclosed inline math delimiter $.",
                    }
                )
                break
            spans.append(
                {
                    "char_start": cursor,
                    "char_end": close + 1,
                    "source_span": text[cursor : close + 1],
                    "tex": text[cursor + 1 : close],
                    "display": False,
                    "delimiter": "$",
                }
            )
            cursor = close + 1
            continue
        if text.startswith("\\(", cursor):
            close = text.find("\\)", cursor + 2)
            if close < 0:
                delimiter_errors.append(
                    {
                        "risk_code": "math_delimiter_unclosed",
                        "char_start": cursor,
                        "char_end": len(text),
                        "source_span": text[cursor:],
                        "tex": text[cursor + 2 :],
                        "message": "Unclosed inline math delimiter \\(.",
                    }
                )
                break
            spans.append(
                {
                    "char_start": cursor,
                    "char_end": close + 2,
                    "source_span": text[cursor : close + 2],
                    "tex": text[cursor + 2 : close],
                    "display": False,
                    "delimiter": "\\(",
                }
            )
            cursor = close + 2
            continue
        if text.startswith("\\[", cursor):
            close = text.find("\\]", cursor + 2)
            if close < 0:
                delimiter_errors.append(
                    {
                        "risk_code": "math_delimiter_unclosed",
                        "char_start": cursor,
                        "char_end": len(text),
                        "source_span": text[cursor:],
                        "tex": text[cursor + 2 :],
                        "message": "Unclosed display math delimiter \\[.",
                    }
                )
                break
            spans.append(
                {
                    "char_start": cursor,
                    "char_end": close + 2,
                    "source_span": text[cursor : close + 2],
                    "tex": text[cursor + 2 : close],
                    "display": True,
                    "delimiter": "\\[",
                }
            )
            cursor = close + 2
            continue
        cursor += 1
    return spans, delimiter_errors


def _run_katex(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not items:
        return {}
    request = {
        "items": [
            {
                "id": str(item["id"]),
                "tex": str(item.get("tex", "") or ""),
                "displayMode": bool(item.get("display", False)),
            }
            for item in items
        ]
    }
    result = subprocess.run(
        ["node", str(KATEX_VALIDATOR)],
        cwd=ROOT,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "katex_validator_failed")
    payload = json.loads(result.stdout or "{}")
    return {str(item.get("id") or ""): item for item in payload.get("results") or [] if isinstance(item, dict)}


def detect_macro_split_anomalies(tex: str) -> list[dict[str, Any]]:
    text = str(tex or "")
    anomalies: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] != "\\":
            cursor += 1
            continue
        command_start = cursor
        cursor += 1
        name_start = cursor
        while cursor < len(text) and text[cursor].isalpha():
            cursor += 1
        command_name = text[name_start:cursor]
        if not command_name:
            continue
        tail_start = cursor
        while tail_start < len(text) and text[tail_start].isspace():
            tail_start += 1
        tail_end = tail_start
        while tail_end < len(text) and text[tail_end].isalpha():
            tail_end += 1
        tail = text[tail_start:tail_end]
        if not tail:
            continue
        joined = command_name + tail
        if joined in KNOWN_JOINED_MACROS:
            anomalies.append(
                {
                    "risk_code": "latex_macro_split_anomaly",
                    "tex_start": command_start,
                    "tex_end": tail_end,
                    "source_tex": text[command_start:tail_end],
                    "suggested_macro": "\\" + joined,
                    "message": f"KaTeX parses this as separate tokens, but it matches a split macro name: \\{joined}.",
                }
            )
    return anomalies


def validate_markdown_text(markdown: str, *, field: str = "", block_ids: list[str] | None = None) -> dict[str, Any]:
    text = str(markdown or "")
    spans, delimiter_errors = extract_math_spans(text)
    risks: list[dict[str, Any]] = []
    for item in delimiter_errors:
        risks.append(
            {
                "risk_code": item["risk_code"],
                "field": field,
                "block_ids": list(block_ids or []),
                "span": item["source_span"],
                "source_span": item["source_span"],
                "match": item["source_span"],
                "char_start": item["char_start"],
                "char_end": item["char_end"],
                "tex": item.get("tex", ""),
                "message": item["message"],
                "suggested_action": "repair_math_delimiter_or_remove_math_mode",
                "validator": "markdown_delimiter_scanner",
            }
        )

    items = []
    for index, span in enumerate(spans, start=1):
        span["id"] = f"m_{index:04d}"
        if not str(span.get("tex", "") or "").strip():
            risks.append(
                {
                    "risk_code": "math_span_empty",
                    "field": field,
                    "block_ids": list(block_ids or []),
                    "span": span["source_span"],
                    "source_span": span["source_span"],
                    "match": span["source_span"],
                    "char_start": span["char_start"],
                    "char_end": span["char_end"],
                    "tex": span.get("tex", ""),
                    "message": "Empty math span.",
                    "suggested_action": "remove_empty_math_span_or_restore_visible_formula",
                    "validator": "markdown_delimiter_scanner",
                }
            )
            continue
        items.append(span)

    try:
        validation_by_id = _run_katex(items)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": VALIDATOR_SCHEMA,
            "validator": "katex",
            "available": False,
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
            "math_span_count": len(spans),
            "risks": risks,
        }

    for span in items:
        validation = validation_by_id.get(str(span["id"]), {})
        if validation.get("ok", False):
            for anomaly in detect_macro_split_anomalies(str(span.get("tex", "") or "")):
                risks.append(
                    {
                        "risk_code": anomaly["risk_code"],
                        "field": field,
                        "block_ids": list(block_ids or []),
                        "span": span["source_span"],
                        "source_span": span["source_span"],
                        "match": anomaly["source_tex"],
                        "char_start": span["char_start"],
                        "char_end": span["char_end"],
                        "tex": span.get("tex", ""),
                        "message": anomaly["message"],
                        "suggested_action": "repair_split_latex_macro",
                        "validator": "katex_macro_token_gate",
                        "katex": validation,
                        "anomaly": anomaly,
                    }
                )
        else:
            message = str(validation.get("error") or validation.get("rawMessage") or "KaTeX parse error")
            risks.append(
                {
                    "risk_code": "latex_parse_error",
                    "field": field,
                    "block_ids": list(block_ids or []),
                    "span": span["source_span"],
                    "source_span": span["source_span"],
                    "match": span["source_span"],
                    "char_start": span["char_start"],
                    "char_end": span["char_end"],
                    "tex": span.get("tex", ""),
                    "message": message,
                    "suggested_action": "repair_latex_span_until_katex_parses",
                    "validator": "katex",
                    "katex": validation,
                }
            )
    return {
        "schema": VALIDATOR_SCHEMA,
        "validator": "katex",
        "available": True,
        "valid": not risks,
        "math_span_count": len(spans),
        "risks": risks,
    }


def validate_fields(fields: dict[str, str], *, field_names: dict[str, str] | None = None) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    all_risks: list[dict[str, Any]] = []
    for key, value in fields.items():
        field_name = (field_names or {}).get(key, key)
        report = validate_markdown_text(str(value or ""), field=field_name)
        reports[key] = report
        all_risks.extend(report.get("risks") or [])
    return {
        "schema": VALIDATOR_SCHEMA,
        "validator": "katex",
        "valid": not all_risks and all(bool(report.get("valid", False)) for report in reports.values()),
        "risk_count": len(all_risks),
        "field_reports": reports,
        "risks": all_risks,
    }


def build_patch_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    validation = payload.get("formula_validation", {}) if isinstance(payload.get("formula_validation"), dict) else {}
    risks = validation.get("risks", []) if isinstance(validation.get("risks"), list) else []
    tasks: list[dict[str, Any]] = []
    for risk in risks:
        if not isinstance(risk, dict):
            continue
        source_span = str(risk.get("source_span") or risk.get("span") or "")
        if not source_span:
            continue
        task = {
            "task_id": f"lx_{len(tasks) + 1:04d}",
            "field": str(risk.get("field") or ""),
            "char_start": risk.get("char_start"),
            "char_end": risk.get("char_end"),
            "source_span": source_span,
            "match": str(risk.get("match") or ""),
            "tex": str(risk.get("tex") or ""),
            "risk_code": str(risk.get("risk_code") or ""),
            "message": str(risk.get("message") or ""),
            "validator": str(risk.get("validator") or ""),
            "suggested_macro": str(((risk.get("anomaly") or {}) if isinstance(risk.get("anomaly"), dict) else {}).get("suggested_macro") or ""),
        }
        tasks.append(task)
    return tasks


def build_patch_input(*, record_id: str, question_id: str, normalized_payload: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    display = normalized_payload.get("display_normalized_text", {})
    if not isinstance(display, dict):
        display = {}
    return {
        "record_id": record_id,
        "question_id": question_id,
        "schema": "latex_span_patch_input_v0.1",
        "policy": {
            "patches_only": True,
            "task_id_required": True,
            "replacement_must_include_markdown_math_delimiters": True,
            "no_full_field_rewrite": True,
            "no_cross_field_move": True,
            "final_validation": "katex",
        },
        "current_fields": {
            "stem": str(display.get("stem_text_md", "") or ""),
            "answer": str(display.get("answer_text_md", "") or ""),
            "analysis": str(display.get("analysis_text_md", "") or ""),
            "handwriting": str(display.get("handwriting_text_md", "") or ""),
        },
        "risky_spans": tasks,
    }


def build_deterministic_patch_actions(*, record_id: str, question_id: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    patches: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        if str(task.get("risk_code") or "") != "latex_macro_split_anomaly":
            unresolved.append({"task_id": task_id, "reason": "not_deterministic_macro_split"})
            continue
        source_span = str(task.get("source_span") or "")
        match = str(task.get("match") or "")
        suggested_macro = str(task.get("suggested_macro") or "")
        if not source_span or not match or not suggested_macro or match not in source_span:
            unresolved.append({"task_id": task_id, "reason": "missing_macro_split_repair_data"})
            continue
        patches.append(
            {
                "task_id": task_id,
                "replacement_text": source_span.replace(match, suggested_macro, 1),
                "confidence": "high",
                "notes": f"deterministic macro split repair: {match} -> {suggested_macro}",
            }
        )
    return {
        "schema": PATCH_SCHEMA,
        "record_id": record_id,
        "question_id": question_id,
        "patches": patches,
        "unresolved": unresolved,
    }


def apply_patch_actions(payload: dict[str, Any], parsed: dict[str, Any] | None, tasks: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    report: dict[str, Any] = {
        "schema": "latex_span_patch_application_v0.1",
        "task_count": len(tasks),
        "applied": [],
        "rejected": [],
        "unresolved": [],
    }
    if not isinstance(parsed, dict) or parsed.get("schema") != PATCH_SCHEMA:
        report["rejected"].append({"code": "invalid_patch_schema"})
        return payload, report

    patched = json.loads(json.dumps(payload, ensure_ascii=False))
    task_by_id = {str(task.get("task_id")): task for task in tasks}
    raw_text = patched.setdefault("raw_text", {})
    display_text = patched.setdefault("display_normalized_text", {})
    field_to_key = {
        "stem": "stem_text_md",
        "answer": "answer_text_md",
        "analysis": "analysis_text_md",
        "handwriting": "handwriting_text_md",
    }
    patches = parsed.get("patches", []) if isinstance(parsed.get("patches"), list) else []
    ordered: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for patch in patches:
        if not isinstance(patch, dict):
            report["rejected"].append({"code": "patch_not_object"})
            continue
        task = task_by_id.get(str(patch.get("task_id") or ""))
        if not task:
            report["rejected"].append({"code": "unknown_task_id", "task_id": patch.get("task_id")})
            continue
        replacement = str(patch.get("replacement_text") or "")
        if not replacement:
            report["rejected"].append({"code": "missing_replacement_text", "task_id": task.get("task_id")})
            continue
        ordered.append((task, patch, replacement))

    ordered.sort(key=lambda item: int(item[0].get("char_start") or 0), reverse=True)
    for task, patch, replacement in ordered:
        field = str(task.get("field") or "")
        key = field_to_key.get(field)
        start = task.get("char_start")
        end = task.get("char_end")
        source_span = str(task.get("source_span") or "")
        if key is None or not isinstance(start, int) or not isinstance(end, int) or end < start:
            report["rejected"].append({"code": "invalid_task_location", "task_id": task.get("task_id")})
            continue
        current = str(display_text.get(key, patched.get(key, "")) or "")
        if current[start:end] != source_span:
            report["rejected"].append(
                {
                    "code": "source_span_offset_mismatch",
                    "task_id": task.get("task_id"),
                    "expected": source_span,
                    "actual": current[start:end],
                }
            )
            continue
        updated = current[:start] + replacement + current[end:]
        patched[key] = updated
        display_text[key] = updated
        raw_text[key] = updated
        report["applied"].append(
            {
                "task_id": task.get("task_id"),
                "field": field,
                "risk_code": task.get("risk_code"),
                "source_chars": len(source_span),
                "replacement_chars": len(replacement),
                "confidence": patch.get("confidence"),
                "notes": patch.get("notes"),
            }
        )
    unresolved = parsed.get("unresolved", []) if isinstance(parsed.get("unresolved"), list) else []
    report["unresolved"] = unresolved
    return patched, report


def formula_structural_risks(markdown: str, *, field_name: str = "", block_ids: list[str] | None = None) -> list[dict[str, Any]]:
    report = validate_markdown_text(markdown, field=field_name, block_ids=block_ids)
    return list(report.get("risks") or [])


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    text = str(payload.get("markdown", "") if isinstance(payload, dict) else "")
    print(json.dumps(validate_markdown_text(text), ensure_ascii=False, indent=2))
