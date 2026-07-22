from __future__ import annotations

import argparse
import base64
import html
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

import option_anchor_detection
import assetize_question_images
import vision_prompt_store
from question_visual_structure_contract import normalize_review_flags


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def asset_role(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_role") or asset.get("role") or "").strip()


def placement(asset: dict[str, Any]) -> str:
    return str(asset.get("placement_scope") or asset.get("placement") or "").strip()


def is_materialized(asset: dict[str, Any]) -> bool:
    return bool(asset.get("materialized")) and str(asset.get("file_status", "") or "") == "materialized"


def is_cropped_asset(asset: dict[str, Any]) -> bool:
    return asset_role(asset) in {"stem", "analysis", "option"} and is_materialized(asset)


def is_panel_group_asset(asset: dict[str, Any]) -> bool:
    if str(asset.get("crop_policy", "") or "").strip() == "panel_group_preserve_layout":
        return True
    if str(asset.get("panel_group_id", "") or "").strip():
        return True
    if int(asset.get("panel_subfigure_count", 0) or 0) > 0:
        return True
    flags = {str(flag) for flag in (asset.get("review_flags", []) or [])}
    return "panel_kept" in flags or "panel_subfigure_union" in flags


def local_path(asset: dict[str, Any], manifest_path: Path) -> Path | None:
    debug = asset.get("debug", {}) if isinstance(asset.get("debug"), dict) else {}
    raw = str(debug.get("local_path", "") or "")
    if raw and Path(raw).exists():
        return Path(raw)
    key = str(asset.get("storage_key", "") or "")
    if key:
        for base in (manifest_path.parent, manifest_path.parent.parent):
            path = base / key
            if path.exists():
                return path
    return None


def _selected_visual_insert_assets(record: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for scope in ("stem", "analysis"):
        selected.extend(assetize_question_images._resolve_selected_assets(record, scope))
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in selected:
        aid = asset_id(asset)
        if not aid or aid in seen:
            continue
        seen.add(aid)
        unique.append(asset)
    return sorted(unique, key=assetize_question_images._asset_sort_key)


def _question_image_path(record: dict[str, Any], manifest_path: Path) -> Path | None:
    selected = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    evidence_ids = selected.get("evidence", []) if isinstance(selected.get("evidence"), list) else []
    by_id = {asset_id(asset): asset for asset in (record.get("assets", []) or []) if isinstance(asset, dict)}
    for evidence_id in evidence_ids:
        asset = by_id.get(str(evidence_id or "").strip())
        if asset:
            path = local_path(asset, manifest_path)
            if path and path.exists():
                return path
    gate = record.get("image_need_gate", {}) if isinstance(record.get("image_need_gate"), dict) else {}
    raw = str(gate.get("source_image", "") or "").strip()
    if raw:
        candidate = Path(raw)
        if candidate.exists():
            return candidate
    debug = record.get("debug_source_refs", {}) if isinstance(record.get("debug_source_refs"), dict) else {}
    for key in ("source_question_image", "source_stem_image", "source_analysis_image"):
        raw = str(debug.get(key, "") or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.exists():
            return candidate
    return None


def _fallback_target_field(asset: dict[str, Any]) -> str:
    return "analysis" if asset_role(asset) == "analysis" else "stem"


def _apply_visual_insert_anchor_fallback(
    record: dict[str, Any],
    *,
    bundle: dict[str, Any],
    error: str,
    reason_flag: str,
    attempt: int | None = None,
) -> dict[str, Any]:
    fallback_plan = _heuristic_visual_anchor_plan(record)
    if fallback_plan:
        normalized_plan = _normalize_visual_anchor_plan(record, fallback_plan)
        qvs = record.get("question_visual_structure", {}) if isinstance(record.get("question_visual_structure"), dict) else {}
        qvs["visual_insert_anchor_slots"] = assetize_question_images.build_visual_insert_anchor_slots(record)
        qvs["visual_insert_anchor_plan"] = normalized_plan
        qvs["content_blocks"] = assetize_question_images.build_content_blocks_from_visual_insert_anchor_plan(record, normalized_plan)
        qvs["inline_asset_anchor_mode"] = "slot_reflow_v1"
        qvs["review_flags"] = sorted(
            set(
                [str(flag) for flag in (qvs.get("review_flags", []) or [])]
                + ["visual_insert_anchor_review_applied", "visual_insert_anchor_slot_order_fallback", reason_flag]
            )
        )
        record["question_visual_structure"] = qvs
        record["visual_insert_anchor_review"] = {
            "prompt_version": bundle["prompt_version"],
            "available_slots": qvs["visual_insert_anchor_slots"],
            "placements": normalized_plan,
            "global_review_flags": [reason_flag, "visual_insert_anchor_slot_order_fallback"],
            "raw_response": {"error": str(error or "")[:500], "fallback": True},
        }
        return {
            "question_id": record.get("question_id", ""),
            "action": "visual_insert_anchor_slot_fallback_applied",
            "asset_count": len(normalized_plan),
            "reason": reason_flag,
            "attempt": attempt,
        }
    return {
        "question_id": record.get("question_id", ""),
        "action": "visual_insert_anchor_model_failed",
        "error": str(error or "")[:500],
        "reason": reason_flag,
        "attempt": attempt,
    }


def _normalize_visual_anchor_plan(record: dict[str, Any], placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets = _selected_visual_insert_assets(record)
    selected_ids = [asset_id(asset) for asset in assets if asset_id(asset)]
    by_id = {aid: asset for aid, asset in ((asset_id(asset), asset) for asset in assets) if aid}
    all_slots = assetize_question_images.build_visual_insert_anchor_slots(record)
    anchor_slot_map = {
        str(item.get("slot_id", "") or "").strip(): item
        for item in all_slots
        if str(item.get("slot_id", "") or "").strip()
    }
    figure_slots_by_field: dict[str, list[dict[str, Any]]] = {"stem": [], "answer": [], "analysis": []}
    for item in all_slots:
        field = str(item.get("field", "") or "").strip()
        if field in figure_slots_by_field and str(item.get("slot_type", "") or "").strip() == "figure_ref":
            figure_slots_by_field[field].append(item)
    for field in figure_slots_by_field:
        figure_slots_by_field[field].sort(key=lambda item: (int(item.get("start", 0) or 0), int(item.get("end", 0) or 0)))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in placements:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("asset_id", "") or "").strip()
        if not aid or aid not in by_id or aid in seen:
            continue
        target_field = str(item.get("target_field", "") or "").strip()
        if target_field not in {"stem", "answer", "analysis"}:
            target_field = _fallback_target_field(by_id[aid])
        asset = by_id[aid]
        anchor_mode = str(item.get("anchor_mode", "") or "").strip()
        if anchor_mode not in {"after_anchor_slot", "after_anchor_text", "field_tail"}:
            anchor_mode = "field_tail"
        anchor_slot_id = str(item.get("anchor_slot_id", "") or "").strip()
        anchor_text = str(item.get("anchor_text", "") or "").strip()
        review_flags = [str(flag) for flag in (item.get("review_flags", []) or []) if str(flag).strip()]
        if target_field == "stem" and is_panel_group_asset(asset):
            stem_slots = figure_slots_by_field.get("stem", [])
            if stem_slots and anchor_mode != "after_anchor_slot":
                slot = stem_slots[0]
                anchor_mode = "after_anchor_slot"
                anchor_slot_id = str(slot.get("slot_id", "") or "").strip()
                anchor_text = str(slot.get("anchor_text", "") or "").strip()
                review_flags = normalize_review_flags(review_flags + ["visual_insert_anchor_panel_force_first_figure_slot"])
        if anchor_mode == "after_anchor_slot":
            slot = anchor_slot_map.get(anchor_slot_id)
            if not isinstance(slot, dict) or str(slot.get("field", "") or "").strip() != target_field:
                anchor_mode = "field_tail"
                anchor_slot_id = ""
                anchor_text = ""
            else:
                anchor_text = str(slot.get("anchor_text", anchor_text) or "").strip()
        if anchor_mode == "field_tail":
            if target_field == "stem" and is_panel_group_asset(asset):
                field_slots = figure_slots_by_field.get("stem", [])
                if field_slots:
                    slot = field_slots[0]
                    anchor_mode = "after_anchor_slot"
                    anchor_slot_id = str(slot.get("slot_id", "") or "").strip()
                    anchor_text = str(slot.get("anchor_text", "") or "").strip()
                    review_flags = normalize_review_flags(review_flags + ["visual_insert_anchor_panel_promote_first_figure_slot"])
                else:
                    anchor_slot_id = ""
                    anchor_text = ""
            else:
                anchor_slot_id = ""
                anchor_text = ""
        if anchor_mode == "after_anchor_slot" and anchor_slot_id:
            slot = anchor_slot_map.get(anchor_slot_id)
            if isinstance(slot, dict):
                anchor_text = str(slot.get("anchor_text", anchor_text) or "").strip()
        normalized.append(
            {
                "asset_id": aid,
                "target_field": target_field,
                "anchor_mode": anchor_mode,
                "anchor_slot_id": anchor_slot_id,
                "anchor_text": anchor_text,
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "review_flags": review_flags,
            }
        )
        seen.add(aid)

    for aid in selected_ids:
        if aid in seen:
            continue
        asset = by_id[aid]
        normalized.append(
            {
                "asset_id": aid,
                "target_field": _fallback_target_field(asset),
                "anchor_mode": "field_tail",
                "anchor_slot_id": "",
                "anchor_text": "",
                "confidence": 0.0,
                "review_flags": ["visual_insert_anchor_fallback_tail"],
            }
        )
    return normalized


def _heuristic_visual_anchor_plan(record: dict[str, Any]) -> list[dict[str, Any]]:
    assets = _selected_visual_insert_assets(record)
    if not assets:
        return []
    slots = assetize_question_images.build_visual_insert_anchor_slots(record)
    figure_slots_by_field: dict[str, list[dict[str, Any]]] = {"stem": [], "answer": [], "analysis": []}
    for item in slots:
        field = str(item.get("field", "") or "").strip()
        if field in figure_slots_by_field and str(item.get("slot_type", "") or "").strip() == "figure_ref":
            figure_slots_by_field[field].append(item)

    exact_fields = [field for field, field_slots in figure_slots_by_field.items() if len(field_slots) == len(assets)]
    if len(exact_fields) != 1:
        return []

    target_field = exact_fields[0]
    sorted_assets = sorted(
        assets,
        key=lambda item: (
            int(item.get("candidate_anchor_order", 0) or 0),
            assetize_question_images._asset_sort_key(item),
        ),
    )
    field_slots = sorted(
        figure_slots_by_field[target_field],
        key=lambda item: (int(item.get("start", 0) or 0), int(item.get("end", 0) or 0)),
    )
    placements: list[dict[str, Any]] = []
    for asset, slot in zip(sorted_assets, field_slots):
        placements.append(
            {
                "asset_id": asset_id(asset),
                "target_field": target_field,
                "anchor_mode": "after_anchor_slot",
                "anchor_slot_id": str(slot.get("slot_id", "") or "").strip(),
                "anchor_text": str(slot.get("anchor_text", "") or "").strip(),
                "confidence": 0.0,
                "review_flags": ["visual_insert_anchor_slot_order_fallback"],
            }
        )
    return placements


def _merged_slot_windows(slots: list[dict[str, Any]], text_len: int, *, before: int = 72, after: int = 180) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for item in slots:
        start = max(0, int(item.get("start", 0) or 0) - before)
        end = min(text_len, int(item.get("end", 0) or 0) + after)
        if not windows:
            windows.append((start, end))
            continue
        last_start, last_end = windows[-1]
        if start <= last_end + 24:
            windows[-1] = (last_start, max(last_end, end))
        else:
            windows.append((start, end))
    return windows


def _compress_field_snapshot_for_anchor_review(
    text_md: str,
    field_slots: list[dict[str, Any]],
    *,
    hard_limit: int = 3200,
) -> str:
    value = str(text_md or "")
    if len(value) <= hard_limit:
        return value
    figure_slots = [item for item in field_slots if str(item.get("slot_type", "") or "").strip() == "figure_ref"]
    focus_slots = figure_slots or field_slots
    if not focus_slots:
        head = value[:1000].rstrip()
        tail = value[-700:].lstrip()
        return f"{head}\n...[TRUNCATED_FOR_VISUAL_INSERT_REVIEW]...\n{tail}"

    windows = _merged_slot_windows(focus_slots, len(value))
    snippets: list[str] = []
    for start, end in windows[:10]:
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(value) else ""
        snippets.append(f"{prefix}{value[start:end].strip()}{suffix}")
    compact = "\n".join(snippets).strip()
    if len(compact) <= hard_limit:
        return compact
    return compact[:hard_limit].rstrip() + "\n...[TRUNCATED_FOR_VISUAL_INSERT_REVIEW]"


def _build_anchor_review_field_snapshots(record: dict[str, Any]) -> dict[str, str]:
    slots = assetize_question_images.build_visual_insert_anchor_slots(record)
    slots_by_field: dict[str, list[dict[str, Any]]] = {"stem": [], "answer": [], "analysis": []}
    for item in slots:
        field = str(item.get("field", "") or "").strip()
        if field in slots_by_field:
            slots_by_field[field].append(item)
    return {
        "stem": _compress_field_snapshot_for_anchor_review(str(record.get("stem_text_md", "") or ""), slots_by_field["stem"]),
        "answer": _compress_field_snapshot_for_anchor_review(str(record.get("answer_text_md", "") or ""), slots_by_field["answer"]),
        "analysis": _compress_field_snapshot_for_anchor_review(str(record.get("analysis_text_md", "") or ""), slots_by_field["analysis"]),
    }


def _is_long_question_image(record: dict[str, Any], manifest_path: Path) -> bool:
    question_image_path = _question_image_path(record, manifest_path)
    if not question_image_path or not question_image_path.exists():
        return False
    try:
        with Image.open(question_image_path) as image:
            width, height = image.size
    except Exception:
        return False
    return height >= 1300 or height >= width * 1.55


def _should_use_visual_block_layout_review(
    record: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    manifest_path: Path,
) -> tuple[bool, str]:
    if len(assets) < 3:
        return False, "asset_count_lt_3"
    has_group_asset = any(is_panel_group_asset(asset) for asset in assets)
    has_long_flag = any(
        "long_image_branch" in {str(flag) for flag in (asset.get("review_flags", []) or [])}
        for asset in assets
    )
    if not has_group_asset and not has_long_flag:
        return False, "no_panel_or_long_asset"
    if not _is_long_question_image(record, manifest_path):
        return False, "question_image_not_long"
    return True, "long_panel_group"


def _split_text_segments(field: str, text_md: str) -> list[dict[str, Any]]:
    value = str(text_md or "").strip()
    if not value:
        return []
    cut_points: set[int] = set()
    cursor = 0
    for line in value.splitlines(keepends=True):
        cursor += len(line)
        cut_points.add(cursor)
    try:
        for slot in assetize_question_images._extract_visual_insert_anchor_slots_for_field(field, value):
            cut_points.add(int(slot.get("end", 0) or 0))
    except Exception:
        pass
    segments: list[dict[str, Any]] = []
    index = 1
    start = 0
    for end in sorted(point for point in cut_points if 0 < point <= len(value)):
        segment_text = value[start:end].strip()
        if segment_text:
            segments.append(
                {
                    "segment_id": f"{field}_seg_{index:03d}",
                    "field": field,
                    "text_md": segment_text,
                    "index": index,
                }
            )
            index += 1
        start = end
    segment_text = value[start:].strip()
    if segment_text:
        segments.append(
            {
                "segment_id": f"{field}_seg_{index:03d}",
                "field": field,
                "text_md": segment_text,
                "index": index,
            }
        )
    return segments


def _build_visual_block_text_segments(record: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for field in ("stem", "answer", "analysis"):
        segments.extend(_split_text_segments(field, str(record.get(f"{field}_text_md", "") or "")))
    return segments


def _render_visual_block_segments_for_prompt(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for segment in segments:
        text = str(segment.get("text_md", "") or "").replace("\n", " / ")
        if len(text) > 420:
            text = text[:420].rstrip() + "..."
        lines.append(
            f'- segment_id={segment["segment_id"]}; field={segment["field"]}; text="{text}"'
        )
    return "\n".join(lines)


def _build_content_blocks_from_visual_block_layout(
    record: dict[str, Any],
    raw_blocks: list[dict[str, Any]],
    *,
    segments: list[dict[str, Any]],
    expected_asset_ids: list[str],
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    segment_by_id = {str(item.get("segment_id", "") or ""): item for item in segments}
    expected_segment_ids = [str(item.get("segment_id", "") or "") for item in segments]
    asset_by_id = assetize_question_images._assets_by_id(record)
    expected_assets = [asset_id for asset_id in expected_asset_ids if asset_id in asset_by_id]
    seen_segments: list[str] = []
    seen_assets: list[str] = []
    blocks: list[dict[str, Any]] = []
    flags: list[str] = []
    block_order = 0
    md_index: dict[str, int] = {"stem": 1, "answer": 1, "analysis": 1}
    image_index: dict[str, int] = {"stem": 1, "answer": 1, "analysis": 1}

    def append_markdown(field: str, text_md: str) -> None:
        nonlocal block_order
        content = str(text_md or "").strip()
        if not content:
            return
        block_order += 1
        idx = md_index[field]
        md_index[field] += 1
        blocks.append(
            {
                "block_id": f"blk_visual_block_{field}_md_{idx:03d}",
                "block_order": block_order,
                "scope": field,
                "block_type": "markdown",
                "text_md": content,
                "asset_id": None,
                "display_ref": None,
                "confidence": 1.0,
                "review_flags": ["visual_block_layout_review_applied"],
            }
        )

    def append_image(field: str, asset: dict[str, Any]) -> None:
        nonlocal block_order
        if field not in {"stem", "answer", "analysis"}:
            field = _fallback_target_field(asset)
        block_order += 1
        idx = image_index[field]
        image_index[field] += 1
        blocks.append(
            {
                "block_id": f"blk_visual_block_{field}_img_{idx:03d}",
                "block_order": block_order,
                "scope": field,
                "block_type": "image",
                "text_md": None,
                "asset_id": asset_id(asset),
                "display_ref": str(asset.get("display_ref", "") or "").strip(),
                "storage_key": str(asset.get("storage_key", "") or "").strip(),
                "asset_role": asset_role(asset),
                "confidence": 1.0,
                "review_flags": ["visual_block_layout_review_applied"],
                "anchor_mode": "block_layout",
            }
        )

    current_field = "stem"
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("block_type", item.get("type", "")) or "").strip()
        if block_type in {"text", "markdown"}:
            sid = str(item.get("segment_id", "") or "").strip()
            segment = segment_by_id.get(sid)
            if segment is None:
                flags.append(f"unknown_segment:{sid}")
                continue
            seen_segments.append(sid)
            current_field = str(segment.get("field", "") or "").strip() or current_field
            append_markdown(current_field, str(segment.get("text_md", "") or ""))
            continue
        if block_type == "image":
            aid = str(item.get("asset_id", "") or "").strip()
            asset = asset_by_id.get(aid)
            if asset is None or aid not in expected_assets:
                flags.append(f"unknown_asset:{aid}")
                continue
            seen_assets.append(aid)
            field = str(item.get("field", item.get("scope", "")) or "").strip() or current_field
            append_image(field, asset)

    if seen_segments != expected_segment_ids:
        flags.append("segment_sequence_mismatch")
    if sorted(seen_assets) != sorted(expected_assets):
        flags.append("asset_set_mismatch")
    if len(seen_assets) != len(set(seen_assets)):
        flags.append("duplicate_asset_in_blocks")
    if len(seen_segments) != len(set(seen_segments)):
        flags.append("duplicate_segment_in_blocks")
    if flags:
        return None, normalize_review_flags(flags)
    return blocks, []


def _call_visual_block_layout_review(
    record: dict[str, Any],
    *,
    manifest_path: Path,
    api_key: str,
    model: str,
    model_timeout: int = 60,
) -> dict[str, Any] | None:
    assets = _selected_visual_insert_assets(record)
    should_use, reason = _should_use_visual_block_layout_review(record, assets, manifest_path=manifest_path)
    if not should_use:
        return None
    if not api_key:
        return {"question_id": record.get("question_id", ""), "action": "visual_block_layout_model_not_run_missing_api_key", "reason": reason}
    if len(assets) > 10:
        return {"question_id": record.get("question_id", ""), "action": "visual_block_layout_skipped_too_many_assets", "asset_count": len(assets)}
    question_image_path = _question_image_path(record, manifest_path)
    if not question_image_path or not question_image_path.exists():
        return {"question_id": record.get("question_id", ""), "action": "visual_block_layout_missing_question_image"}
    segments = _build_visual_block_text_segments(record)
    if not segments:
        return {"question_id": record.get("question_id", ""), "action": "visual_block_layout_no_text_segments"}
    if len(segments) > 180:
        return {"question_id": record.get("question_id", ""), "action": "visual_block_layout_skipped_too_many_segments", "segment_count": len(segments)}

    bundle = vision_prompt_store.get_visual_block_layout_review_prompt_bundle()
    asset_lines: list[str] = []
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": "",
        },
        {
            "type": "image_url",
            "image_url": {"url": option_anchor_detection._image_to_data_url(question_image_path)},
        },
    ]
    expected_asset_ids: list[str] = []
    for asset in assets:
        aid = asset_id(asset)
        crop_path = local_path(asset, manifest_path)
        if not aid or not crop_path or not crop_path.exists():
            continue
        expected_asset_ids.append(aid)
        asset_lines.append(
            f"- asset_id={aid}; current_role={asset_role(asset)}; candidate_anchor_key={str(asset.get('candidate_anchor_key', '') or '').strip()}; candidate_anchor_order={int(asset.get('candidate_anchor_order', 0) or 0)}"
        )
        content.append({"type": "text", "text": f"Asset crop: {asset_lines[-1]}"})
        content.append({"type": "image_url", "image_url": {"url": option_anchor_detection._image_to_data_url(crop_path)}})
    if not expected_asset_ids:
        return {"question_id": record.get("question_id", ""), "action": "visual_block_layout_no_materialized_assets"}

    prompt_text = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "TEXT_SEGMENTS": _render_visual_block_segments_for_prompt(segments),
            "ASSET_LINES": "\n".join(asset_lines),
        },
    )
    content[0] = {"type": "text", "text": prompt_text}
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {"role": "user", "content": content},
        ],
    }
    request = urllib.request.Request(
        option_anchor_detection.API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    last_error = ""
    raw = ""
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=max(10, int(model_timeout or 60))) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"http_{exc.code}: {detail}"[:300]
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt >= 3:
                return {
                    "question_id": record.get("question_id", ""),
                    "action": "visual_block_layout_http_error",
                    "error": last_error,
                    "attempt": attempt,
                }
        except Exception as exc:
            last_error = str(exc)[:300]
            if attempt >= 3:
                return {
                    "question_id": record.get("question_id", ""),
                    "action": "visual_block_layout_model_failed",
                    "error": last_error,
                    "attempt": attempt,
                }
        time.sleep(2 * attempt)

    payload = json.loads(raw)
    parsed = option_anchor_detection._extract_json_block(payload["choices"][0]["message"]["content"])
    raw_blocks = parsed.get("blocks", []) if isinstance(parsed.get("blocks", []), list) else []
    content_blocks, validation_flags = _build_content_blocks_from_visual_block_layout(
        record,
        raw_blocks,
        segments=segments,
        expected_asset_ids=expected_asset_ids,
    )
    if content_blocks is None:
        record["visual_block_layout_review"] = {
            "prompt_version": bundle["prompt_version"],
            "trigger_reason": reason,
            "segments": segments,
            "raw_response": payload,
            "global_review_flags": validation_flags,
        }
        return {
            "question_id": record.get("question_id", ""),
            "action": "visual_block_layout_rejected",
            "reason": reason,
            "review_flags": validation_flags,
        }

    qvs = record.get("question_visual_structure", {}) if isinstance(record.get("question_visual_structure"), dict) else {}
    qvs["visual_block_layout_segments"] = segments
    qvs["visual_block_layout_plan"] = raw_blocks
    qvs["content_blocks"] = content_blocks
    qvs["inline_asset_anchor_mode"] = "slot_reflow_v1"
    qvs["review_flags"] = sorted(
        set([str(flag) for flag in (qvs.get("review_flags", []) or [])] + ["visual_block_layout_review_applied"])
    )
    record["question_visual_structure"] = qvs
    record["visual_block_layout_review"] = {
        "prompt_version": bundle["prompt_version"],
        "trigger_reason": reason,
        "segments": segments,
        "blocks": raw_blocks,
        "global_review_flags": [str(flag) for flag in (parsed.get("global_review_flags", []) or []) if str(flag).strip()],
        "raw_response": payload,
    }
    return {
        "question_id": record.get("question_id", ""),
        "action": "visual_block_layout_review_applied",
        "reason": reason,
        "asset_count": len(expected_asset_ids),
        "segment_count": len(segments),
    }


