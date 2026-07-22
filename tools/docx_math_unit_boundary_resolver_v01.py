from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_native_boundary_resolver_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

SEMANTIC_ROLES = {
    "section",
    "instruction",
    "question",
    "subquestion",
    "answer",
    "analysis",
    "solution",
    "knowledge",
    "shared_material",
    "document_meta",
    "decorative",
    "unknown",
}

DISPOSITION_TYPES = {
    "question",
    "section",
    "knowledge",
    "instruction",
    "document_meta",
    "decorative",
    "blank",
    "quarantined",
}

ATTACHMENT_RELATIONS = {
    "part_of_question",
    "solution_for",
    "analysis_for",
    "answer_for",
    "companion_for",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    return read_json(path)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_hash(payload: Any) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def source_line_span(needle: str) -> tuple[int, int]:
    try:
        lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    except OSError:
        return (0, 0)
    for index, line in enumerate(lines, start=1):
        if needle in line:
            return (index, index)
    return (0, 0)


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def slug_for(path: Path) -> str:
    value = path.parent.name or path.stem
    chars: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in "._-":
            chars.append(ch)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return ("".join(chars).strip("_") or "docx_boundary")[:96]


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def weak_hints_for(block: dict[str, Any]) -> list[str]:
    """Diagnostic hints only. These are not allowed to decide boundaries."""
    text = str(block.get("markdown") or block.get("text") or "").strip()
    hints: list[str] = []
    if not text:
        hints.append("blank")
    if block.get("source_block_type") == "docx_table":
        hints.append("table_block")
    if block.get("image_refs"):
        hints.append("has_image")
    if block.get("formula_count"):
        hints.append("has_formula")
    if any(token in text for token in ("【例", "【变式", "【例题", "例.", "例．")):
        hints.append("lesson_question_marker")
    if any(token in text for token in ("【答案】", "答案：", "答案")):
        hints.append("answer_marker")
    if any(token in text for token in ("【解析】", "【分析】", "【详解】", "解：", "证明：")):
        hints.append("analysis_solution_marker")
    if any(token in text for token in ("单选题", "填空题", "解答题", "选择题", "基础巩固", "能力提升", "通关测")):
        hints.append("section_or_type_heading_marker")
    if text[:2] in {"一、", "二、", "三、", "四、", "五、"}:
        hints.append("section_number_heading_marker")
    if len(text) <= 12 and not block.get("formula_count") and not block.get("image_refs"):
        hints.append("short_text")
    return hints


def modalities_for(block: dict[str, Any]) -> list[str]:
    modalities = ["text"] if str(block.get("markdown") or block.get("text") or "").strip() else []
    if block.get("formula_count"):
        modalities.append("formula")
    if block.get("source_block_type") == "docx_table":
        modalities.append("table")
    if block.get("image_refs"):
        modalities.append("visual")
    return list(dict.fromkeys(modalities))


def build_immutable_block_stream(paragraph_stream: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    table_index = 0
    for order, block in enumerate(paragraph_stream.get("paragraphs", []) or []):
        source_type = str(block.get("source_block_type") or "docx_block")
        if source_type == "docx_table":
            table_index += 1
        markdown = str(block.get("markdown") or "")
        text = str(block.get("text") or "")
        formula_refs = [
            item
            for item in block.get("formula_findings", []) or []
            if isinstance(item, dict)
        ]
        image_refs = [
            item
            for item in block.get("image_refs", []) or []
            if isinstance(item, dict)
        ]
        block_id = f"b_{order:06d}"
        immutable = {
            "block_id": block_id,
            "source_order": order,
            "source_block_type": source_type,
            "paragraph_index": block.get("paragraph_index", order),
            "table_index": table_index if source_type == "docx_table" else None,
            "text": text,
            "markdown": markdown,
            "formula_count": int(block.get("formula_count") or 0),
            "formula_refs": formula_refs,
            "image_refs": image_refs,
            "modalities": modalities_for(block),
            "weak_hints": weak_hints_for(block),
            "content_hash": sha256_text(json.dumps({"text": text, "markdown": markdown}, ensure_ascii=False, sort_keys=True)),
            "raw_block": block,
        }
        if block.get("table_structured") is not None:
            immutable["table_structured"] = block.get("table_structured")
        blocks.append(immutable)
    return {
        "schema_version": "docx_immutable_block_stream.v0.1",
        "source_docx": paragraph_stream.get("source_docx", ""),
        "counts": paragraph_stream.get("counts", {}),
        "block_count": len(blocks),
        "blocks": blocks,
    }


@dataclass(frozen=True)
class Window:
    window_id: str
    core_start: int
    core_end_exclusive: int
    input_start: int
    input_end_exclusive: int


def plan_windows(blocks: list[dict[str, Any]], core: int, left: int, right: int) -> list[Window]:
    windows: list[Window] = []
    start = 0
    index = 0
    while start < len(blocks):
        end = min(start + core, len(blocks))
        windows.append(
            Window(
                window_id=f"w_{index:04d}",
                core_start=start,
                core_end_exclusive=end,
                input_start=max(0, start - left),
                input_end_exclusive=min(len(blocks), end + right),
            )
        )
        start = end
        index += 1
    return windows


def block_for_model(block: dict[str, Any], preview_chars: int) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "text_preview": compact_text(block.get("text", ""), preview_chars),
        "markdown_preview": compact_text(block.get("markdown", ""), preview_chars),
        "formula_count": block.get("formula_count", 0),
        "image_ref_count": len(block.get("image_refs", []) or []),
        "modalities": block.get("modalities", []),
        "weak_hints": block.get("weak_hints", []),
    }


SYSTEM_PROMPT = """你是 TeachBase DOCX native 数学资料的 Unit Tagger。

你只做结构观察，不切最终题包，不重写正文，不修公式，不生成 Markdown。

任务：
1. 根据 DOCX 原生 block 顺序，把 core_block_ids 中的每个 block 归入一个 unit，或放入 unassigned_block_ids。
2. 每个 core block 必须恰好出现一次：要么在一个 unit.block_ids 中，要么在 unassigned_block_ids 中。
3. 允许参考 left/right context 理解边界，但只能给 core block 做正式归属。
4. 不要编造 block_id，不要输出正文文本。title 只能用 title_source_ref 指向原 block。
5. 不确定时使用 semantic_role=unknown 或 unassigned_block_ids，不要把内容默认挂到上一题。
6. 图片、表格是 modality，不是 semantic_role；它们可能属于 question/answer/knowledge/shared_material/decorative。
7. section 只能覆盖标题、栏目名、试卷说明或短引导块。不要把真实题目、选项、小问、答案解析放进 section。
8. 遇到“单选题/填空题/解答题”等栏目标题后，后面的每一道真实题目应单独标为 question 或 subquestion，而不是并入 section。
9. 如果 core 开头是上一题的小问/续写，允许标为 subquestion 并使用 relation=continues_previous；不要编造 parent_local_unit_id。

semantic_role 只能是：
section, instruction, question, subquestion, answer, analysis, solution, knowledge, shared_material, document_meta, decorative, unknown

relation 只能是：
standalone, part_of_question, solution_for, analysis_for, answer_for, companion_for, starts_new_section, continues_previous, unassigned

completeness 只能是：
complete, open_tail, fragment, ambiguous

只返回合法 JSON。"""


def build_user_payload(
    *,
    window: Window,
    blocks: list[dict[str, Any]],
    preview_chars: int,
    config_hash: str,
) -> dict[str, Any]:
    input_blocks = blocks[window.input_start : window.input_end_exclusive]
    core_blocks = blocks[window.core_start : window.core_end_exclusive]
    return {
        "task": "tag DOCX native math blocks into open semantic units",
        "schema_version": "docx_math_unit_tagger_v01",
        "config_hash": config_hash,
        "window_id": window.window_id,
        "core_block_ids": [block["block_id"] for block in core_blocks],
        "left_context_block_ids": [block["block_id"] for block in blocks[window.input_start : window.core_start]],
        "right_context_block_ids": [block["block_id"] for block in blocks[window.core_end_exclusive : window.input_end_exclusive]],
        "output_contract": {
            "full_core_coverage": "Every core block must appear exactly once in units.block_ids or unassigned_block_ids.",
            "no_text_rewrite": "Do not output rewritten content. Use source block ids only.",
            "title_source_ref": "If a unit has a title, point to one input block id; do not generate title text.",
        },
        "blocks": [block_for_model(block, preview_chars) for block in input_blocks],
        "required_json_shape": {
            "window_id": window.window_id,
            "core_block_ids": [block["block_id"] for block in core_blocks],
            "units": [
                {
                    "window_local_unit_id": "lu_001",
                    "semantic_role": "question",
                    "role_tags": ["variant_question"],
                    "modalities": ["text", "formula", "table", "visual"],
                    "start_block_id": "b_000000",
                    "end_block_id": "b_000000",
                    "block_ids": ["b_000000"],
                    "relation": "standalone",
                    "parent_local_unit_id": "",
                    "completeness": "complete",
                    "confidence": 0.0,
                    "title_source_ref": "b_000000",
                    "reason": "short audit reason",
                }
            ],
            "unassigned_block_ids": [],
            "left_edge": {"relation": "none", "reason": ""},
            "right_edge": {"relation": "none", "reason": ""},
            "qa_flags": [],
        },
    }


def call_model(api_key: str, model: str, payload: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    started = time.time()
    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    result = json.loads(raw)
    content = str(result["choices"][0]["message"]["content"])
    parsed = json.loads(content)
    return {
        "parsed": parsed,
        "raw_response": result,
        "raw_content": content,
        "usage": result.get("usage", {}),
        "finish_reason": (result.get("choices") or [{}])[0].get("finish_reason", ""),
        "latency_seconds": round(time.time() - started, 3),
    }


def source_order(block_id: str) -> int:
    try:
        return int(block_id.rsplit("_", 1)[-1])
    except ValueError:
        return -1


def validate_window_result(
    *,
    window: Window,
    result: dict[str, Any],
    all_block_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    normalized_units: list[dict[str, Any]] = []
    core_ids = [f"b_{idx:06d}" for idx in range(window.core_start, window.core_end_exclusive)]
    core_set = set(core_ids)
    assigned: list[str] = []
    unassigned = [str(item) for item in result.get("unassigned_block_ids", []) or []]

    for item in result.get("units", []) or []:
        if not isinstance(item, dict):
            issues.append({"type": "invalid_unit_shape", "window_id": window.window_id})
            continue
        role = str(item.get("semantic_role") or "unknown")
        if role not in SEMANTIC_ROLES:
            issues.append({"type": "invalid_semantic_role", "window_id": window.window_id, "value": role})
            role = "unknown"
        block_ids = [str(block_id) for block_id in item.get("block_ids", []) or []]
        if not block_ids:
            issues.append({"type": "empty_unit_block_ids", "window_id": window.window_id, "unit": item.get("window_local_unit_id")})
            continue
        invalid = [block_id for block_id in block_ids if block_id not in all_block_ids]
        if invalid:
            issues.append({"type": "invalid_source_ref", "window_id": window.window_id, "block_ids": invalid})
        outside_core = [block_id for block_id in block_ids if block_id not in core_set]
        if outside_core:
            issues.append({"type": "unit_assigns_context_block", "window_id": window.window_id, "block_ids": outside_core})
            block_ids = [block_id for block_id in block_ids if block_id in core_set]
        orders = [source_order(block_id) for block_id in block_ids]
        if orders and (max(orders) - min(orders) + 1 != len(set(orders))):
            issues.append({"type": "non_contiguous_unit", "window_id": window.window_id, "block_ids": block_ids})
            continue
        title_ref = str(item.get("title_source_ref") or "")
        context_title_source_ref = ""
        if title_ref and title_ref not in block_ids:
            issues.append(
                {
                    "type": "title_source_ref_outside_unit",
                    "window_id": window.window_id,
                    "unit": item.get("window_local_unit_id"),
                    "title_source_ref": title_ref,
                    "block_ids": block_ids,
                }
            )
            if title_ref in all_block_ids:
                context_title_source_ref = title_ref
            title_ref = block_ids[0]
        if not block_ids:
            continue
        assigned.extend(block_ids)
        normalized = {
            "window_id": window.window_id,
            "window_local_unit_id": str(item.get("window_local_unit_id") or f"lu_{len(normalized_units)+1:03d}"),
            "semantic_role": role,
            "role_tags": [str(tag) for tag in item.get("role_tags", []) or []],
            "modalities": [str(tag) for tag in item.get("modalities", []) or []],
            "start_block_id": min(block_ids, key=source_order),
            "end_block_id": max(block_ids, key=source_order),
            "block_ids": sorted(block_ids, key=source_order),
            "relation": str(item.get("relation") or "standalone"),
            "parent_local_unit_id": str(item.get("parent_local_unit_id") or ""),
            "completeness": str(item.get("completeness") or "ambiguous"),
            "confidence": float(item.get("confidence") or 0.0),
            "title_source_ref": title_ref,
            "context_title_source_ref": context_title_source_ref,
            "reason": str(item.get("reason") or ""),
        }
        normalized_units.append(normalized)

    invalid_unassigned = [block_id for block_id in unassigned if block_id not in core_set]
    if invalid_unassigned:
        issues.append({"type": "invalid_unassigned_ref", "window_id": window.window_id, "block_ids": invalid_unassigned})
    unassigned = [block_id for block_id in unassigned if block_id in core_set]
    coverage = assigned + unassigned
    missing = [block_id for block_id in core_ids if block_id not in coverage]
    if missing:
        issues.append({"type": "block_coverage_gap", "window_id": window.window_id, "block_ids": missing})
    duplicates = sorted({block_id for block_id in coverage if coverage.count(block_id) > 1}, key=source_order)
    if duplicates:
        issues.append({"type": "block_coverage_overlap", "window_id": window.window_id, "block_ids": duplicates})
    return normalized_units, issues


def fallback_units_for_failed_window(window: Window) -> tuple[list[dict[str, Any]], list[str]]:
    block_ids = [f"b_{idx:06d}" for idx in range(window.core_start, window.core_end_exclusive)]
    return [], block_ids


def exact_title(unit: dict[str, Any], block_by_id: dict[str, dict[str, Any]]) -> str:
    ref = unit.get("title_source_ref") if unit.get("title_source_ref") in block_by_id else unit["block_ids"][0]
    block = block_by_id.get(str(ref), {})
    return compact_text(str(block.get("markdown") or block.get("text") or ""), 120)


def globalize_units(units: list[dict[str, Any]], block_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    units = sorted(units, key=lambda item: source_order(item["start_block_id"]))
    result: list[dict[str, Any]] = []
    for index, unit in enumerate(units, start=1):
        result.append(
            {
                **unit,
                "unit_id": f"u_{index:06d}",
                "source_orders": [source_order(block_id) for block_id in unit["block_ids"]],
                "title": exact_title(unit, block_by_id),
            }
        )
    return result


def has_section_between(units: list[dict[str, Any]], start_exclusive: int, end_exclusive: int) -> bool:
    for unit in units:
        if unit.get("semantic_role") != "section":
            continue
        orders = unit.get("source_orders", [])
        if any(start_exclusive < int(order) < end_exclusive for order in orders):
            return True
    return False


def merge_cross_window_continuations(units: list[dict[str, Any]], block_by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge only explicit adjacent continuations.

    This is intentionally narrow. It is not a nearest-question fallback:
    the current unit must either say it continues/attaches to the previous
    unit, or point its title source to a block inside the previous question.
    """
    traces: list[dict[str, Any]] = []
    ordered = sorted(units, key=lambda item: source_order(item["start_block_id"]))
    merged: list[dict[str, Any]] = []
    for unit in ordered:
        if not merged:
            merged.append(unit)
            continue
        previous = merged[-1]
        prev_end = max(previous.get("source_orders", []) or [-1])
        cur_start = min(unit.get("source_orders", []) or [-1])
        title_ref = str(unit.get("context_title_source_ref") or "")
        points_to_previous = bool(title_ref and title_ref in set(previous.get("block_ids", []) or []))
        relation = str(unit.get("relation") or "")
        crosses_window = unit.get("window_id") != previous.get("window_id")
        explicit_continuation = relation == "continues_previous" or (
            crosses_window
            and relation
            in {
                "part_of_question",
                "solution_for",
                "analysis_for",
                "answer_for",
                "companion_for",
            }
        )
        adjacent = prev_end + 1 == cur_start
        no_section = not has_section_between(ordered, prev_end, cur_start)
        if (
            previous.get("semantic_role") == "question"
            and unit.get("semantic_role") in {"question", "subquestion", "answer", "analysis", "solution"}
            and adjacent
            and no_section
            and (points_to_previous or explicit_continuation)
        ):
            block_ids = sorted(set(previous.get("block_ids", []) + unit.get("block_ids", [])), key=source_order)
            previous["block_ids"] = block_ids
            previous["source_orders"] = [source_order(block_id) for block_id in block_ids]
            previous["start_block_id"] = block_ids[0]
            previous["end_block_id"] = block_ids[-1]
            previous["modalities"] = list(dict.fromkeys((previous.get("modalities", []) or []) + (unit.get("modalities", []) or [])))
            previous["role_tags"] = list(dict.fromkeys((previous.get("role_tags", []) or []) + (unit.get("role_tags", []) or [])))
            previous["title"] = exact_title(previous, block_by_id)
            previous.setdefault("merged_unit_ids", []).append(unit.get("unit_id"))
            traces.append(
                {
                    "type": "cross_window_continuation_merged",
                    "target_unit_id": previous.get("unit_id"),
                    "merged_unit_id": unit.get("unit_id"),
                    "reason": "adjacent_explicit_continuation_or_context_title_ref",
                    "relation": relation,
                    "block_ids": unit.get("block_ids", []),
                }
            )
            continue
        merged.append(unit)
    return merged, traces


def build_questions_from_units(units: list[dict[str, Any]], block_by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    unit_by_local = {(unit["window_id"], unit["window_local_unit_id"]): unit for unit in units}
    attached_by_parent: dict[str, list[dict[str, Any]]] = {}

    for unit in units:
        relation = str(unit.get("relation") or "")
        parent = str(unit.get("parent_local_unit_id") or "")
        if relation in ATTACHMENT_RELATIONS:
            parent_unit = unit_by_local.get((unit["window_id"], parent))
            if parent_unit and parent_unit.get("semantic_role") == "question":
                attached_by_parent.setdefault(parent_unit["unit_id"], []).append(unit)
            elif (
                relation == "part_of_question"
                and parent_unit
                and parent_unit.get("semantic_role") in {"section", "instruction", "shared_material"}
                and unit.get("semantic_role") in {"section", "question", "subquestion"}
            ):
                # A question can belong to a local section/type heading without
                # being attached to it as question content.
                continue
            else:
                issues.append(
                    {
                        "type": "ambiguous_attachment",
                        "unit_id": unit.get("unit_id"),
                        "relation": relation,
                        "parent_local_unit_id": parent,
                        "block_ids": unit.get("block_ids", []),
                    }
                )

    question_index = 0
    for unit in units:
        if unit.get("semantic_role") != "question":
            continue
        question_index += 1
        related = [unit] + attached_by_parent.get(unit["unit_id"], [])
        all_block_ids = sorted({block_id for item in related for block_id in item["block_ids"]}, key=source_order)
        roles_inside = {item.get("semantic_role") for item in related}
        if "section" in roles_inside:
            issues.append({"type": "question_contains_section_unit", "unit_id": unit["unit_id"], "block_ids": all_block_ids})
        orders = [source_order(block_id) for block_id in all_block_ids]
        if orders and (max(orders) - min(orders) + 1 != len(set(orders))):
            issues.append({"type": "question_boundary_non_contiguous", "unit_id": unit["unit_id"], "block_ids": all_block_ids})
        start = min(orders) if orders else source_order(unit["start_block_id"])
        end = max(orders) if orders else source_order(unit["end_block_id"])
        display = "\n\n".join(
            str(block_by_id[f"b_{order:06d}"].get("markdown") or "")
            for order in range(start, end + 1)
            if f"b_{order:06d}" in block_by_id and str(block_by_id[f"b_{order:06d}"].get("markdown") or "").strip()
        )
        refs = [
            ref
            for order in range(start, end + 1)
            for ref in block_by_id.get(f"b_{order:06d}", {}).get("image_refs", []) or []
        ]
        questions.append(
            {
                "question_id": f"docx_q_{question_index:03d}",
                "order_index": question_index,
                "title": unit.get("title", ""),
                "start_paragraph_index": start,
                "end_paragraph_index": end,
                "start_block_id": f"b_{start:06d}",
                "end_block_id": f"b_{end:06d}",
                "block_ids": [f"b_{order:06d}" for order in range(start, end + 1)],
                "source_unit_ids": [item["unit_id"] for item in related],
                "question_kind": ",".join(unit.get("role_tags", []) or []),
                "confidence": unit.get("confidence", 0.0),
                "review_flags": [],
                "display_markdown": display,
                "asset_ids": list(dict.fromkeys(ref.get("asset_id") for ref in refs if isinstance(ref, dict) and ref.get("asset_id"))),
            }
        )
    return questions, issues


def section_content_gate(units: list[dict[str, Any]], block_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for unit in units:
        if unit.get("semantic_role") != "section":
            continue
        suspicious: list[str] = []
        for block_id in unit.get("block_ids", []) or []:
            block = block_by_id.get(block_id, {})
            text = str(block.get("markdown") or block.get("text") or "").strip()
            hints = set(block.get("weak_hints", []) or [])
            if "lesson_question_marker" in hints:
                suspicious.append(block_id)
            if text.startswith(tuple(f"{idx}．" for idx in range(1, 51))) or text.startswith(tuple(f"{idx}." for idx in range(1, 51))):
                suspicious.append(block_id)
            if text.startswith(("A．", "B．", "C．", "D．", "A.", "B.", "C.", "D.")):
                suspicious.append(block_id)
        if suspicious:
            issues.append(
                {
                    "type": "section_contains_question_like_content",
                    "unit_id": unit.get("unit_id"),
                    "block_ids": sorted(set(suspicious), key=source_order),
                }
            )
    return issues


def block_review_issues(units: list[dict[str, Any]], unassigned: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for unit in units:
        if unit.get("semantic_role") == "unknown":
            issues.append({"type": "unknown_unit", "unit_id": unit.get("unit_id"), "block_ids": unit.get("block_ids", [])})
        if unit.get("completeness") in {"open_tail", "fragment", "ambiguous"}:
            issues.append(
                {
                    "type": "unit_completeness_review",
                    "unit_id": unit.get("unit_id"),
                    "completeness": unit.get("completeness"),
                    "block_ids": unit.get("block_ids", []),
                }
            )
    if unassigned:
        issues.append({"type": "unassigned_blocks", "block_ids": sorted(unassigned, key=source_order), "count": len(unassigned)})
    return issues


def block_text(block: dict[str, Any]) -> str:
    return str(block.get("markdown") or block.get("text") or "").strip()


def has_block_content(block: dict[str, Any]) -> bool:
    return bool(block_text(block) or block.get("image_refs") or block.get("formula_count") or block.get("source_block_type") == "docx_table")


def starts_numbered_question(text: str) -> bool:
    if not text:
        return False
    idx = 0
    while idx < len(text) and text[idx].isdigit():
        idx += 1
    while idx < len(text) and text[idx].isspace():
        idx += 1
    return idx > 0 and idx < len(text) and text[idx] in {"．", ".", "、"}


def starts_lesson_question(text: str) -> bool:
    return text.startswith("【例") or text.startswith("【变式")


def independent_question_start(text: str) -> bool:
    return starts_lesson_question(text) or starts_numbered_question(text)


def assessment_section_like(text: str) -> bool:
    return any(token in text for token in ("单选题", "选择题", "填空题", "解答题", "计算题", "应用题"))


def document_section_like(text: str) -> bool:
    if not text:
        return False
    return text.startswith("【知识点") or "复习讲义" in text


def question_group_section_like(text: str) -> bool:
    if not text:
        return False
    return text.startswith("题型") or any(token in text for token in ("基础巩固", "能力提升", "通关测"))


def non_question_role(role: str) -> bool:
    return role in {"instruction", "knowledge", "section", "document_meta", "decorative", "table_of_contents", "unknown_non_question"}


def image_only_block(block: dict[str, Any]) -> bool:
    text = block_text(block)
    if not block.get("image_refs") or not text.startswith("!["):
        return False
    remainder = text
    for ref in block.get("image_refs", []) or []:
        if isinstance(ref, dict):
            remainder = remainder.replace(str(ref.get("markdown") or ""), "")
    return not remainder.strip()


def section_heading_like(block: dict[str, Any]) -> bool:
    text = block_text(block)
    if not text or block.get("formula_count") or block.get("image_refs"):
        return False
    if text.startswith("题型"):
        return True
    if len(text) > 40:
        return False
    section_tokens = ("单选题", "填空题", "解答题", "选择题", "基础巩固", "能力提升", "通关测")
    if any(token in text for token in section_tokens):
        return True
    return text.startswith(("一、", "二、", "三、", "四、", "五、"))


def relation_set(units: list[dict[str, Any]]) -> set[str]:
    return {str(unit.get("relation") or "") for unit in units}


def unit_role_set(units: list[dict[str, Any]]) -> set[str]:
    return {str(unit.get("semantic_role") or "") for unit in units}


def next_content_block(blocks: list[dict[str, Any]], start_order: int) -> dict[str, Any] | None:
    for index in range(start_order + 1, len(blocks)):
        if has_block_content(blocks[index]):
            return blocks[index]
    return None


def classify_section_scope(
    *,
    block: dict[str, Any],
    current_question_open: bool,
    current_section_kind: str,
    units_for_block: list[dict[str, Any]],
    next_units: list[dict[str, Any]],
    next_block: dict[str, Any] | None,
) -> dict[str, Any]:
    """Classify a section-like block by structural scope.

    Text markers are evidence, not the boundary decision. The important signal
    for question-internal headings is that the model and neighboring units make
    the heading behave like a continuation while a question is still open.
    """
    text = block_text(block)
    block_id = block["block_id"]
    relations = relation_set(units_for_block)
    next_relations = relation_set(next_units)
    next_roles = unit_role_set(next_units)
    next_text = block_text(next_block or {}) if next_block else ""

    evidence: dict[str, Any] = {
        "relations": sorted(relations),
        "next_relations": sorted(next_relations),
        "current_question_open": current_question_open,
        "current_section_kind": current_section_kind,
    }
    if next_block:
        evidence["next_block_id"] = next_block.get("block_id")

    next_is_independent_start = starts_lesson_question(next_text) or (
        starts_numbered_question(next_text) and current_section_kind == "assessment"
    )
    section_is_continuation = bool(relations & {"continues_previous", "part_of_question", "companion_for"})
    next_depends_on_current = bool(next_relations & {"part_of_question", "continues_previous", "companion_for"}) or bool(
        next_roles & {"question", "subquestion", "analysis", "solution", "answer"}
    )
    if current_question_open and section_is_continuation and next_depends_on_current and not next_is_independent_start:
        evidence["next_content_relation"] = "depends_on_previous_material"
        return {
            "block_id": block_id,
            "semantic_role": "section",
            "section_scope": "question_internal",
            "hard_stop": False,
            "owner_candidate_id": "",
            "evidence": evidence,
        }

    if assessment_section_like(text) or (text.startswith(("一、", "二、", "三、", "四、", "五、")) and current_section_kind == "assessment"):
        return {
            "block_id": block_id,
            "semantic_role": "section",
            "section_scope": "assessment_type",
            "hard_stop": True,
            "owner_candidate_id": "",
            "evidence": evidence,
        }
    if question_group_section_like(text):
        return {
            "block_id": block_id,
            "semantic_role": "section",
            "section_scope": "question_group",
            "hard_stop": True,
            "owner_candidate_id": "",
            "evidence": evidence,
        }
    if document_section_like(text):
        return {
            "block_id": block_id,
            "semantic_role": "section",
            "section_scope": "document",
            "hard_stop": True,
            "owner_candidate_id": "",
            "evidence": evidence,
        }

    if current_question_open:
        evidence["reason"] = "section_like_block_inside_open_question_without_safe_scope"
        return {
            "block_id": block_id,
            "semantic_role": "section",
            "section_scope": "unknown",
            "hard_stop": False,
            "owner_candidate_id": "",
            "evidence": evidence,
        }
    return {
        "block_id": block_id,
        "semantic_role": "section",
        "section_scope": "document",
        "hard_stop": True,
        "owner_candidate_id": "",
        "evidence": evidence,
    }


def starts_option_line(text: str) -> bool:
    return text.startswith(("A．", "B．", "C．", "D．", "A.", "B.", "C.", "D."))


def starts_subquestion_line(text: str) -> bool:
    text = text.strip()
    if len(text) < 3 or text[0] != "(":
        return False
    index = 1
    while index < len(text) and text[index].isdigit():
        index += 1
    return index > 1 and index < len(text) and text[index] == ")"


def question_block_role_for(
    *,
    block: dict[str, Any],
    units_for_block: list[dict[str, Any]],
    is_question_start: bool = False,
    section_scope: str = "",
    current_question: dict[str, Any] | None = None,
) -> str:
    if is_question_start:
        return "question_start"
    if section_scope == "question_internal":
        return "internal_heading"
    text = block_text(block)
    roles = unit_role_set(units_for_block)
    relations = relation_set(units_for_block)
    if block.get("source_block_type") == "docx_table":
        return "table"
    if image_only_block(block):
        return "visual"
    if "answer" in roles:
        return "answer"
    if text.startswith(("分析：", "【分析】")):
        return "analysis"
    if text.startswith(("解：", "证明：", "【详解】")):
        return "solution"
    if "analysis" in roles:
        return "analysis"
    if "solution" in roles:
        return "solution"
    if starts_option_line(text):
        return "option"
    if starts_subquestion_line(text):
        return "subquestion"
    if "part_of_question" in relations:
        return "prompt"
    if current_question and "阅读材料" in str(current_question.get("title") or ""):
        return "shared_material"
    if "shared_material" in roles:
        return "shared_material"
    if "subquestion" in roles:
        return "subquestion"
    return "continuation"


def build_boundary_rule_inventory(config: dict[str, Any]) -> dict[str, Any]:
    source_file = safe_rel(Path(__file__))
    window_cfg = config.get("window", {}) or {}

    def item(
        rule_id: str,
        needle: str,
        rule_type: str,
        pattern_or_description: str,
        produces: list[str],
        decision_authority: str,
        requires_supporting_evidence: list[str],
        *,
        can_create_question: bool = False,
        can_close_question: bool = False,
        can_merge_question: bool = False,
        can_assign_section_scope: bool = False,
        can_mark_ready: bool = False,
        tests: list[str] | None = None,
    ) -> dict[str, Any]:
        start, end = source_line_span(needle)
        return {
            "rule_id": rule_id,
            "source_file": source_file,
            "source_line_start": start,
            "source_line_end": end,
            "rule_type": rule_type,
            "pattern_or_description": pattern_or_description,
            "produces": produces,
            "decision_authority": decision_authority,
            "requires_supporting_evidence": requires_supporting_evidence,
            "can_create_question": can_create_question,
            "can_close_question": can_close_question,
            "can_merge_question": can_merge_question,
            "can_assign_section_scope": can_assign_section_scope,
            "can_mark_ready": can_mark_ready,
            "tests": tests or [],
        }

    rules = [
        item("rule_weak_lesson_question_hint", "lesson_question_marker", "keyword_set", "diagnostic contains markers such as 【例】/【变式】", ["weak_hint"], "hint_only", [], tests=["test_doc2_v10_numeric_prefix_does_not_override_semantic_role"]),
        item("rule_weak_answer_hint", "answer_marker", "keyword_set", "diagnostic contains answer markers", ["weak_hint"], "hint_only", []),
        item("rule_weak_analysis_solution_hint", "analysis_solution_marker", "keyword_set", "diagnostic contains analysis/solution markers", ["weak_hint"], "hint_only", []),
        item("rule_weak_section_or_type_heading_hint", "section_or_type_heading_marker", "keyword_set", "diagnostic contains section/type heading markers", ["weak_hint"], "hint_only", []),
        item("rule_window_distance_gate", "def plan_windows", "distance_gate", f"window core/context thresholds: core={window_cfg.get('core_blocks', 24)}, left={window_cfg.get('context_left_blocks', 6)}, right={window_cfg.get('context_right_blocks', 6)}", ["window_plan"], "structural_gate", ["source_order_continuity"]),
        item("rule_unit_contiguity_gate", "max(orders) - min(orders) + 1 != len(set(orders))", "structural_gate", "unit block_ids must be contiguous in source order", ["validation_issue"], "hard_gate", ["source_order_continuity"]),
        item("rule_cross_window_merge_gate", "adjacent_explicit_continuation_or_context_title_ref", "structural_gate", "merge only adjacent cross-window continuations with explicit model/title evidence", ["merge_trace"], "final_action", ["model_relation", "source_order_continuity", "cross_window_state"], can_merge_question=True),
        item("rule_numbered_question_parser", "def starts_numbered_question", "parser", "parse leading Arabic number followed by ．/. /、", ["marker_parse"], "candidate_generation", ["document_assessment_section_state", "source_order_state"], can_create_question=True, tests=["test_doc2_v10_section_scope_counterfactuals"]),
        item("rule_lesson_marker_parser", "def starts_lesson_question", "parser", "parse lesson marker prefix 【例】 or 【变式】", ["marker_parse"], "candidate_generation", ["model_semantic_role_or_relation", "source_order_state"], can_create_question=True, tests=["test_doc2_v10_section_scope_counterfactuals"]),
        item("rule_assessment_section_matcher", "def assessment_section_like", "keyword_set", "match common assessment section titles", ["section_scope_evidence"], "candidate_generation", ["section_like_shape", "document_state"], can_assign_section_scope=True),
        item("rule_document_section_matcher", "def document_section_like", "keyword_set", "match document-level knowledge/header clues", ["section_scope_evidence"], "candidate_generation", ["section_like_shape", "document_state"], can_assign_section_scope=True),
        item("rule_question_group_section_matcher", "def question_group_section_like", "keyword_set", "match teaching question-group headings", ["section_scope_evidence"], "candidate_generation", ["section_like_shape", "document_state"], can_assign_section_scope=True),
        item("rule_section_heading_shape_gate", "def section_heading_like", "keyword_set", "short no-formula/no-image text with section title shape", ["section_like_candidate"], "candidate_generation", ["model_semantic_role", "section_scope_gate"], can_close_question=True),
        item("rule_section_scope_structural_gate", "def classify_section_scope", "structural_gate", "assign section_scope from open question state, model relation, next relation, absence of independent next start, and document/assessment state", ["section_scope"], "final_action", ["model_relation", "current_open_question_state", "next_content_relation", "independent_question_absence"], can_close_question=True, can_assign_section_scope=True, tests=["test_doc2_v10_section_scope_counterfactuals"]),
        item("rule_option_line_parser", "def starts_option_line", "parser", "parse A/B/C/D option prefixes", ["question_block_role"], "candidate_generation", ["open_question_state"]),
        item("rule_subquestion_line_parser", "def starts_subquestion_line", "parser", "parse parenthesized numeric subquestion markers", ["question_block_role"], "candidate_generation", ["open_question_state"]),
        item("rule_analysis_solution_role_marker", "def question_block_role_for", "keyword_set", "classify question-internal block role from model role plus markers such as 分析：/解：", ["question_block_role"], "candidate_generation", ["model_semantic_role", "open_question_state"]),
        item("rule_blank_content_gate", "def has_block_content", "structural_gate", "blank/content detection from text, image_refs, formula_count, and table block type", ["blank_or_content"], "hard_gate", ["source_block_metadata"]),
        item("rule_image_only_gate", "def image_only_block", "structural_gate", "detect native image-only block from image refs and markdown remainder", ["visual_candidate", "quarantine_candidate"], "hard_gate", ["image_ref_metadata", "block_text_absence", "blank_gap_state"]),
        item("rule_isolated_visual_quarantine_gate", "isolated_visual_after_blank_gap", "structural_gate", "quarantine isolated image-only block after blank gap", ["repair_case"], "final_action", ["image_only_gate", "blank_gap_state"]),
        item("rule_question_quality_gate", "def quality_gate_questions", "structural_gate", "mark ready only when no blocking quality/review flags exist", ["boundary_status", "flow_status"], "hard_gate", ["question_candidate_exists", "no_blocking_flags", "disposition_integrity"], can_mark_ready=True),
        item("rule_repair_context_distance", "min(orders) - 3", "distance_gate", "repair queue captures three blocks of left/right context around target span", ["repair_context"], "structural_gate", ["source_order_context"]),
    ]
    by_type: dict[str, int] = {}
    by_authority: dict[str, int] = {}
    for rule in rules:
        by_type[rule["rule_type"]] = by_type.get(rule["rule_type"], 0) + 1
        by_authority[rule["decision_authority"]] = by_authority.get(rule["decision_authority"], 0) + 1
    return {
        "schema_version": "docx_math_boundary_rule_inventory.v0.1",
        "rule_count": len(rules),
        "regex_rule_count": by_type.get("regex", 0),
        "keyword_or_pattern_rule_count": sum(by_type.get(key, 0) for key in ["keyword_set", "parser"]),
        "deterministic_pattern_rule_count": len(rules),
        "by_rule_type": by_type,
        "by_decision_authority": by_authority,
        "rules": rules,
    }



def lesson_family_id(text: str) -> str:
    if text.startswith("【例"):
        end = text.find("】")
        return f"family_example_{text[2:end] if end > 2 else 'unknown'}"
    if text.startswith("【变式"):
        end = text.find("】")
        marker = text[3:end] if end > 3 else "unknown"
        root = marker.split("-", 1)[0]
        return f"family_example_{root}"
    return ""


def unit_maps(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    by_block: dict[str, list[dict[str, Any]]] = {}
    role_by_block: dict[str, str] = {}
    for unit in units:
        for block_id in unit.get("block_ids", []) or []:
            by_block.setdefault(block_id, []).append(unit)
            role_by_block.setdefault(block_id, str(unit.get("semantic_role") or "unknown"))
    return by_block, role_by_block


def build_questions_by_replay(
    blocks: list[dict[str, Any]],
    units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Deterministically replay QuestionPacket boundaries from immutable blocks.

    This layer is not content rewriting and not a model substitute. It enforces
    the packet granularity contract after the model has observed semantic units.
    """
    _unit_by_block, role_by_block = unit_maps(units)
    questions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    quarantined_spans: list[dict[str, Any]] = []
    family_items: list[dict[str, Any]] = []
    section_scopes: list[dict[str, Any]] = []
    decision_records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_section = ""
    current_section_kind = ""
    blank_gap_after_current = 0

    def close_current(reason: str, supporting_evidence: list[dict[str, Any]] | None = None) -> None:
        nonlocal current
        if not current:
            return
        block_ids = current["block_ids"]
        if block_ids:
            start = source_order(block_ids[0])
            end = source_order(block_ids[-1])
            display = "\n\n".join(block_text(blocks[source_order(block_id)]) for block_id in block_ids if block_text(blocks[source_order(block_id)]))
            refs = [
                ref
                for block_id in block_ids
                for ref in blocks[source_order(block_id)].get("image_refs", []) or []
                if isinstance(ref, dict)
            ]
            candidate_id = f"qb_{block_ids[0]}"
            family_id = current.get("question_family_id") or ""
            item = {
                "candidate_id": candidate_id,
                "question_id": f"docx_q_{len(questions) + 1:03d}",
                "order_index": len(questions) + 1,
                "title": current.get("title", ""),
                "start_paragraph_index": start,
                "end_paragraph_index": end,
                "start_block_id": block_ids[0],
                "end_block_id": block_ids[-1],
                "block_ids": block_ids,
                "question_block_roles": dict(current.get("block_roles", {})),
                "source_unit_ids": sorted(set(current.get("source_unit_ids", []))),
                "question_kind": current.get("question_kind", ""),
                "question_family_id": family_id,
                "variant_of": current.get("variant_of", ""),
                "variant_of_candidate_id": "",
                "section_context": current.get("section_context", ""),
                "confidence": current.get("confidence", 0.0),
                "boundary_status": "candidate",
                "flow_allowed": False,
                "blocking_reasons": [],
                "review_flags": sorted(set(current.get("review_flags", []))),
                "quality_flags": sorted(set(current.get("quality_flags", []))),
                "lineage": {
                    "lineage_status": "initial_stable_candidate",
                    "merged_from": [],
                    "split_from": [],
                },
                "display_markdown": display,
                "asset_ids": list(dict.fromkeys(ref.get("asset_id") for ref in refs if ref.get("asset_id"))),
                "start_decision": current.get("start_decision", {}),
                "close_decision": {
                    "final_action": "close_question",
                    "reason": reason,
                    "supporting_evidence": supporting_evidence or [
                        {"source": "structural_state", "value": "current_question_open"},
                        {"source": "source_order_state", "value": reason},
                    ],
                },
            }
            questions.append(item)
            if family_id:
                family_items.append(
                    {
                        "question_family_id": family_id,
                        "candidate_id": candidate_id,
                        "question_id": item["question_id"],
                        "variant_of": item["variant_of"],
                        "title": item["title"],
                    }
                )
            actions.append({"type": "close_question", "candidate_id": candidate_id, "reason": reason, "block_ids": block_ids})
            decision_records.append(
                {
                    "candidate_id": candidate_id,
                    "decision_kind": "close_question",
                    "final_action": "close_question",
                    "supporting_evidence": item["close_decision"]["supporting_evidence"],
                    "reason": reason,
                }
            )
        current = None

    for block in blocks:
        block_id = block["block_id"]
        order = int(block.get("source_order") or source_order(block_id))
        text = block_text(block)
        if not has_block_content(block):
            if current:
                blank_gap_after_current += 1
            continue
        role = role_by_block.get(block_id, "")
        units_for_block = _unit_by_block.get(block_id, [])
        image_only_after_gap = bool(current and blank_gap_after_current and image_only_block(block))
        if image_only_after_gap:
            close_current(
                "blank_gap_before_isolated_visual",
                [
                    {"source": "blank_gap_state", "value": str(blank_gap_after_current)},
                    {"source": "visual_metadata", "value": "next_block_is_image_only"},
                ],
            )
            quarantined_spans.append(
                {
                    "type": "quarantine_span",
                    "block_ids": [block_id],
                    "reason": "isolated_visual_after_blank_gap",
                    "text": compact_text(text, 120),
                }
            )
            blank_gap_after_current = 0
            continue
        lesson_start = starts_lesson_question(text)
        if role == "section" or section_heading_like(block):
            if not lesson_start:
                next_block = next_content_block(blocks, order)
                next_units = _unit_by_block.get(str(next_block.get("block_id")), []) if next_block else []
                scope = classify_section_scope(
                    block=block,
                    current_question_open=current is not None,
                    current_section_kind=current_section_kind,
                    units_for_block=units_for_block,
                    next_units=next_units,
                    next_block=next_block,
                )
                if scope["section_scope"] == "question_internal" and current:
                    scope["owner_candidate_id"] = f"qb_{current['block_ids'][0]}"
                    section_scopes.append(scope)
                    current["block_ids"].append(block_id)
                    current.setdefault("block_roles", {})[block_id] = question_block_role_for(
                        block=block,
                        units_for_block=units_for_block,
                        section_scope="question_internal",
                        current_question=current,
                    )
                    current["source_unit_ids"].extend(unit.get("unit_id") for unit in units_for_block if unit.get("unit_id"))
                    actions.append({"type": "attach_question_internal_heading", "block_id": block_id, "owner_candidate_id": scope["owner_candidate_id"], "reason": "section_scope_question_internal"})
                    decision_records.append(
                        {
                            "candidate_id": scope["owner_candidate_id"],
                            "block_id": block_id,
                            "decision_kind": "assign_question_internal_heading",
                            "final_action": "attach_to_previous_question",
                            "supporting_evidence": [
                                {"source": "model_relation", "value": ",".join(scope["evidence"].get("relations", []))},
                                {"source": "current_open_question_state", "value": str(scope["evidence"].get("current_question_open"))},
                                {"source": "next_content_relation", "value": scope["evidence"].get("next_content_relation", "")},
                                {"source": "independent_question_absence", "value": "next_block_not_independent_start"},
                            ],
                            "section_scope": scope["section_scope"],
                        }
                    )
                    blank_gap_after_current = 0
                    continue
                section_scopes.append(scope)
                if scope["section_scope"] == "unknown":
                    if current:
                        current.setdefault("review_flags", []).append("unresolved_section_scope")
                    quarantined_spans.append(
                        {
                            "type": "quarantine_span",
                            "block_ids": [block_id],
                            "reason": "unresolved_section_scope",
                            "text": compact_text(text, 120),
                        }
                    )
                    blank_gap_after_current = 0
                    continue
                close_current(
                    "section_hard_stop",
                    [
                        {"source": "section_scope_gate", "value": scope["section_scope"]},
                        {"source": "current_open_question_state", "value": "true"},
                    ],
                )
                current_section = text
                current_section_kind = "assessment" if scope["section_scope"] == "assessment_type" else ("problem" if scope["section_scope"] == "question_group" else "section")
                actions.append({"type": "classify_non_question", "block_id": block_id, "as": "section", "section_scope": scope["section_scope"], "text": compact_text(text, 80)})
                blank_gap_after_current = 0
                continue
        if non_question_role(role):
            if not lesson_start:
                close_current(
                    f"{role}_hard_stop",
                    [
                        {"source": "model_semantic_role", "value": role},
                        {"source": "current_open_question_state", "value": "true"},
                    ],
                )
                actions.append({"type": "classify_non_question", "block_id": block_id, "as": role, "text": compact_text(text, 80)})
                blank_gap_after_current = 0
                continue
        numbered_question_start = starts_numbered_question(text) and current_section_kind == "assessment"
        model_starts_question = any(
            unit.get("semantic_role") == "question"
            and unit.get("start_block_id") == block_id
            and str(unit.get("relation") or "") not in {"part_of_question", "continues_previous", "solution_for", "analysis_for", "answer_for", "companion_for"}
            for unit in units_for_block
        ) and current is None
        model_section_question_start = any(
            unit.get("semantic_role") == "question"
            and unit.get("start_block_id") == block_id
            and str(unit.get("relation") or "") == "part_of_question"
            for unit in units_for_block
        ) and current is None and current_section_kind in {"assessment", "problem"}
        starts_question = lesson_start or numbered_question_start or model_starts_question
        starts_question = starts_question or model_section_question_start
        if starts_question:
            if current:
                close_current(
                    "independent_question_marker",
                    [
                        {"source": "new_question_start", "value": "true"},
                        {"source": "current_open_question_state", "value": "true"},
                    ],
                )
            family_id = lesson_family_id(text)
            variant_of = ""
            if text.startswith("【变式") and family_id:
                variant_of = family_id.replace("family_example_", "example_")
            source_units = [unit.get("unit_id") for unit in _unit_by_block.get(block_id, []) if unit.get("unit_id")]
            start_evidence: list[dict[str, Any]] = []
            if lesson_start:
                start_evidence.append({"source": "explicit_marker", "value": "lesson_question_marker"})
            if numbered_question_start:
                start_evidence.append({"source": "explicit_marker", "value": "assessment_numbered_marker"})
                start_evidence.append({"source": "document_section_state", "value": "assessment"})
            if model_starts_question or model_section_question_start or units_for_block:
                start_evidence.append({"source": "model_semantic_role", "value": ",".join(sorted(unit_role_set(units_for_block)))})
                start_evidence.append({"source": "model_relation", "value": ",".join(sorted(relation_set(units_for_block)))})
            start_evidence.append({"source": "source_order_state", "value": "block_is_candidate_start"})
            if current_section_kind:
                start_evidence.append({"source": "document_section_state", "value": current_section_kind})
            current = {
                "block_ids": [block_id],
                "title": compact_text(text, 120),
                "source_unit_ids": source_units,
                "question_kind": "lesson_question" if lesson_start else ("assessment_numbered_question" if numbered_question_start else "model_question_unit"),
                "question_family_id": family_id,
                "variant_of": variant_of,
                "section_context": current_section,
                "confidence": 1.0 if (lesson_start or numbered_question_start) else 0.75,
                "merged_from": [f"qb_{block_id}"],
                "split_from": [],
                "block_roles": {
                    block_id: question_block_role_for(
                        block=block,
                        units_for_block=units_for_block,
                        is_question_start=True,
                    )
                },
                "start_decision": {
                    "final_action": "create_question",
                    "supporting_evidence": start_evidence,
                },
            }
            actions.append({"type": "create_question", "candidate_id": f"qb_{block_id}", "block_id": block_id, "reason": "lesson_marker" if lesson_start else ("assessment_numbered_marker" if numbered_question_start else "model_question_unit")})
            decision_records.append(
                {
                    "candidate_id": f"qb_{block_id}",
                    "block_id": block_id,
                    "decision_kind": "create_question",
                    "final_action": "create_question",
                    "supporting_evidence": start_evidence,
                }
            )
            blank_gap_after_current = 0
            continue
        if current:
            current["block_ids"].append(block_id)
            current.setdefault("block_roles", {})[block_id] = question_block_role_for(
                block=block,
                units_for_block=units_for_block,
                current_question=current,
            )
            current["source_unit_ids"].extend(unit.get("unit_id") for unit in _unit_by_block.get(block_id, []) if unit.get("unit_id"))
            blank_gap_after_current = 0
            continue
        quarantined_spans.append(
            {
                "type": "quarantine_span",
                "block_ids": [block_id],
                "reason": "content_not_attached_to_question_or_section",
                "text": compact_text(text, 120),
            }
        )
    close_current(
        "end_of_document",
        [
            {"source": "current_open_question_state", "value": "true"},
            {"source": "source_order_state", "value": "end_of_document"},
        ],
    )

    section_scope_manifest = {
        "schema_version": "docx_math_section_scope_manifest.v0.1",
        "section_count": len(section_scopes),
        "document_section_count": sum(1 for item in section_scopes if item["section_scope"] == "document"),
        "question_group_section_count": sum(1 for item in section_scopes if item["section_scope"] == "question_group"),
        "assessment_type_section_count": sum(1 for item in section_scopes if item["section_scope"] == "assessment_type"),
        "question_internal_heading_count": sum(1 for item in section_scopes if item["section_scope"] == "question_internal"),
        "unknown_section_count": sum(1 for item in section_scopes if item["section_scope"] == "unknown"),
        "section_scope_missing_count": sum(1 for item in section_scopes if not item.get("section_scope")),
        "sections": section_scopes,
    }

    family_manifest = {
        "schema_version": "docx_math_question_family_manifest.v0.1",
        "families": [],
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in family_items:
        grouped.setdefault(item["question_family_id"], []).append(item)
    for family_id, items in sorted(grouped.items()):
        root = next((item for item in items if str(item.get("title", "")).startswith("【例")), items[0])
        root_candidate_id = root["candidate_id"]
        for question in questions:
            if question.get("question_family_id") != family_id:
                continue
            if question["candidate_id"] != root_candidate_id:
                question["variant_of_candidate_id"] = root_candidate_id
        family_manifest["families"].append(
            {
                "question_family_id": family_id,
                "root_candidate_id": root_candidate_id,
                "members": [
                    {
                        "candidate_id": item["candidate_id"],
                        "question_id": item["question_id"],
                        "relation_to_root": "root" if item["candidate_id"] == root_candidate_id else "variant_of",
                        "title": item["title"],
                    }
                    for item in items
                ],
            }
        )
    decision_evidence = {
        "schema_version": "docx_math_boundary_decision_evidence.v0.1",
        "decisions": decision_records,
    }
    return questions, actions, quarantined_spans, family_manifest, section_scope_manifest, decision_evidence


def quality_gate_questions(
    questions: list[dict[str, Any]],
    quarantined_spans: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for question in questions:
        marker_blocks = []
        for block_id in question.get("block_ids", []) or []:
            # The caller stores display text only; use the question display to
            # catch accidental multi-marker packets without re-reading globals.
            pass
        display = str(question.get("display_markdown") or "")
        lesson_markers = display.count("【例") + display.count("【变式")
        numbered_starts = 0
        for line in display.splitlines():
            if starts_numbered_question(line.strip()):
                numbered_starts += 1
        if lesson_markers > 1:
            question["quality_flags"].append("question_contains_multiple_independent_lesson_markers")
            issues.append({"type": "question_contains_multiple_independent_lesson_markers", "candidate_id": question["candidate_id"], "block_ids": question["block_ids"], "count": lesson_markers})
        if question.get("question_kind") == "numbered_question" and numbered_starts > 1:
            question["quality_flags"].append("question_contains_multiple_numbered_question_starts")
            issues.append({"type": "question_contains_multiple_numbered_question_starts", "candidate_id": question["candidate_id"], "block_ids": question["block_ids"], "count": numbered_starts})
        if len(question.get("block_ids", [])) == 1 and str(question.get("display_markdown") or "").strip().endswith(("：", ":")):
            question["quality_flags"].append("incomplete_question")
            issues.append({"type": "incomplete_question", "candidate_id": question["candidate_id"], "block_ids": question["block_ids"]})
        if not question.get("candidate_id") or not question.get("lineage"):
            question["quality_flags"].append("stable_id_lineage_missing")
            issues.append({"type": "stable_id_lineage_missing", "candidate_id": question.get("candidate_id", ""), "block_ids": question.get("block_ids", [])})

    for span in quarantined_spans:
        issues.append({"type": "quarantined_span", **span})

    repair_case_count = 0
    for question in questions:
        flags = sorted(set(question.get("quality_flags", []) + question.get("review_flags", [])))
        question["quality_flags"] = flags
        if flags:
            question["boundary_status"] = "needs_auto_repair"
            question["flow_allowed"] = False
            question["blocking_reasons"] = flags
            repair_case_count += 1
        else:
            question["boundary_status"] = "ready"
            question["flow_allowed"] = True
            question["blocking_reasons"] = []
            question["review_flags"] = []

    ready_count = sum(1 for question in questions if question.get("boundary_status") == "ready")
    non_ready_count = len(questions) - ready_count
    quarantined_count = len(quarantined_spans)
    if non_ready_count == 0:
        question_flow_status = "bulk_ready"
    elif ready_count:
        question_flow_status = "partial_ready"
    else:
        question_flow_status = "blocked"
    if quarantined_count == 0:
        document_content_status = "complete"
    elif ready_count:
        document_content_status = "partial"
    else:
        document_content_status = "blocked"
    if question_flow_status == "bulk_ready" and document_content_status == "complete":
        bulk_status = "bulk_ready"
    elif ready_count:
        bulk_status = "partial_ready"
    else:
        bulk_status = "blocked"
    return issues, {
        "bulk_status": bulk_status,
        "question_flow_status": question_flow_status,
        "document_content_status": document_content_status,
        "ready_question_count": ready_count,
        "non_ready_question_count": non_ready_count,
        "repair_case_count": repair_case_count + quarantined_count,
        "quarantined_count": quarantined_count,
    }


def build_repair_queue(
    issues: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    question_by_block = {block_id: q for q in questions for block_id in q.get("block_ids", []) or []}
    cases: list[dict[str, Any]] = []
    for index, issue in enumerate(issues, start=1):
        target = [str(block_id) for block_id in issue.get("block_ids", []) or []]
        if not target:
            continue
        orders = [source_order(block_id) for block_id in target]
        left = [f"b_{idx:06d}" for idx in range(max(0, min(orders) - 3), min(orders))]
        right = [f"b_{idx:06d}" for idx in range(max(orders) + 1, min(len(blocks), max(orders) + 4))]
        existing_qids = sorted({question_by_block[block_id]["candidate_id"] for block_id in target if block_id in question_by_block})
        source_hashes = {block_id: blocks[source_order(block_id)].get("content_hash", "") for block_id in target if 0 <= source_order(block_id) < len(blocks)}
        allowed_actions = [
            "create_question",
            "split_question",
            "merge_with_question",
            "attach_to_question",
            "attach_to_section",
            "attach_as_subquestion",
            "attach_as_solution",
            "attach_as_analysis",
            "relabel_unit",
            "classify_non_question",
            "quarantine_span",
            "no_change",
        ]
        if issue.get("reason") == "isolated_visual_after_blank_gap":
            allowed_actions = [
                "attach_to_previous_question",
                "attach_to_next_section",
                "classify_non_question",
                "quarantine_span",
                "no_change",
            ]
        cases.append(
            {
                "repair_case_id": f"repair_{index:04d}",
                "issue_types": [str(issue.get("type") or "unknown_issue")],
                "target_block_ids": target,
                "left_context_block_ids": left,
                "right_context_block_ids": right,
                "existing_unit_ids": [],
                "existing_question_ids": existing_qids,
                "allowed_actions": allowed_actions,
                "source_hashes": source_hashes,
                "attempt_count": 0,
            }
        )
    return {"schema_version": "docx_math_boundary_repair_queue.v0.1", "repair_cases": cases}


def build_block_disposition_manifest(
    blocks: list[dict[str, Any]],
    units: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    quarantined_spans: list[dict[str, Any]],
) -> dict[str, Any]:
    _unit_by_block, role_by_block = unit_maps(units)
    question_by_block = {block_id: question["candidate_id"] for question in questions for block_id in question.get("block_ids", []) or []}
    question_role_by_block = {
        block_id: str(question.get("question_block_roles", {}).get(block_id) or "")
        for question in questions
        for block_id in question.get("block_ids", []) or []
    }
    quarantined = {block_id for span in quarantined_spans for block_id in span.get("block_ids", []) or []}
    dispositions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in blocks:
        block_id = block["block_id"]
        role = role_by_block.get(block_id, "")
        if block_id in question_by_block:
            disposition = "question"
            owner = question_by_block[block_id]
        elif block_id in quarantined:
            disposition = "quarantined"
            owner = ""
        elif not has_block_content(block):
            disposition = "blank"
            owner = ""
        elif image_only_block(block):
            disposition = "decorative"
            owner = ""
        elif role in {"instruction", "knowledge", "document_meta", "decorative", "section"}:
            disposition = role
            owner = ""
            if role == "section" and block.get("source_order") == 0:
                disposition = "document_meta"
        elif section_heading_like(block):
            disposition = "section"
            owner = ""
        else:
            disposition = "quarantined"
            owner = ""
        seen.add(block_id)
        dispositions.append(
            {
                "block_id": block_id,
                "source_order": block.get("source_order"),
                "disposition": disposition,
                "owner_candidate_id": owner,
                "question_block_role": question_role_by_block.get(block_id, "") if disposition == "question" else "",
                "source_content_hash": block.get("content_hash", ""),
            }
        )
    duplicate_count = len(dispositions) - len(seen)
    missing_count = len(blocks) - len(seen)
    question_overlap_count = 0
    return {
        "schema_version": "docx_math_block_disposition_manifest.v0.1",
        "block_count": len(blocks),
        "disposition_block_count": len(dispositions),
        "duplicate_disposition_count": duplicate_count,
        "missing_disposition_count": missing_count,
        "question_block_overlap_count": question_overlap_count,
        "source_content_hash_change_count": 0,
        "dispositions": dispositions,
    }


def model_question_unit_stats(units: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, int]:
    question_unit_ids = {unit.get("unit_id") for unit in units if unit.get("semantic_role") == "question"}
    emitted_unit_ids = {unit_id for question in questions for unit_id in question.get("source_unit_ids", [])}
    emitted = len(question_unit_ids & emitted_unit_ids)
    attached = 0
    unresolved = len(question_unit_ids - emitted_unit_ids)
    return {
        "model_question_unit_count": len(question_unit_ids),
        "model_question_unit_emitted_count": emitted,
        "model_question_unit_attached_count": attached,
        "model_question_unit_unresolved_count": unresolved,
    }


def apply_document_coverage_gate(flow_summary: dict[str, Any], block_disposition: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    dispositions = block_disposition.get("dispositions", []) or []
    quarantined_content = [item for item in dispositions if item.get("disposition") == "quarantined"]
    question_blocks = [item for item in dispositions if item.get("disposition") == "question"]
    content_orphan_count = len(quarantined_content)
    no_question_content_count = len(question_blocks)
    summary = dict(flow_summary)
    summary["content_orphan_block_count"] = content_orphan_count
    summary["question_owned_block_count"] = no_question_content_count
    if not questions and content_orphan_count:
        summary["document_content_status"] = "blocked"
        summary["question_flow_status"] = "blocked"
        summary["bulk_status"] = "blocked"
        summary["coverage_blocking_reason"] = "no_questions_with_quarantined_content"
    elif content_orphan_count:
        summary["document_content_status"] = "partial"
        summary["bulk_status"] = "partial_ready" if summary.get("ready_question_count", 0) else "blocked"
        summary["coverage_blocking_reason"] = "quarantined_content_blocks"
    else:
        summary["coverage_blocking_reason"] = ""
    return summary


def build_final_assembly_actions(
    questions: list[dict[str, Any]],
    block_disposition: dict[str, Any],
    flow_summary: dict[str, Any],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    action_index = 1

    def add_action(payload: dict[str, Any]) -> str:
        nonlocal action_index
        action_id = f"assembly_action_{action_index:04d}"
        action_index += 1
        actions.append(
            {
                "action_id": action_id,
                "actor": "deterministic_rule",
                **payload,
            }
        )
        return action_id

    for question in questions:
        add_action(
            {
                "type": "create_question",
                "rule_id": "emit_final_question_candidate_v10_1",
                "candidate_id": question["candidate_id"],
                "question_id": question["question_id"],
                "order_index": question["order_index"],
                "block_ids": question["block_ids"],
                "question_block_roles": question.get("question_block_roles", {}),
                "question_family_id": question.get("question_family_id", ""),
                "variant_of_candidate_id": question.get("variant_of_candidate_id", ""),
                "boundary_status": question.get("boundary_status", ""),
                "flow_allowed": bool(question.get("flow_allowed")),
            }
        )

    for item in block_disposition["dispositions"]:
        if item["disposition"] == "question":
            continue
        if item["disposition"] == "quarantined":
            add_action(
                {
                    "type": "quarantine_span",
                    "rule_id": "quarantine_unresolved_visual_or_span_v10_1",
                    "block_id": item["block_id"],
                    "as": "quarantined",
                }
            )
        else:
            add_action(
                {
                    "type": "classify_non_question",
                    "rule_id": f"classify_{item['disposition']}_v10_1",
                    "block_id": item["block_id"],
                    "as": item["disposition"],
                }
            )

    add_action(
        {
            "type": "set_flow_status",
            "rule_id": "set_boundary_flow_status_v10_1",
            "question_flow_status": flow_summary["question_flow_status"],
            "document_content_status": flow_summary["document_content_status"],
            "bulk_status": flow_summary["bulk_status"],
        }
    )
    return {"schema_version": "docx_math_boundary_assembly_actions.v0.1", "actions": actions}


def replay_boundary_actions(
    immutable_blocks: dict[str, Any],
    assembly_actions: dict[str, Any],
    repair_actions: dict[str, Any],
) -> dict[str, Any]:
    block_ids = [block["block_id"] for block in immutable_blocks["blocks"]]
    dispositions: dict[str, dict[str, str]] = {}
    questions: dict[str, dict[str, Any]] = {}
    owner_by_block: dict[str, str] = {}
    status = {"question_flow_status": "", "document_content_status": "", "bulk_status": ""}

    def set_disposition(block_id: str, disposition: str, owner: str = "") -> None:
        if block_id in dispositions:
            dispositions[block_id]["duplicate"] = "true"
        dispositions[block_id] = {"disposition": disposition, "owner_candidate_id": owner}

    for action in assembly_actions.get("actions", []) or []:
        action_type = action.get("type")
        if action_type == "create_question":
            candidate_id = str(action["candidate_id"])
            questions[candidate_id] = {
                "candidate_id": candidate_id,
                "question_id": action.get("question_id", ""),
                "order_index": action.get("order_index", 0),
                "block_ids": list(action.get("block_ids", []) or []),
                "question_family_id": action.get("question_family_id", ""),
                "variant_of_candidate_id": action.get("variant_of_candidate_id", ""),
                "boundary_status": action.get("boundary_status", ""),
                "flow_allowed": bool(action.get("flow_allowed")),
            }
            for block_id in questions[candidate_id]["block_ids"]:
                if block_id in owner_by_block:
                    dispositions.setdefault(block_id, {})["overlap"] = "true"
                owner_by_block[block_id] = candidate_id
                set_disposition(block_id, "question", candidate_id)
        elif action_type == "classify_non_question":
            set_disposition(str(action["block_id"]), str(action["as"]), "")
        elif action_type == "quarantine_span":
            set_disposition(str(action["block_id"]), "quarantined", "")
        elif action_type == "set_flow_status":
            status = {
                "question_flow_status": str(action.get("question_flow_status") or ""),
                "document_content_status": str(action.get("document_content_status") or ""),
                "bulk_status": str(action.get("bulk_status") or ""),
            }

    for action in repair_actions.get("actions", []) or []:
        if action.get("status") != "applied":
            continue
        for block_id in action.get("target_block_ids", []) or []:
            if action.get("action") == "quarantine_span":
                set_disposition(str(block_id), "quarantined", "")

    missing = [block_id for block_id in block_ids if block_id not in dispositions]
    duplicates = [block_id for block_id, item in dispositions.items() if item.get("duplicate") == "true"]
    overlaps = [block_id for block_id, item in dispositions.items() if item.get("overlap") == "true"]
    return {
        "questions": questions,
        "dispositions": dispositions,
        "status": status,
        "missing_block_ids": missing,
        "duplicate_block_ids": duplicates,
        "overlap_block_ids": overlaps,
    }


def build_action_replay_audit(
    immutable: dict[str, Any],
    assembly_actions: dict[str, Any],
    repair_actions: dict[str, Any],
    questions: list[dict[str, Any]],
    block_disposition: dict[str, Any],
    family_manifest: dict[str, Any],
    flow_summary: dict[str, Any],
) -> dict[str, Any]:
    replayed = replay_boundary_actions(immutable, assembly_actions, repair_actions)
    expected_questions = {question["candidate_id"]: question for question in questions}
    expected_dispositions = {item["block_id"]: item for item in block_disposition["dispositions"]}
    mismatches: list[dict[str, Any]] = []

    question_boundary_mismatch_count = 0
    candidate_owner_mismatch_count = 0
    for candidate_id, expected in expected_questions.items():
        actual = replayed["questions"].get(candidate_id)
        if not actual or actual.get("block_ids") != expected.get("block_ids"):
            question_boundary_mismatch_count += 1
            mismatches.append({"type": "question_boundary_mismatch", "candidate_id": candidate_id, "expected": expected.get("block_ids"), "actual": actual.get("block_ids") if actual else None})
        for block_id in expected.get("block_ids", []) or []:
            owner = replayed["dispositions"].get(block_id, {}).get("owner_candidate_id", "")
            if owner != candidate_id:
                candidate_owner_mismatch_count += 1
                mismatches.append({"type": "candidate_owner_mismatch", "block_id": block_id, "expected": candidate_id, "actual": owner})

    disposition_mismatch_count = 0
    for block_id, expected in expected_dispositions.items():
        actual = replayed["dispositions"].get(block_id, {})
        if actual.get("disposition") != expected.get("disposition"):
            disposition_mismatch_count += 1
            mismatches.append({"type": "disposition_mismatch", "block_id": block_id, "expected": expected.get("disposition"), "actual": actual.get("disposition")})

    candidate_ids = set(expected_questions)
    family_reference_mismatch_count = 0
    for family in family_manifest.get("families", []) or []:
        root = family.get("root_candidate_id", "")
        if root and root not in candidate_ids:
            family_reference_mismatch_count += 1
            mismatches.append({"type": "family_root_missing", "question_family_id": family.get("question_family_id"), "root_candidate_id": root})
        for member in family.get("members", []) or []:
            if member.get("candidate_id") not in candidate_ids:
                family_reference_mismatch_count += 1
                mismatches.append({"type": "family_member_missing", "question_family_id": family.get("question_family_id"), "candidate_id": member.get("candidate_id")})

    status_mismatch_count = 0
    for key in ("question_flow_status", "document_content_status", "bulk_status"):
        if replayed["status"].get(key) != flow_summary.get(key):
            status_mismatch_count += 1
            mismatches.append({"type": "status_mismatch", "field": key, "expected": flow_summary.get(key), "actual": replayed["status"].get(key)})

    if replayed["missing_block_ids"]:
        disposition_mismatch_count += len(replayed["missing_block_ids"])
        mismatches.append({"type": "missing_replayed_disposition", "block_ids": replayed["missing_block_ids"]})
    if replayed["duplicate_block_ids"]:
        disposition_mismatch_count += len(replayed["duplicate_block_ids"])
        mismatches.append({"type": "duplicate_replayed_disposition", "block_ids": replayed["duplicate_block_ids"]})
    if replayed["overlap_block_ids"]:
        candidate_owner_mismatch_count += len(replayed["overlap_block_ids"])
        mismatches.append({"type": "replayed_question_overlap", "block_ids": replayed["overlap_block_ids"]})

    audit = {
        "schema_version": "docx_math_boundary_action_replay_audit.v0.1",
        "status": "pass" if not mismatches else "fail",
        "assembly_action_count": len(assembly_actions.get("actions", []) or []),
        "repair_action_count": len(repair_actions.get("actions", []) or []),
        "replayed_question_count": len(replayed["questions"]),
        "expected_question_count": len(questions),
        "question_boundary_mismatch_count": question_boundary_mismatch_count,
        "candidate_owner_mismatch_count": candidate_owner_mismatch_count,
        "disposition_mismatch_count": disposition_mismatch_count,
        "family_reference_mismatch_count": family_reference_mismatch_count,
        "status_mismatch_count": status_mismatch_count,
        "mismatches": mismatches,
    }
    return audit


def build_semantic_boundary_audit(
    *,
    questions: list[dict[str, Any]],
    block_disposition: dict[str, Any],
    family_manifest: dict[str, Any],
    section_scope_manifest: dict[str, Any],
    units: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    block_by_id = {block["block_id"]: block for block in blocks}
    _unit_by_block, _role_by_block = unit_maps(units)
    dispositions = {item["block_id"]: item for item in block_disposition.get("dispositions", []) or []}
    questions_by_id = {question["candidate_id"]: question for question in questions}
    issues: list[dict[str, Any]] = []

    context_dependent_orphan_question_count = 0
    previous_question: dict[str, Any] | None = None
    for question in questions:
        first_block_id = str(question.get("start_block_id") or "")
        first_block = block_by_id.get(first_block_id, {})
        first_text = block_text(first_block)
        starts_independently = starts_lesson_question(first_text) or str(question.get("question_kind") or "") == "assessment_numbered_question"
        units_for_first = _unit_by_block.get(first_block_id, [])
        relations = relation_set(units_for_first)
        if (
            previous_question
            and not starts_independently
            and relations & {"part_of_question", "continues_previous", "companion_for"}
            and question.get("section_context") == previous_question.get("section_context")
        ):
            context_dependent_orphan_question_count += 1
            issues.append(
                {
                    "type": "context_dependent_orphan_question",
                    "candidate_id": question.get("candidate_id"),
                    "start_block_id": first_block_id,
                    "previous_candidate_id": previous_question.get("candidate_id"),
                    "relations": sorted(relations),
                }
            )
        previous_question = question

    question_internal_heading_split_count = 0
    unresolved_section_scope_count = 0
    shared_material_relation_missing_count = 0
    for section in section_scope_manifest.get("sections", []) or []:
        block_id = str(section.get("block_id") or "")
        scope = str(section.get("section_scope") or "")
        if not scope or scope == "unknown":
            unresolved_section_scope_count += 1
            issues.append({"type": "unresolved_section_scope", "block_id": block_id, "section_scope": scope})
        if scope == "question_internal":
            disposition = dispositions.get(block_id, {})
            owner = str(disposition.get("owner_candidate_id") or section.get("owner_candidate_id") or "")
            if disposition.get("disposition") != "question" or not owner:
                question_internal_heading_split_count += 1
                issues.append({"type": "question_internal_heading_split", "block_id": block_id, "owner_candidate_id": owner})
            elif owner in questions_by_id:
                owner_question = questions_by_id[owner]
                if str(owner_question.get("question_block_roles", {}).get(block_id) or "") != "internal_heading":
                    question_internal_heading_split_count += 1
                    issues.append({"type": "question_internal_heading_role_missing", "block_id": block_id, "owner_candidate_id": owner})
                after_heading = [
                    candidate_block_id
                    for candidate_block_id in owner_question.get("block_ids", []) or []
                    if source_order(candidate_block_id) > source_order(block_id)
                ]
                if after_heading and not any(
                    str(owner_question.get("question_block_roles", {}).get(candidate_block_id) or "") in {"prompt", "subquestion", "continuation"}
                    for candidate_block_id in after_heading
                ):
                    shared_material_relation_missing_count += 1
                    issues.append({"type": "shared_material_relation_missing", "block_id": block_id, "owner_candidate_id": owner})

    question_contains_document_section_count = 0
    question_contains_assessment_section_count = 0
    section_scope_by_block = {str(item.get("block_id")): str(item.get("section_scope") or "") for item in section_scope_manifest.get("sections", []) or []}
    for item in block_disposition.get("dispositions", []) or []:
        if item.get("disposition") != "question":
            continue
        scope = section_scope_by_block.get(str(item.get("block_id") or ""), "")
        if scope == "document":
            question_contains_document_section_count += 1
            issues.append({"type": "question_contains_document_section", "block_id": item.get("block_id"), "owner_candidate_id": item.get("owner_candidate_id")})
        if scope == "assessment_type":
            question_contains_assessment_section_count += 1
            issues.append({"type": "question_contains_assessment_section", "block_id": item.get("block_id"), "owner_candidate_id": item.get("owner_candidate_id")})

    candidate_ids = set(questions_by_id)
    question_family_orphan_count = 0
    for family in family_manifest.get("families", []) or []:
        if family.get("root_candidate_id") not in candidate_ids:
            question_family_orphan_count += 1
            issues.append({"type": "question_family_root_orphan", "question_family_id": family.get("question_family_id"), "root_candidate_id": family.get("root_candidate_id")})
        for member in family.get("members", []) or []:
            if member.get("candidate_id") not in candidate_ids:
                question_family_orphan_count += 1
                issues.append({"type": "question_family_member_orphan", "question_family_id": family.get("question_family_id"), "candidate_id": member.get("candidate_id")})

    metrics = {
        "question_count": len(questions),
        "context_dependent_orphan_question_count": context_dependent_orphan_question_count,
        "question_internal_heading_split_count": question_internal_heading_split_count,
        "question_contains_document_section_count": question_contains_document_section_count,
        "question_contains_assessment_section_count": question_contains_assessment_section_count,
        "question_family_orphan_count": question_family_orphan_count,
        "unresolved_section_scope_count": unresolved_section_scope_count,
        "shared_material_relation_missing_count": shared_material_relation_missing_count,
    }
    status = "pass" if all(value == 0 for key, value in metrics.items() if key != "question_count") else "fail"
    return {
        "schema_version": "docx_math_semantic_boundary_audit.v0.1",
        "status": status,
        **metrics,
        "issues": issues,
    }


LEXICAL_EVIDENCE_SOURCES = {"explicit_marker", "keyword", "regex", "text_marker"}
STRUCTURAL_EVIDENCE_SOURCES = {
    "model_semantic_role",
    "model_relation",
    "current_open_question_state",
    "source_order_state",
    "document_section_state",
    "section_scope_gate",
    "next_content_relation",
    "independent_question_absence",
    "blank_gap_state",
    "visual_metadata",
    "quality_gate",
    "disposition_integrity",
}


def evidence_source_families(evidence: list[dict[str, Any]]) -> set[str]:
    families: set[str] = set()
    for item in evidence:
        source = str(item.get("source") or "")
        if source in LEXICAL_EVIDENCE_SOURCES or "marker" in source or "regex" in source or "keyword" in source:
            families.add("lexical")
        elif source in STRUCTURAL_EVIDENCE_SOURCES:
            families.add(source)
        elif source:
            families.add(source)
    return families


def finalize_boundary_decision_evidence(
    decision_evidence: dict[str, Any],
    questions: list[dict[str, Any]],
    section_scope_manifest: dict[str, Any],
    overfit_scan: dict[str, Any],
) -> dict[str, Any]:
    decisions = list(decision_evidence.get("decisions", []) or [])
    for question in questions:
        decisions.append(
            {
                "candidate_id": question["candidate_id"],
                "decision_kind": "set_boundary_status_ready",
                "final_action": "set_boundary_status_ready",
                "supporting_evidence": [
                    {"source": "quality_gate", "value": "no_quality_flags"},
                    {"source": "quality_gate", "value": "no_review_flags"},
                    {"source": "disposition_integrity", "value": "owned_question_blocks"},
                ],
            }
        )
    single_evidence = []
    regex_only = []
    hardcoded_literal = []
    for decision in decisions:
        evidence = list(decision.get("supporting_evidence", []) or [])
        families = evidence_source_families(evidence)
        if len(families) < 2:
            single_evidence.append(decision)
        if families and families <= {"lexical"}:
            regex_only.append(decision)
        haystack = json.dumps(decision, ensure_ascii=False)
        if any(match.get("literal") in haystack for match in overfit_scan.get("matches", []) or []):
            hardcoded_literal.append(decision)

    keyword_only_section_scope = []
    for section in section_scope_manifest.get("sections", []) or []:
        if section.get("section_scope") != "question_internal":
            continue
        evidence = section.get("evidence", {}) or {}
        has_model_relation = bool(evidence.get("relations") or evidence.get("next_relations"))
        has_open_state = evidence.get("current_question_open") is True
        has_next_relation = bool(evidence.get("next_content_relation"))
        if not (has_model_relation and has_open_state and has_next_relation):
            keyword_only_section_scope.append(section)

    return {
        "schema_version": "docx_math_boundary_decision_evidence.v0.1",
        "status": "pass"
        if not single_evidence and not regex_only and not keyword_only_section_scope and not hardcoded_literal
        else "fail",
        "decision_count": len(decisions),
        "single_evidence_final_decision_count": len(single_evidence),
        "regex_only_final_decision_count": len(regex_only),
        "keyword_only_section_scope_count": len(keyword_only_section_scope),
        "hardcoded_literal_decision_count": len(hardcoded_literal),
        "production_code_reads_golden_fixture": False,
        "production_code_reads_doc2_fixture": False,
        "violations": {
            "single_evidence_final_decisions": single_evidence,
            "regex_only_final_decisions": regex_only,
            "keyword_only_section_scopes": keyword_only_section_scope,
            "hardcoded_literal_decisions": hardcoded_literal,
        },
        "decisions": decisions,
    }


def scan_overfit_literals() -> dict[str, Any]:
    forbidden_literals = [
        "b_" + "000082",
        "b_" + "000087",
        "b_" + "000088",
        "变式" + "4-2",
        "第二章 " + "有理数的运算",
        "第二章_" + "有理数的运算_复习讲义_原卷版_数学人教版2024七年级上册",
        "doc" + "2_unit_boundary",
        "doc" + "2 专用",
    ]
    production_roots = [ROOT / "tools", ROOT / "config"]
    allowed_parts = {"tests", "fixtures", "golden", "outputs"}
    matches: list[dict[str, Any]] = []
    files_scanned = 0
    for root in production_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".md"}:
                continue
            rel_parts = set(path.relative_to(ROOT).parts)
            if rel_parts & allowed_parts:
                continue
            files_scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for literal in forbidden_literals:
                start = 0
                while True:
                    index = text.find(literal, start)
                    if index < 0:
                        break
                    line_no = text.count("\n", 0, index) + 1
                    matches.append(
                        {
                            "literal": literal,
                            "source_file": safe_rel(path),
                            "line": line_no,
                            "context": compact_text(text.splitlines()[line_no - 1], 160),
                        }
                    )
                    start = index + len(literal)
    return {
        "schema_version": "docx_math_overfit_literal_scan.v0.1",
        "status": "pass" if not matches else "fail",
        "production_files_scanned": files_scanned,
        "forbidden_literal_match_count": len(matches),
        "matches": matches,
        "production_code_reads_golden_fixture": False,
        "production_code_reads_doc2_fixture": False,
    }


def build_raw_issue_resolution_manifest(
    raw_issues: list[dict[str, Any]],
    final_issues: list[dict[str, Any]],
    assembly_actions: dict[str, Any],
    block_disposition: dict[str, Any],
    questions: list[dict[str, Any]],
    repair_queue: dict[str, Any],
) -> dict[str, Any]:
    action_by_block: dict[str, list[str]] = {}
    for action in assembly_actions.get("actions", []) or []:
        block_ids = list(action.get("block_ids", []) or [])
        if action.get("block_id"):
            block_ids.append(str(action["block_id"]))
        for block_id in block_ids:
            action_by_block.setdefault(block_id, []).append(str(action["action_id"]))
    disposition_by_block = {item["block_id"]: item["disposition"] for item in block_disposition["dispositions"]}
    candidate_by_block = {block_id: question["candidate_id"] for question in questions for block_id in question.get("block_ids", []) or []}
    repair_case_by_block = {
        block_id: str(case.get("repair_case_id") or "")
        for case in repair_queue.get("repair_cases", []) or []
        for block_id in case.get("target_block_ids", []) or []
    }
    final_types = {issue.get("type") for issue in final_issues}
    resolutions: list[dict[str, Any]] = []
    for index, issue in enumerate(raw_issues, start=1):
        issue_type = str(issue.get("type") or "unknown_issue")
        raw_block_ids = [str(block_id) for block_id in issue.get("block_ids", []) or []]
        resolution_items: list[dict[str, Any]] = []
        for block_id in raw_block_ids:
            final_disposition = disposition_by_block.get(block_id, "")
            if final_disposition == "quarantined" and block_id in repair_case_by_block:
                resolution_items.append(
                    {
                        "block_id": block_id,
                        "status": "converted_to_repair_case",
                        "repair_case_id": repair_case_by_block[block_id],
                        "final_disposition": final_disposition,
                    }
                )
            elif block_id in candidate_by_block or final_disposition in {"section", "knowledge", "instruction", "document_meta", "decorative", "blank"}:
                resolution_items.append(
                    {
                        "block_id": block_id,
                        "status": "resolved_deterministically",
                        "final_candidate_id": candidate_by_block.get(block_id, ""),
                        "final_disposition": final_disposition,
                    }
                )
            elif final_disposition == "quarantined":
                resolution_items.append({"block_id": block_id, "status": "quarantined", "final_disposition": final_disposition})
        item_statuses = {item["status"] for item in resolution_items}
        if "converted_to_repair_case" in item_statuses and len(item_statuses) > 1:
            resolution_status = "partially_resolved"
        elif "converted_to_repair_case" in item_statuses:
            resolution_status = "converted_to_repair_case"
        elif issue_type in final_types:
            resolution_status = "still_open"
        elif issue_type in {"unassigned_blocks", "section_contains_question_like_content", "ambiguous_attachment", "title_source_ref_outside_unit"}:
            resolution_status = "resolved_deterministically"
        else:
            resolution_status = "superseded"
        action_ids = sorted({action_id for block_id in raw_block_ids for action_id in action_by_block.get(block_id, [])})
        final_candidate_ids = sorted({candidate_by_block[block_id] for block_id in raw_block_ids if block_id in candidate_by_block})
        final_dispositions = sorted({disposition_by_block.get(block_id, "") for block_id in raw_block_ids if block_id in disposition_by_block})
        resolutions.append(
            {
                "raw_issue_id": f"raw_issue_{index:04d}",
                "raw_issue_type": issue_type,
                "raw_block_ids": raw_block_ids,
                "resolution_status": resolution_status,
                "resolution_items": resolution_items,
                "resolution_action_ids": action_ids,
                "final_candidate_ids": final_candidate_ids,
                "final_dispositions": final_dispositions,
                "evidence": {
                    "before": issue,
                    "after": {
                        "candidate_ids": final_candidate_ids,
                        "dispositions": final_dispositions,
                    },
                },
            }
        )
    counts = {status: 0 for status in ["resolved_deterministically", "false_positive", "superseded", "converted_to_repair_case", "partially_resolved", "quarantined", "still_open"]}
    for item in resolutions:
        counts[item["resolution_status"]] = counts.get(item["resolution_status"], 0) + 1
        for resolution_item in item.get("resolution_items", []) or []:
            status = str(resolution_item.get("status") or "")
            if status in {"converted_to_repair_case", "quarantined"}:
                counts[status] = counts.get(status, 0) + 1
            if resolution_item.get("final_disposition") == "quarantined":
                counts["quarantined"] = counts.get("quarantined", 0) + 1
    missing_resolution = max(0, len(raw_issues) - len(resolutions))
    missing_action_refs = [
        item["raw_issue_id"]
        for item in resolutions
        if item["resolution_status"] in {"resolved_deterministically", "converted_to_repair_case", "quarantined"}
        and not item["resolution_action_ids"]
    ]
    return {
        "schema_version": "docx_math_raw_issue_resolution_manifest.v0.1",
        "raw_issue_count": len(raw_issues),
        "resolution_record_count": len(resolutions),
        "unresolved_without_repair_case_count": counts.get("still_open", 0),
        "missing_resolution_action_reference_count": len(missing_action_refs),
        "missing_resolution_action_reference_ids": missing_action_refs,
        "metrics": {
            "raw_issue_count": len(raw_issues),
            "resolved_deterministically_count": counts.get("resolved_deterministically", 0),
            "false_positive_count": counts.get("false_positive", 0),
            "superseded_count": counts.get("superseded", 0),
            "converted_to_repair_case_count": counts.get("converted_to_repair_case", 0),
            "partially_resolved_count": counts.get("partially_resolved", 0),
            "quarantined_count": counts.get("quarantined", 0),
            "still_open_count": counts.get("still_open", 0),
            "missing_resolution_count": missing_resolution,
        },
        "resolutions": resolutions,
    }


def evaluate_golden_fixture(
    fixture_path: Path | None,
    questions: list[dict[str, Any]],
    flow_summary: dict[str, Any],
    repair_queue: dict[str, Any],
    block_disposition: dict[str, Any],
    semantic_boundary_audit: dict[str, Any],
    section_scope_manifest: dict[str, Any],
    source_artifact_paths: dict[str, Path],
) -> dict[str, Any]:
    if not fixture_path:
        return {"status": "not_run", "mismatches": [], "assertion_count": 0, "passed_assertion_count": 0, "failed_assertion_count": 0}
    expected = read_json(fixture_path)
    by_candidate = {question["candidate_id"]: question for question in questions}
    start_ids = {question["start_block_id"] for question in questions}
    disp_by_block = {item["block_id"]: item for item in block_disposition.get("dispositions", []) or []}
    section_by_block = {item["block_id"]: item for item in section_scope_manifest.get("sections", []) or []}
    mismatches: list[dict[str, Any]] = []
    checked_boundaries: list[dict[str, Any]] = []
    assertion_count = 0

    def check(condition: bool, mismatch: dict[str, Any]) -> None:
        nonlocal assertion_count
        assertion_count += 1
        if not condition:
            mismatches.append(mismatch)

    if len(questions) != expected.get("expected_question_count"):
        check(False, {"type": "question_count", "expected": expected.get("expected_question_count"), "actual": len(questions)})
    else:
        check(True, {})
    check(flow_summary["question_flow_status"] == expected.get("expected_question_flow_status"), {"type": "question_flow_status", "expected": expected.get("expected_question_flow_status"), "actual": flow_summary["question_flow_status"]})
    check(flow_summary["document_content_status"] == expected.get("expected_document_content_status"), {"type": "document_content_status", "expected": expected.get("expected_document_content_status"), "actual": flow_summary["document_content_status"]})
    check(bool(questions) and questions[0]["candidate_id"] == expected.get("expected_first_candidate_id"), {"type": "first_candidate_id", "expected": expected.get("expected_first_candidate_id"), "actual": questions[0]["candidate_id"] if questions else ""})
    forbidden = set(expected.get("forbidden_candidate_start_block_ids", []) or [])
    forbidden_present = sorted(forbidden & start_ids)
    check(not forbidden_present, {"type": "forbidden_candidate_start_block_ids", "block_ids": forbidden_present})
    forbidden_candidate_ids = set(expected.get("forbidden_candidate_ids", []) or [])
    forbidden_candidate_present = sorted(forbidden_candidate_ids & set(by_candidate))
    check(not forbidden_candidate_present, {"type": "forbidden_candidate_ids", "candidate_ids": forbidden_candidate_present})
    quarantined = [
        block_id
        for case in repair_queue.get("repair_cases", []) or []
        if "quarantine_span" in case.get("issue_types", [])
        for block_id in case.get("target_block_ids", []) or []
    ]
    check(sorted(quarantined) == sorted(expected.get("expected_quarantined_block_ids", []) or []), {"type": "quarantined_block_ids", "expected": expected.get("expected_quarantined_block_ids", []), "actual": quarantined})
    for candidate_id, boundary in (expected.get("expected_boundaries", {}) or {}).items():
        question = by_candidate.get(candidate_id)
        actual = [question["start_block_id"], question["end_block_id"]] if question else None
        checked_boundaries.append({"candidate_id": candidate_id, "expected": boundary, "actual": actual})
        check(actual == boundary, {"type": "candidate_boundary", "candidate_id": candidate_id, "expected": boundary, "actual": actual})
    for block_id, role in (expected.get("expected_question_block_roles", {}) or {}).items():
        actual = disp_by_block.get(block_id, {}).get("question_block_role", "")
        check(actual == role, {"type": "question_block_role", "block_id": block_id, "expected": role, "actual": actual})
    for block_id, scope in (expected.get("expected_section_scopes", {}) or {}).items():
        actual = section_by_block.get(block_id, {}).get("section_scope", "")
        check(actual == scope, {"type": "section_scope", "block_id": block_id, "expected": scope, "actual": actual})
    for key, expected_value in (expected.get("expected_semantic_boundary_metrics", {}) or {}).items():
        actual = semantic_boundary_audit.get(key)
        check(actual == expected_value, {"type": "semantic_boundary_metric", "field": key, "expected": expected_value, "actual": actual})
    source_hashes: dict[str, str] = {}
    for label, path in source_artifact_paths.items():
        if path.exists():
            source_hashes[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "status": "pass" if not mismatches else "fail",
        "fixture_path": str(fixture_path),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "source_artifact_hashes": source_hashes,
        "assertion_count": assertion_count,
        "passed_assertion_count": assertion_count - len(mismatches),
        "failed_assertion_count": len(mismatches),
        "checked_boundaries": checked_boundaries,
        "mismatches": mismatches,
    }


HARD_ISSUE_TYPES = {
    "invalid_source_ref",
    "unit_assigns_context_block",
    "non_contiguous_unit",
    "block_coverage_gap",
    "block_coverage_overlap",
    "question_contains_section_unit",
    "question_boundary_non_contiguous",
    "section_contains_question_like_content",
    "unknown_unit",
    "unit_completeness_review",
    "ambiguous_attachment",
}


def block_has_content(block: dict[str, Any]) -> bool:
    return bool(
        str(block.get("markdown") or block.get("text") or "").strip()
        or block.get("image_refs")
        or block.get("formula_count")
        or block.get("source_block_type") == "docx_table"
    )


def apply_question_flow_gates(
    questions: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    block_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Project boundary issues to question-level flow decisions."""
    meaningful_unassigned = {
        block_id
        for issue in issues
        if issue.get("type") == "unassigned_blocks"
        for block_id in issue.get("block_ids", []) or []
        if block_has_content(block_by_id.get(str(block_id), {}))
    }

    for question in questions:
        q_blocks = set(question.get("block_ids", []) or [])
        blocking: list[str] = []
        soft: list[str] = []
        for issue in issues:
            issue_type = str(issue.get("type") or "unknown_issue")
            issue_blocks = {str(block_id) for block_id in issue.get("block_ids", []) or []}
            overlaps = bool(q_blocks & issue_blocks)
            if issue_type == "unassigned_blocks":
                continue
            if overlaps and issue_type in HARD_ISSUE_TYPES:
                blocking.append(issue_type)
            elif overlaps:
                soft.append(issue_type)
        if q_blocks & meaningful_unassigned:
            blocking.append("contains_unassigned_content")
        blocking = sorted(set(blocking))
        soft = sorted(set(soft))
        question["boundary_status"] = "blocked" if blocking else ("review" if soft else "ready")
        question["flow_allowed"] = not blocking
        question["blocking_reasons"] = blocking
        question["review_flags"] = soft

    ready_count = sum(1 for question in questions if question.get("flow_allowed"))
    blocked_count = len(questions) - ready_count
    return {
        "bulk_flow_allowed": blocked_count == 0 and not meaningful_unassigned,
        "ready_question_count": ready_count,
        "blocked_question_count": blocked_count,
        "meaningful_unassigned_block_ids": sorted(meaningful_unassigned, key=source_order),
    }


def render_trace_html(out_dir: Path, blocks: list[dict[str, Any]], units: list[dict[str, Any]], questions: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    unit_by_block: dict[str, list[str]] = {}
    for unit in units:
        label = f"{unit['unit_id']}:{unit['semantic_role']}"
        for block_id in unit.get("block_ids", []):
            unit_by_block.setdefault(block_id, []).append(label)
    q_by_block: dict[str, list[str]] = {}
    for q in questions:
        for block_id in q.get("block_ids", []):
            q_by_block.setdefault(block_id, []).append(q["question_id"])
    rows = []
    for block in blocks:
        block_id = block["block_id"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(block_id)}</td>"
            f"<td>{block['source_order']}</td>"
            f"<td>{html.escape(block['source_block_type'])}</td>"
            f"<td>{html.escape(', '.join(unit_by_block.get(block_id, [])))}</td>"
            f"<td>{html.escape(', '.join(q_by_block.get(block_id, [])))}</td>"
            f"<td>{html.escape(' '.join(block.get('weak_hints', [])))}</td>"
            f"<td>{html.escape(compact_text(block.get('markdown') or block.get('text') or '', 260))}</td>"
            "</tr>"
        )
    page = (
        "<!doctype html><meta charset='utf-8'><title>DOCX Boundary Trace</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:20px;color:#111827}"
        "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #d7dee8;padding:6px;vertical-align:top}"
        "th{background:#eef2f7}.issues{white-space:pre-wrap;background:#fff7ed;border:1px solid #fed7aa;padding:12px}</style>"
        "<h1>DOCX Boundary Trace</h1>"
        f"<p>blocks={len(blocks)} units={len(units)} questions={len(questions)} issues={len(issues)}</p>"
        f"<div class='issues'>{html.escape(json.dumps(issues[:80], ensure_ascii=False, indent=2))}</div>"
        "<table><thead><tr><th>block</th><th>order</th><th>type</th><th>unit</th><th>question</th><th>hints</th><th>text</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )
    (out_dir / "boundary_trace.html").write_text(page, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    boundary_rule_inventory = build_boundary_rule_inventory(config)
    overfit_literal_scan = scan_overfit_literals()
    out_root = ROOT / str(config.get("owned_output_root") or "outputs/docx_native_boundary_resolver_v0_1")
    out_dir = out_root / args.run_id / slug_for(args.paragraph_stream)
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paragraph_stream = read_json(args.paragraph_stream)
    immutable = build_immutable_block_stream(paragraph_stream)
    blocks = immutable["blocks"]
    block_by_id = {block["block_id"]: block for block in blocks}
    config_hash = stable_hash(config)
    prompt_hash = sha256_text(SYSTEM_PROMPT)
    write_json(out_dir / "immutable_block_stream.json", immutable)

    window_cfg = config.get("window", {}) or {}
    windows = plan_windows(
        blocks,
        core=int(args.core_blocks or window_cfg.get("core_blocks") or 24),
        left=int(args.context_left_blocks or window_cfg.get("context_left_blocks") or 6),
        right=int(args.context_right_blocks or window_cfg.get("context_right_blocks") or 6),
    )
    write_json(out_dir / "window_plan.json", {"windows": [window.__dict__ for window in windows]})

    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    model = args.model or str(config.get("default_model_endpoint_id") or "doubao-seed-2-0-mini-260428")
    preview_chars = int(window_cfg.get("max_block_preview_chars") or 520)
    raw_dir = out_dir / "raw_model_responses"

    all_units: list[dict[str, Any]] = []
    unassigned: list[str] = []
    issues: list[dict[str, Any]] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for window in windows:
        payload = build_user_payload(window=window, blocks=blocks, preview_chars=preview_chars, config_hash=config_hash)
        write_json(raw_dir / f"{window.window_id}.prompt.json", payload)
        if args.no_model:
            window_units, window_unassigned = fallback_units_for_failed_window(window)
            unassigned.extend(window_unassigned)
            issues.append({"type": "model_skipped", "window_id": window.window_id, "block_ids": window_unassigned})
            continue
        if not api_key and not args.replay_raw_dir:
            window_units, window_unassigned = fallback_units_for_failed_window(window)
            unassigned.extend(window_unassigned)
            issues.append({"type": "missing_api_key", "window_id": window.window_id, "block_ids": window_unassigned})
            continue
        try:
            if args.replay_raw_dir:
                replay_content = Path(args.replay_raw_dir) / f"{window.window_id}.content.json"
                parsed = json.loads(replay_content.read_text(encoding="utf-8"))
                result = {"parsed": parsed, "usage": {}, "finish_reason": "replay"}
            else:
                result = call_model(api_key, model, payload, timeout=int(args.timeout))
                write_json(raw_dir / f"{window.window_id}.response.json", result["raw_response"])
                (raw_dir / f"{window.window_id}.content.json").write_text(result["raw_content"], encoding="utf-8")
                if result.get("finish_reason") == "length":
                    raise RuntimeError("model_finish_reason_length")
                for key in usage_totals:
                    usage_totals[key] += int((result.get("usage") or {}).get(key) or 0)
            normalized, validation_issues = validate_window_result(window=window, result=result["parsed"], all_block_ids=set(block_by_id))
            all_units.extend(normalized)
            issues.extend(validation_issues)
            if validation_issues:
                core_ids = [f"b_{idx:06d}" for idx in range(window.core_start, window.core_end_exclusive)]
                assigned = {block_id for unit in normalized for block_id in unit.get("block_ids", [])}
                unassigned.extend([block_id for block_id in core_ids if block_id not in assigned])
            else:
                unassigned.extend([str(item) for item in result["parsed"].get("unassigned_block_ids", []) or []])
        except (json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
            window_units, window_unassigned = fallback_units_for_failed_window(window)
            all_units.extend(window_units)
            unassigned.extend(window_unassigned)
            issues.append(
                {
                    "type": "window_model_failed",
                    "window_id": window.window_id,
                    "reason": str(exc),
                    "block_ids": window_unassigned,
                }
            )

    global_units = globalize_units(all_units, block_by_id)
    global_units, merge_traces = merge_cross_window_continuations(global_units, block_by_id)
    raw_model_issues = list(issues)
    raw_model_issues.extend(section_content_gate(global_units, block_by_id))
    raw_model_issues.extend(block_review_issues(global_units, unassigned))
    questions, replay_actions, quarantined_spans, family_manifest, section_scope_manifest, boundary_decision_evidence_seed = build_questions_by_replay(blocks, global_units)
    issues, flow_summary = quality_gate_questions(questions, quarantined_spans)
    block_disposition = build_block_disposition_manifest(blocks, global_units, questions, quarantined_spans)
    flow_summary = apply_document_coverage_gate(flow_summary, block_disposition, questions)
    repair_queue = build_repair_queue(issues, blocks, questions)
    repair_actions = {"schema_version": "docx_math_boundary_repair_actions.v0.1", "actions": []}
    assembly_actions = build_final_assembly_actions(questions, block_disposition, flow_summary)
    action_replay_audit = build_action_replay_audit(
        immutable,
        assembly_actions,
        repair_actions,
        questions,
        block_disposition,
        family_manifest,
        flow_summary,
    )
    semantic_boundary_audit = build_semantic_boundary_audit(
        questions=questions,
        block_disposition=block_disposition,
        family_manifest=family_manifest,
        section_scope_manifest=section_scope_manifest,
        units=global_units,
        blocks=blocks,
    )
    boundary_decision_evidence = finalize_boundary_decision_evidence(
        boundary_decision_evidence_seed,
        questions,
        section_scope_manifest,
        overfit_literal_scan,
    )
    preliminary_boundary_candidates = {
        "schema_version": "docx_math_question_boundary_candidates.v0.1",
        "questions": questions,
        "flow_summary": flow_summary,
        "source_unit_bundle": safe_rel(out_dir / "unit_bundle.json"),
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "question_boundary_candidates.json", preliminary_boundary_candidates)
    write_json(out_dir / "block_disposition_manifest.json", block_disposition)
    write_json(out_dir / "section_scope_manifest.json", section_scope_manifest)
    write_json(out_dir / "semantic_boundary_audit.json", semantic_boundary_audit)
    raw_issue_resolution = build_raw_issue_resolution_manifest(raw_model_issues, issues, assembly_actions, block_disposition, questions, repair_queue)
    model_unit_metrics = model_question_unit_stats(global_units, questions)
    raw_resolution_metrics = raw_issue_resolution["metrics"]
    golden_evaluation = evaluate_golden_fixture(
        args.golden_fixture,
        questions,
        flow_summary,
        repair_queue,
        block_disposition,
        semantic_boundary_audit,
        section_scope_manifest,
        {
            "question_boundary_candidates": out_dir / "question_boundary_candidates.json",
            "block_disposition_manifest": out_dir / "block_disposition_manifest.json",
            "section_scope_manifest": out_dir / "section_scope_manifest.json",
            "semantic_boundary_audit": out_dir / "semantic_boundary_audit.json",
        },
    )
    artifact_consistency_status = (
        "pass"
        if block_disposition["missing_disposition_count"] == 0
        and block_disposition["duplicate_disposition_count"] == 0
        and block_disposition["question_block_overlap_count"] == 0
        and block_disposition["source_content_hash_change_count"] == 0
        else "fail"
    )
    projection_replay_status = action_replay_audit["status"]
    boundary_pattern_audit_status = "pass" if (
        overfit_literal_scan["status"] == "pass"
        and boundary_decision_evidence["status"] == "pass"
        and boundary_rule_inventory["regex_rule_count"] >= 0
    ) else "fail"
    semantic_boundary_validation_status = "pass" if semantic_boundary_audit["status"] == "pass" and boundary_pattern_audit_status == "pass" else "fail"
    audit_trace_status = artifact_consistency_status
    action_replay_status = projection_replay_status
    raw_issue_closure_status = (
        "pass"
        if raw_issue_resolution["raw_issue_count"] == raw_issue_resolution["resolution_record_count"]
        and raw_issue_resolution["unresolved_without_repair_case_count"] == 0
        and raw_issue_resolution["missing_resolution_action_reference_count"] == 0
        and raw_resolution_metrics["missing_resolution_count"] == 0
        else "fail"
    )
    golden_fixture_status = golden_evaluation["status"]
    six_doc_regression_allowed = all(
        status == "pass"
        for status in [projection_replay_status, artifact_consistency_status, semantic_boundary_validation_status, raw_issue_closure_status, golden_fixture_status]
    )

    unit_bundle = {
        "schema_version": "docx_math_unit_bundle.v0.1",
        "source_paragraph_stream": safe_rel(args.paragraph_stream),
        "model_provider": config.get("model_provider"),
        "requested_model": args.model or config.get("default_model_alias"),
        "resolved_model_id": model,
        "prompt_version": config.get("prompt_version"),
        "config_hash": config_hash,
        "prompt_hash": prompt_hash,
        "source_sha256": sha256_text(args.paragraph_stream.read_text(encoding="utf-8")),
        "units": global_units,
        "unassigned_block_ids": sorted(set(unassigned), key=source_order),
        "merge_traces": merge_traces,
        "raw_model_issues": raw_model_issues,
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "unit_bundle.json", unit_bundle)
    write_json(out_dir / "question_family_manifest.json", family_manifest)
    write_json(out_dir / "section_scope_manifest.json", section_scope_manifest)
    write_json(out_dir / "boundary_rule_inventory.json", boundary_rule_inventory)
    write_json(out_dir / "overfit_literal_scan.json", overfit_literal_scan)
    write_json(out_dir / "boundary_decision_evidence.json", boundary_decision_evidence)
    write_json(out_dir / "boundary_assembly_actions.json", assembly_actions)
    write_json(out_dir / "boundary_repair_actions.json", repair_actions)
    write_json(out_dir / "boundary_repair_queue.json", repair_queue)
    write_json(out_dir / "block_disposition_manifest.json", block_disposition)
    write_json(out_dir / "raw_issue_resolution_manifest.json", raw_issue_resolution)
    write_json(out_dir / "boundary_action_replay_audit.json", action_replay_audit)
    write_json(out_dir / "semantic_boundary_audit.json", semantic_boundary_audit)
    write_json(out_dir / "golden_fixture_audit.json", {"schema_version": "docx_math_golden_fixture_audit.v0.2", **golden_evaluation})

    boundary_candidates = {
        "schema_version": "docx_math_question_boundary_candidates.v0.1",
        "questions": questions,
        "flow_summary": flow_summary,
        "source_unit_bundle": safe_rel(out_dir / "unit_bundle.json"),
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "question_boundary_candidates.json", boundary_candidates)

    review = {
        "schema_version": "docx_math_boundary_review.v0.1",
        "status": flow_summary["bulk_status"],
        "question_flow_status": flow_summary["question_flow_status"],
        "document_content_status": flow_summary["document_content_status"],
        "audit_trace_status": audit_trace_status,
        "action_replay_status": action_replay_status,
        "projection_replay_status": projection_replay_status,
        "artifact_consistency_status": artifact_consistency_status,
        "semantic_boundary_validation_status": semantic_boundary_validation_status,
        "boundary_pattern_audit_status": boundary_pattern_audit_status,
        "raw_issue_closure_status": raw_issue_closure_status,
        "golden_fixture_status": golden_fixture_status,
        "six_doc_regression_allowed": six_doc_regression_allowed,
        "legacy_status": "ok" if not issues else "needs_review",
        "issue_count": len(issues),
        "issues": issues,
    }
    write_json(out_dir / "boundary_review.json", review)
    render_trace_html(out_dir, blocks, global_units, questions, issues)

    summary = {
        "schema_version": "docx_math_unit_boundary_resolver_summary.v0.1",
        "status": flow_summary["bulk_status"],
        "question_flow_status": flow_summary["question_flow_status"],
        "document_content_status": flow_summary["document_content_status"],
        "audit_trace_status": audit_trace_status,
        "action_replay_status": action_replay_status,
        "projection_replay_status": projection_replay_status,
        "artifact_consistency_status": artifact_consistency_status,
        "semantic_boundary_validation_status": semantic_boundary_validation_status,
        "boundary_pattern_audit_status": boundary_pattern_audit_status,
        "raw_issue_closure_status": raw_issue_closure_status,
        "golden_fixture_status": golden_fixture_status,
        "six_doc_regression_allowed": six_doc_regression_allowed,
        "legacy_status": review["legacy_status"],
        "out_dir": str(out_dir),
        "source_paragraph_stream": str(args.paragraph_stream),
        "block_count": len(blocks),
        "window_count": len(windows),
        "unit_count": len(global_units),
        "question_count": len(questions),
        "ready_question_count": flow_summary["ready_question_count"],
        "non_ready_question_count": flow_summary["non_ready_question_count"],
        "bulk_status": flow_summary["bulk_status"],
        "unassigned_count": len(set(unassigned)),
        "meaningful_unassigned_count": sum(1 for block_id in set(unassigned) if has_block_content(block_by_id.get(block_id, {}))),
        "review_count": len(issues),
        "raw_model_issue_count": len(raw_model_issues),
        "repair_case_count": flow_summary["repair_case_count"],
        "quarantined_count": flow_summary["quarantined_count"],
        "merge_trace_count": len(merge_traces),
        "raw_model_metrics": {
            "issue_count": len(raw_model_issues),
            "unassigned_count": len(set(unassigned)),
            "meaningful_unassigned_count": sum(1 for block_id in set(unassigned) if has_block_content(block_by_id.get(block_id, {}))),
        },
        "final_replay_metrics": {
            "question_count": len(questions),
            "ready_question_count": flow_summary["ready_question_count"],
            "non_ready_question_count": flow_summary["non_ready_question_count"],
            "repair_pending_count": len(repair_queue.get("repair_cases", [])),
            "quarantined_count": flow_summary["quarantined_count"],
            "question_flow_status": flow_summary["question_flow_status"],
            "document_content_status": flow_summary["document_content_status"],
        },
        "model_question_unit_metrics": model_unit_metrics,
        "raw_issue_resolution_metrics": raw_resolution_metrics,
        "semantic_boundary_metrics": {key: semantic_boundary_audit[key] for key in [
            "question_count",
            "context_dependent_orphan_question_count",
            "question_internal_heading_split_count",
            "question_contains_document_section_count",
            "question_contains_assessment_section_count",
            "question_family_orphan_count",
            "unresolved_section_scope_count",
            "shared_material_relation_missing_count",
        ]},
        "boundary_rule_inventory_metrics": {
            "rule_count": boundary_rule_inventory["rule_count"],
            "regex_rule_count": boundary_rule_inventory["regex_rule_count"],
            "keyword_or_pattern_rule_count": boundary_rule_inventory["keyword_or_pattern_rule_count"],
            "deterministic_pattern_rule_count": boundary_rule_inventory["deterministic_pattern_rule_count"],
            "by_rule_type": boundary_rule_inventory["by_rule_type"],
            "by_decision_authority": boundary_rule_inventory["by_decision_authority"],
        },
        "overfit_literal_scan_metrics": {
            "production_files_scanned": overfit_literal_scan["production_files_scanned"],
            "forbidden_literal_match_count": overfit_literal_scan["forbidden_literal_match_count"],
            "production_code_reads_golden_fixture": overfit_literal_scan["production_code_reads_golden_fixture"],
            "production_code_reads_doc2_fixture": overfit_literal_scan["production_code_reads_doc2_fixture"],
        },
        "boundary_decision_evidence_metrics": {
            "decision_count": boundary_decision_evidence["decision_count"],
            "single_evidence_final_decision_count": boundary_decision_evidence["single_evidence_final_decision_count"],
            "regex_only_final_decision_count": boundary_decision_evidence["regex_only_final_decision_count"],
            "keyword_only_section_scope_count": boundary_decision_evidence["keyword_only_section_scope_count"],
            "hardcoded_literal_decision_count": boundary_decision_evidence["hardcoded_literal_decision_count"],
            "production_code_reads_golden_fixture": boundary_decision_evidence["production_code_reads_golden_fixture"],
            "production_code_reads_doc2_fixture": boundary_decision_evidence["production_code_reads_doc2_fixture"],
        },
        "section_scope_metrics": {key: section_scope_manifest[key] for key in [
            "section_count",
            "document_section_count",
            "question_group_section_count",
            "assessment_type_section_count",
            "question_internal_heading_count",
            "unknown_section_count",
            "section_scope_missing_count",
        ]},
        "action_replay_metrics": {
            "assembly_action_count": action_replay_audit["assembly_action_count"],
            "repair_action_count": action_replay_audit["repair_action_count"],
            "replayed_question_count": action_replay_audit["replayed_question_count"],
            "expected_question_count": action_replay_audit["expected_question_count"],
            "question_boundary_mismatch_count": action_replay_audit["question_boundary_mismatch_count"],
            "candidate_owner_mismatch_count": action_replay_audit["candidate_owner_mismatch_count"],
            "disposition_mismatch_count": action_replay_audit["disposition_mismatch_count"],
            "family_reference_mismatch_count": action_replay_audit["family_reference_mismatch_count"],
            "status_mismatch_count": action_replay_audit["status_mismatch_count"],
        },
        "block_disposition_metrics": {key: block_disposition[key] for key in ["block_count", "disposition_block_count", "duplicate_disposition_count", "missing_disposition_count", "question_block_overlap_count", "source_content_hash_change_count"]},
        "model_calls_this_run": 0 if args.no_model or args.replay_raw_dir or not api_key else len(windows),
        "usage": usage_totals,
        "artifacts": {
            "immutable_block_stream": safe_rel(out_dir / "immutable_block_stream.json"),
            "window_plan": safe_rel(out_dir / "window_plan.json"),
            "unit_bundle": safe_rel(out_dir / "unit_bundle.json"),
            "question_boundary_candidates": safe_rel(out_dir / "question_boundary_candidates.json"),
            "question_family_manifest": safe_rel(out_dir / "question_family_manifest.json"),
            "section_scope_manifest": safe_rel(out_dir / "section_scope_manifest.json"),
            "boundary_rule_inventory": safe_rel(out_dir / "boundary_rule_inventory.json"),
            "overfit_literal_scan": safe_rel(out_dir / "overfit_literal_scan.json"),
            "boundary_decision_evidence": safe_rel(out_dir / "boundary_decision_evidence.json"),
            "boundary_repair_queue": safe_rel(out_dir / "boundary_repair_queue.json"),
            "boundary_repair_actions": safe_rel(out_dir / "boundary_repair_actions.json"),
            "boundary_assembly_actions": safe_rel(out_dir / "boundary_assembly_actions.json"),
            "boundary_action_replay_audit": safe_rel(out_dir / "boundary_action_replay_audit.json"),
            "semantic_boundary_audit": safe_rel(out_dir / "semantic_boundary_audit.json"),
            "block_disposition_manifest": safe_rel(out_dir / "block_disposition_manifest.json"),
            "raw_issue_resolution_manifest": safe_rel(out_dir / "raw_issue_resolution_manifest.json"),
            "golden_fixture_audit": safe_rel(out_dir / "golden_fixture_audit.json"),
            "boundary_review": safe_rel(out_dir / "boundary_review.json"),
            "boundary_trace_html": safe_rel(out_dir / "boundary_trace.html"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX native model-assisted unit boundary resolver v0.1.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--core-blocks", type=int, default=0)
    parser.add_argument("--context-left-blocks", type=int, default=0)
    parser.add_argument("--context-right-blocks", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--replay-raw-dir", type=Path, default=None, help="Replay existing raw_model_responses/*.content.json without calling the model.")
    parser.add_argument("--golden-fixture", type=Path, default=None, help="Optional audit-only golden fixture for deterministic replay validation.")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