def _call_visual_insert_anchor_review(
    record: dict[str, Any],
    *,
    manifest_path: Path,
    api_key: str,
    model: str,
    model_timeout: int = 60,
) -> dict[str, Any]:
    assets = _selected_visual_insert_assets(record)
    if not assets:
        return {"action": "no_selected_assets"}
    if len(assets) > 10:
        return {"action": "too_many_selected_assets", "asset_count": len(assets)}
    if not api_key:
        return {"action": "model_not_run_missing_api_key"}

    question_image_path = _question_image_path(record, manifest_path)
    if not question_image_path or not question_image_path.exists():
        return {"action": "missing_question_image"}

    bundle = vision_prompt_store.get_visual_insert_anchor_review_prompt_bundle()
    anchor_slot_lines = assetize_question_images.render_visual_insert_anchor_slots_for_prompt(record)
    field_snapshots = _build_anchor_review_field_snapshots(record)
    asset_lines: list[str] = []
    content: list[dict[str, Any]] = []
    content.append(
        {
            "type": "text",
            "text": vision_prompt_store.render_template(
                bundle["user_template"],
                {
                    "STEM_TEXT": field_snapshots["stem"],
                    "ANSWER_TEXT": field_snapshots["answer"],
                    "ANALYSIS_TEXT": field_snapshots["analysis"],
                    "ANCHOR_SLOTS": anchor_slot_lines,
                    "ASSET_LINES": "",
                },
            ),
        }
    )
    content.append(
        {
            "type": "image_url",
            "image_url": {"url": option_anchor_detection._image_to_data_url(question_image_path)},
        }
    )

    for asset in assets:
        aid = asset_id(asset)
        crop_path = local_path(asset, manifest_path)
        if not crop_path or not crop_path.exists():
            continue
        asset_lines.append(
            f"- asset_id={aid}; current_role={asset_role(asset)}; candidate_anchor_key={str(asset.get('candidate_anchor_key', '') or '').strip()}; candidate_anchor_order={int(asset.get('candidate_anchor_order', 0) or 0)}"
        )
        content.append({"type": "text", "text": f"Asset crop: {asset_lines[-1]}"})
        content.append({"type": "image_url", "image_url": {"url": option_anchor_detection._image_to_data_url(crop_path)}})

    if not asset_lines:
        return {"action": "no_materialized_assets_for_review"}

    prompt_text = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "STEM_TEXT": field_snapshots["stem"],
            "ANSWER_TEXT": field_snapshots["answer"],
            "ANALYSIS_TEXT": field_snapshots["analysis"],
            "ANCHOR_SLOTS": anchor_slot_lines,
            "ASSET_LINES": "\n".join(asset_lines),
        },
    )
    content[0] = {"type": "text", "text": prompt_text}

    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {"role": "user", "content": content},
        ],
    }
    request = urllib.request.Request(
        option_anchor_detection.API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    last_error = ""
    raw = ""
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=max(10, int(model_timeout or 60))) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"http_{exc.code}: {detail}"[:300]
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt >= 3:
                return {
                    "question_id": record.get("question_id", ""),
                    "action": "visual_insert_anchor_http_error",
                    "error": last_error,
                    "attempt": attempt,
                }
        except Exception as exc:
            last_error = str(exc)[:300]
            if attempt >= 3:
                return _apply_visual_insert_anchor_fallback(
                    record,
                    bundle=bundle,
                    error=last_error,
                    reason_flag="visual_insert_anchor_model_failed",
                    attempt=attempt,
                )
        time.sleep(2 * attempt)
    try:
        payload = json.loads(raw)
        parsed = option_anchor_detection._extract_json_block(payload["choices"][0]["message"]["content"])
    except Exception as exc:
        return _apply_visual_insert_anchor_fallback(
            record,
            bundle=bundle,
            error=f"visual_insert_anchor_bad_json: {exc}",
            reason_flag="visual_insert_anchor_bad_json_fallback",
            attempt=None,
        )
    placements = parsed.get("placements", []) if isinstance(parsed.get("placements", []), list) else []
    normalized_plan = _normalize_visual_anchor_plan(record, placements)
    qvs = record.get("question_visual_structure", {}) if isinstance(record.get("question_visual_structure"), dict) else {}
    qvs["visual_insert_anchor_slots"] = assetize_question_images.build_visual_insert_anchor_slots(record)
    qvs["visual_insert_anchor_plan"] = normalized_plan
    qvs["content_blocks"] = assetize_question_images.build_content_blocks_from_visual_insert_anchor_plan(record, normalized_plan)
    qvs["inline_asset_anchor_mode"] = "slot_reflow_v1"
    qvs["review_flags"] = sorted(
        set([str(flag) for flag in (qvs.get("review_flags", []) or [])] + ["visual_insert_anchor_review_applied"])
    )
    record["question_visual_structure"] = qvs
    record["visual_insert_anchor_review"] = {
        "prompt_version": bundle["prompt_version"],
        "available_slots": qvs["visual_insert_anchor_slots"],
        "placements": normalized_plan,
        "global_review_flags": [str(flag) for flag in (parsed.get("global_review_flags", []) or []) if str(flag).strip()],
        "raw_response": payload,
    }
    return {
        "question_id": record.get("question_id", ""),
        "action": "visual_insert_anchor_review_applied",
        "asset_count": len(normalized_plan),
    }


def cropped_by_role(record: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [
        item
        for item in (record.get("assets", []) or [])
        if isinstance(item, dict) and is_cropped_asset(item) and asset_role(item) == role
    ]


def clone_for_role(asset: dict[str, Any], role: str, index: int, reason: str) -> dict[str, Any]:
    cloned = deepcopy(asset)
    old_id = str(asset.get("asset_id", "") or f"asset_{index:03d}")
    new_id = f"{old_id}__as_{role}_{index:03d}"
    cloned["asset_id"] = new_id
    cloned["asset_role"] = role
    cloned["role"] = role
    cloned["placement_scope"] = "after_stem" if role == "stem" else "after_analysis"
    cloned["placement"] = cloned["placement_scope"]
    cloned["display_ref"] = f"asset://{new_id}"
    cloned["attach_status"] = "attached"
    cloned["ownership_relinked_from_asset_id"] = old_id
    cloned["ownership_relink_reason"] = reason
    cloned["review_flags"] = sorted(
        set([str(f) for f in (cloned.get("review_flags", []) or [])] + [f"asset_ownership_relinked_to_{role}"])
    )
    debug = cloned.get("debug", {}) if isinstance(cloned.get("debug"), dict) else {}
    debug["ownership_relinked_from_asset_id"] = old_id
    cloned["debug"] = debug
    return cloned


def asset_id(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_id", "") or "").strip()


def scope_alias_ids(record: dict[str, Any], scope: str) -> list[str]:
    aliases = record.get("scope_asset_aliases", {}) if isinstance(record.get("scope_asset_aliases"), dict) else {}
    values = aliases.get(scope, []) if isinstance(aliases.get(scope), list) else []
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def asset_score(asset: dict[str, Any]) -> float:
    score = float(asset.get("confidence", 0.0) or 0.0)
    flags = {str(flag) for flag in (asset.get("review_flags", []) or [])}
    audit = asset.get("bbox_audit", {}) if isinstance(asset.get("bbox_audit"), dict) else {}
    if "final_asset_quality_refined_by_model" in flags:
        score += 0.08
    if "final_asset_quality_panel_group_skip" in flags:
        score += 0.02
    if "bbox_audit_suspect" in flags or str(audit.get("validity", "") or "") == "suspect":
        score -= 0.08
    if "final_asset_quality_model_failed" in flags:
        score -= 0.1
    if "final_asset_quality_shrink_rejected_keep_current" in flags:
        score -= 0.04
    return round(score, 4)


def dedupe_scope_assets(assets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for asset in assets:
        key = str(asset.get("storage_key", "") or "").strip() or asset_id(asset)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = asset
            kept.append(asset)
            continue
        if asset_score(asset) > asset_score(existing):
            removed.append(existing)
            kept = [item for item in kept if item is not existing]
            by_key[key] = asset
            kept.append(asset)
        else:
            removed.append(asset)
    kept.sort(key=lambda item: (-asset_score(item), asset_id(item)))
    return kept, removed


def compact_evidence_assets(record: dict[str, Any]) -> list[dict[str, Any]]:
    assets = record.get("assets", []) if isinstance(record.get("assets"), list) else []
    evidence_assets = [
        item
        for item in assets
        if isinstance(item, dict) and placement(item) == "evidence_only" and is_materialized(item)
    ]
    if not evidence_assets:
        return []
    selected = sorted(
        evidence_assets,
        key=lambda item: (
            assetize_question_images.EVIDENCE_ROLE_PRIORITY.get(asset_role(item), 0),
            asset_score(item),
            asset_id(item),
        ),
        reverse=True,
    )[0]
    selected_ids = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    selected_ids["evidence"] = [asset_id(selected)] if asset_id(selected) else []
    record["selected_scope_asset_ids"] = selected_ids
    actions: list[dict[str, Any]] = []
    for asset in evidence_assets:
        if asset is selected:
            continue
        actions.append(
            {
                "question_id": record.get("question_id", ""),
                "action": "drop_extra_evidence_asset",
                "removed_asset_id": asset_id(asset),
                "kept_asset_id": asset_id(selected),
            }
        )
    return actions


def select_delivery_assets(record: dict[str, Any]) -> list[dict[str, Any]]:
    assets = record.get("assets", []) if isinstance(record.get("assets"), list) else []
    selected = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    scope = record.get("figure_detection_scope", {}) if isinstance(record.get("figure_detection_scope"), dict) else {}
    scope_stem = bool(scope.get("stem", False))
    scope_analysis = bool(scope.get("analysis", False))

    direct_stem = cropped_by_role(record, "stem")
    direct_analysis = cropped_by_role(record, "analysis")
    direct_option = cropped_by_role(record, "option")

    stem_selected, stem_removed = dedupe_scope_assets(direct_stem)
    analysis_selected, analysis_removed = dedupe_scope_assets(direct_analysis)

    alias_map = record.get("scope_asset_aliases", {}) if isinstance(record.get("scope_asset_aliases"), dict) else {}
    stem_alias = scope_alias_ids(record, "stem")
    analysis_alias = scope_alias_ids(record, "analysis")

    if stem_selected:
        selected["stem"] = [asset_id(item) for item in stem_selected if asset_id(item)]
    elif stem_alias:
        selected["stem"] = stem_alias
    else:
        selected["stem"] = []

    if analysis_selected and (scope_analysis or bool(record.get("analysis_requires_image", False))):
        selected["analysis"] = [asset_id(item) for item in analysis_selected if asset_id(item)]
    elif analysis_alias:
        selected["analysis"] = analysis_alias
    else:
        selected["analysis"] = []

    option_by_key: dict[str, list[str]] = {}
    option_removed: list[dict[str, Any]] = []
    option_groups: dict[str, list[dict[str, Any]]] = {}
    for asset in direct_option:
        option_key = str(asset.get("option_key", "") or "").strip().upper() or "_"
        option_groups.setdefault(option_key, []).append(asset)
    for option_key, group in option_groups.items():
        kept_group, removed_group = dedupe_scope_assets(group)
        if option_key != "_":
            option_by_key[option_key] = [asset_id(item) for item in kept_group if asset_id(item)]
        option_removed.extend(removed_group)
    selected["option_by_key"] = option_by_key
    record["selected_scope_asset_ids"] = selected

    keep_ids: set[str] = set()
    for scope_name in ("evidence", "stem", "analysis"):
        keep_ids.update([str(item or "").strip() for item in selected.get(scope_name, []) if str(item or "").strip()])
    for values in option_by_key.values():
        keep_ids.update([str(item or "").strip() for item in values if str(item or "").strip()])

    actions: list[dict[str, Any]] = []
    for asset in stem_removed + analysis_removed + option_removed:
        aid = asset_id(asset)
        if not aid or aid in keep_ids:
            continue
        actions.append(
            {
                "question_id": record.get("question_id", ""),
                "action": "drop_duplicate_cropped_asset",
                "removed_asset_id": aid,
                "storage_key": str(asset.get("storage_key", "") or ""),
            }
        )

    record["assets"] = [
        asset
        for asset in assets
        if not isinstance(asset, dict) or asset_id(asset) in keep_ids
    ]
    if alias_map:
        record["scope_asset_aliases"] = alias_map
    return actions


def reconcile_ownership(record: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    scope = record.get("figure_detection_scope", {}) if isinstance(record.get("figure_detection_scope"), dict) else {}
    scope_stem = bool(scope.get("stem", False))
    scope_analysis = bool(scope.get("analysis", False))

    stem_assets = cropped_by_role(record, "stem")
    analysis_assets = cropped_by_role(record, "analysis")
    option_assets = cropped_by_role(record, "option")
    aliases = record.get("scope_asset_aliases", {}) if isinstance(record.get("scope_asset_aliases"), dict) else {}

    if scope_stem and not stem_assets and not option_assets and analysis_assets:
        candidates = [a for a in analysis_assets if str(a.get("bbox_space", "") or "") == "question_image"] or analysis_assets
        aliases["stem"] = [asset_id(asset) for asset in candidates if asset_id(asset)]
        for asset in candidates:
            actions.append(
                {
                    "question_id": record.get("question_id", ""),
                    "action": "reuse_analysis_asset_for_stem",
                    "source_asset_id": asset.get("asset_id", ""),
                }
            )

    stem_assets = cropped_by_role(record, "stem")
    analysis_assets = cropped_by_role(record, "analysis")
    if scope_analysis and not analysis_assets and stem_assets:
        candidates = [a for a in stem_assets if str(a.get("bbox_space", "") or "") == "question_image"] or stem_assets
        aliases["analysis"] = [asset_id(asset) for asset in candidates if asset_id(asset)]
        for asset in candidates:
            actions.append(
                {
                    "question_id": record.get("question_id", ""),
                    "action": "reuse_stem_asset_for_analysis",
                    "source_asset_id": asset.get("asset_id", ""),
                }
            )

    if aliases:
        record["scope_asset_aliases"] = aliases
    if actions:
        record["asset_ownership_reconcile_actions"] = actions
    return actions


def valid_bbox(
    raw: Any,
    width: int,
    height: int,
    *,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, dict):
        return None
    try:
        x_raw = float(raw.get("x", 0) or 0)
        y_raw = float(raw.get("y", 0) or 0)
        w_raw = float(raw.get("w", 0) or 0)
        h_raw = float(raw.get("h", 0) or 0)
    except Exception:
        return None
    if canvas_width and canvas_height and canvas_width > 0 and canvas_height > 0:
        scale_x = width / float(canvas_width)
        scale_y = height / float(canvas_height)
        x = int(round(x_raw * scale_x))
        y = int(round(y_raw * scale_y))
        w = int(round(w_raw * scale_x))
        h = int(round(h_raw * scale_y))
    else:
        x = int(round(x_raw))
        y = int(round(y_raw))
        w = int(round(w_raw))
        h = int(round(h_raw))
    if w <= 0 or h <= 0:
        return None
    x1 = max(0, min(x, width - 1))
    y1 = max(0, min(y, height - 1))
    x2 = max(x1 + 1, min(x + w, width))
    y2 = max(y1 + 1, min(y + h, height))
    return x1, y1, x2, y2


def expand_bbox_for_safe_crop(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    edge_x = max(12, int(round(width * 0.02)))
    edge_y = max(12, int(round(height * 0.02)))

    left_pad = max(8, int(round(box_w * 0.04)))
    right_pad = max(8, int(round(box_w * 0.04)))
    top_pad = max(12, int(round(box_h * 0.12)))
    bottom_pad = max(8, int(round(box_h * 0.06)))

    if x1 <= edge_x:
        left_pad = max(left_pad, int(round(box_w * 0.08)))
    if x2 >= width - edge_x:
        right_pad = max(right_pad, int(round(box_w * 0.08)))
    if y1 <= edge_y:
        top_pad = max(top_pad, int(round(box_h * 0.18)))
    if y2 >= height - edge_y:
        bottom_pad = max(bottom_pad, int(round(box_h * 0.1)))

    nx1 = max(0, x1 - left_pad)
    ny1 = max(0, y1 - top_pad)
    nx2 = min(width, x2 + right_pad)
    ny2 = min(height, y2 + bottom_pad)
    return nx1, ny1, max(nx1 + 1, nx2), max(ny1 + 1, ny2)


def refine_asset(
    record: dict[str, Any],
    asset: dict[str, Any],
    *,
    manifest_path: Path,
    out_dir: Path,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    qid = str(record.get("question_id", "") or "question")
    aid = str(asset.get("asset_id", "") or "asset")
    debug = asset.get("debug", {}) if isinstance(asset.get("debug"), dict) else {}
    path: Path | None = None
    refine_input_source = "local_path"
    pre_final_raw = str(debug.get("pre_final_refine_local_path", "") or "").strip()
    if pre_final_raw:
        pre_final_path = Path(pre_final_raw)
        if pre_final_path.exists():
            path = pre_final_path
            refine_input_source = "pre_final_refine_local_path"
    if not path:
        path = local_path(asset, manifest_path)
    flags = [str(f) for f in (asset.get("review_flags", []) or [])]
    if not path:
        asset["review_flags"] = sorted(set(flags + ["final_asset_quality_missing_local_path"]))
        return {"question_id": qid, "asset_id": aid, "action": "missing_local_path"}
    if not api_key:
        asset["review_flags"] = sorted(set(flags + ["final_asset_quality_model_not_run_missing_api_key"]))
        return {"question_id": qid, "asset_id": aid, "action": "model_not_run_missing_api_key"}
    try:
        with Image.open(path) as im:
            image = im.convert("RGB")
            width, height = image.size
            debug["final_refine_contract"] = "single_candidate_refine_v0.1"
            debug["final_refine_input_width"] = width
            debug["final_refine_input_height"] = height
            payload = option_anchor_detection._call_inline_figure_refine_model(api_key, model, image)
            asset["final_asset_quality_model_payload"] = payload
            if not bool(payload.get("is_valid_figure", True)):
                debug["final_refine_action"] = "model_invalid_figure"
                asset["debug"] = debug
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_model_invalid_figure"]))
                return {"question_id": qid, "asset_id": aid, "action": "model_invalid_figure"}
            bbox = valid_bbox(
                payload.get("bbox", {}),
                width,
                height,
                canvas_width=int(payload.get("image_width", 0) or 0),
                canvas_height=int(payload.get("image_height", 0) or 0),
            )
            if not bbox:
                debug["final_refine_action"] = "bbox_invalid"
                asset["debug"] = debug
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_bbox_invalid"]))
                return {"question_id": qid, "asset_id": aid, "action": "bbox_invalid"}
            x1, y1, x2, y2 = bbox
            area_ratio = ((x2 - x1) * (y2 - y1)) / max(width * height, 1)
            if area_ratio < 0.55:
                debug["final_refine_action"] = "shrink_rejected_keep_current"
                debug["final_refine_rejected_bbox"] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
                debug["final_refine_rejected_area_ratio"] = round(area_ratio, 4)
                asset["debug"] = debug
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_shrink_rejected_keep_current"]))
                return {
                    "question_id": qid,
                    "asset_id": aid,
                    "action": "shrink_rejected_keep_current",
                    "area_ratio": round(area_ratio, 4),
                }
            if area_ratio > 0.985 and x1 <= 2 and y1 <= 2:
                debug["final_refine_action"] = "checked_no_change"
                asset["debug"] = debug
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_checked_no_change"]))
                return {"question_id": qid, "asset_id": aid, "action": "checked_no_change"}
            refined_bbox = expand_bbox_for_safe_crop((x1, y1, x2, y2), width, height)
            rx1, ry1, rx2, ry2 = refined_bbox
            refined = image.crop((rx1, ry1, rx2, ry2))
            refined_dir = out_dir / "refined_assets" / qid
            refined_dir.mkdir(parents=True, exist_ok=True)
            refined_path = refined_dir / f"{aid}.png"
            refined.save(refined_path)
            debug["pre_final_refine_local_path"] = str(path)
            debug["local_path"] = str(refined_path)
            debug["final_refine_input_source"] = refine_input_source
            debug["final_refine_original_bbox"] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
            debug["final_refine_expanded_bbox"] = {"x1": rx1, "y1": ry1, "x2": rx2, "y2": ry2}
            debug["final_refine_action"] = "refined_by_model"
            asset["debug"] = debug
            refined_storage_key = str(refined_path.relative_to(out_dir)).replace("\\", "/")
            asset["storage_key"] = refined_storage_key
            asset["review_storage_key"] = refined_storage_key
            asset["delivery_storage_key"] = refined_storage_key
            asset["image_width"] = refined.width
            asset["image_height"] = refined.height
            asset["review_flags"] = sorted(set(flags + ["final_asset_quality_refined_by_model"]))
            return {
                "question_id": qid,
                "asset_id": aid,
                "action": "refined_by_model",
                "area_ratio": round(area_ratio, 4),
                "refine_input_source": refine_input_source,
            }
    except Exception as exc:
        debug["final_refine_action"] = "model_failed"
        debug["final_refine_error"] = str(exc)[:240]
        asset["debug"] = debug
        asset["review_flags"] = sorted(set(flags + ["final_asset_quality_model_failed"]))
        return {"question_id": qid, "asset_id": aid, "action": "model_failed", "error": str(exc)[:240]}


def image_data_url(path: Path) -> str:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def render_review(records: list[dict[str, Any]], manifest_path: Path) -> str:
    cards: list[str] = []
    for record in records:
        qid = html.escape(str(record.get("question_id", "") or ""))
        cropped = [a for a in (record.get("assets", []) or []) if isinstance(a, dict) and is_cropped_asset(a)]
        if not cropped:
            continue
        imgs: list[str] = []
        for asset in cropped:
            path = local_path(asset, manifest_path)
            if not path:
                continue
            flags = ", ".join(str(f) for f in (asset.get("review_flags", []) or []))
            imgs.append(
                "<figure>"
                f"<img src='{image_data_url(path)}'>"
                f"<figcaption>{html.escape(asset_role(asset))} | {html.escape(str(asset.get('asset_id','')))}<br>{html.escape(flags)}</figcaption>"
                "</figure>"
            )
        cards.append(f"<section><h2>{qid}</h2><div class='assets'>{''.join(imgs)}</div></section>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Asset Ownership Reconcile & Final Quality Review</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;background:#f6f3ed;color:#172033;margin:24px}}
section{{background:white;border:1px solid #ded4c6;border-radius:14px;padding:16px;margin:0 0 18px}}
h2{{font-size:18px;margin:0 0 12px}}
.assets{{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}}
figure{{margin:0;border:1px solid #d9e0ec;border-radius:10px;padding:10px;background:#fbfdff;max-width:360px}}
img{{max-width:330px;max-height:260px;display:block;margin:auto}}
figcaption{{font-size:12px;line-height:1.45;color:#4a5870;margin-top:8px;word-break:break-all}}
</style>
</head>
<body>
<h1>Asset Ownership Reconcile & Final Quality Review</h1>
{''.join(cards)}
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--model-timeout", type=int, default=60)
    parser.add_argument("--skip-model-refine", action="store_true")
    parser.add_argument("--skip-visual-insert-anchor-review", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = read_json(manifest_path)
    records = payload.get("questions", []) if isinstance(payload.get("questions"), list) else []

    ownership_actions: list[dict[str, Any]] = []
    quality_actions: list[dict[str, Any]] = []
    selection_actions: list[dict[str, Any]] = []
    visual_anchor_actions: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        ownership_actions.extend(reconcile_ownership(record))
        for asset in list(record.get("assets", []) or []):
            if not isinstance(asset, dict) or not is_cropped_asset(asset):
                continue
            if is_panel_group_asset(asset):
                asset["review_flags"] = sorted(
                    set([str(f) for f in (asset.get("review_flags", []) or [])] + ["final_asset_quality_panel_group_skip"])
                )
                continue
            if args.skip_model_refine:
                asset["review_flags"] = sorted(
                    set([str(f) for f in (asset.get("review_flags", []) or [])] + ["final_asset_quality_model_skipped"])
                )
                continue
            quality_actions.append(
                refine_asset(
                    record,
                    asset,
                    manifest_path=manifest_path,
                    out_dir=out_dir,
                    api_key=str(args.api_key or ""),
                    model=str(args.model or ""),
                )
            )
        selection_actions.extend(compact_evidence_assets(record))
        selection_actions.extend(select_delivery_assets(record))
        if not args.skip_visual_insert_anchor_review:
            block_layout_action = _call_visual_block_layout_review(
                record,
                manifest_path=manifest_path,
                api_key=str(args.api_key or ""),
                model=str(args.model or ""),
                model_timeout=int(args.model_timeout or 60),
            )
            if block_layout_action is not None:
                visual_anchor_actions.append(block_layout_action)
            if not block_layout_action or str(block_layout_action.get("action", "") or "") != "visual_block_layout_review_applied":
                visual_anchor_actions.append(
                    _call_visual_insert_anchor_review(
                        record,
                        manifest_path=manifest_path,
                        api_key=str(args.api_key or ""),
                        model=str(args.model or ""),
                        model_timeout=int(args.model_timeout or 60),
                    )
                )
        try:
            record["display_blocks"] = assetize_question_images.build_display_blocks(record)
            record["display_markdown"] = (
                assetize_question_images.build_qvs_display_markdown(
                    record.get("question_visual_structure", {}) if isinstance(record.get("question_visual_structure"), dict) else {},
                    record,
                )
                or assetize_question_images.build_markdown(record)
            )
        except Exception as exc:
            record["display_rebuild_error"] = str(exc)[:240]

    payload["questions"] = records
    payload["asset_ownership_reconcile"] = {
        "schema_version": "asset_ownership_reconcile.v0.1",
        "action_count": len(ownership_actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in ownership_actions)),
    }
    payload["final_asset_quality"] = {
        "schema_version": "final_asset_quality.v0.1",
        "action_count": len(quality_actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in quality_actions)),
        "model_refine_enabled": not args.skip_model_refine and bool(str(args.api_key or "")),
    }
    payload["delivery_asset_selection"] = {
        "schema_version": "delivery_asset_selection.v0.1",
        "action_count": len(selection_actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in selection_actions)),
    }
    payload["visual_insert_anchor_review"] = {
        "schema_version": "visual_insert_anchor_review.v0.1",
        "action_count": len(visual_anchor_actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in visual_anchor_actions)),
        "model_review_enabled": not args.skip_visual_insert_anchor_review and bool(str(args.api_key or "")),
    }
    out_manifest = out_dir / "reconciled_refined_manifest.json"
    write_json(out_manifest, payload)
    write_json(out_dir / "ownership_actions.json", ownership_actions)
    write_json(out_dir / "quality_actions.json", quality_actions)
    write_json(out_dir / "selection_actions.json", selection_actions)
    write_json(out_dir / "visual_insert_anchor_actions.json", visual_anchor_actions)
    summary = {
        "manifest": str(out_manifest),
        "ownership_action_count": len(ownership_actions),
        "ownership_action_counts": dict(Counter(str(a.get("action", "")) for a in ownership_actions)),
        "quality_action_count": len(quality_actions),
        "quality_action_counts": dict(Counter(str(a.get("action", "")) for a in quality_actions)),
        "selection_action_count": len(selection_actions),
        "selection_action_counts": dict(Counter(str(a.get("action", "")) for a in selection_actions)),
        "visual_anchor_action_count": len(visual_anchor_actions),
        "visual_anchor_action_counts": dict(Counter(str(a.get("action", "")) for a in visual_anchor_actions)),
    }
    write_json(out_dir / "reconcile_refine_summary.json", summary)
    (out_dir / "reconcile_refine_review.html").write_text(render_review(records, out_manifest), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
