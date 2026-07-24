from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image

import option_choice_gating
import option_crop_staging
from question_visual_structure_contract import (
    make_display_ref,
    make_stable_asset_id,
    make_storage_key,
    normalize_review_flags,
)


DEFAULT_OPTION_ANCHOR_MODEL = "doubao-seed-2-0-lite-260428"
OPTION_KEYS = ("A", "B", "C", "D")


def _option_anchor_detection():
    import option_anchor_detection

    return option_anchor_detection


def safe_slug(text: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(text or "").strip())
    value = value.strip("._-")
    return value[:80].rstrip("._-") or "item"


def _bbox_iou(a: dict, b: dict) -> float:
    ax1 = int(a.get("x", 0) or 0)
    ay1 = int(a.get("y", 0) or 0)
    ax2 = ax1 + int(a.get("w", 0) or 0)
    ay2 = ay1 + int(a.get("h", 0) or 0)
    bx1 = int(b.get("x", 0) or 0)
    by1 = int(b.get("y", 0) or 0)
    bx2 = bx1 + int(b.get("w", 0) or 0)
    by2 = by1 + int(b.get("h", 0) or 0)
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(ax2 - ax1, 0) * max(ay2 - ay1, 0)
    area_b = max(bx2 - bx1, 0) * max(by2 - by1, 0)
    return inter / max(area_a + area_b - inter, 1)


def _suppress_public_boxes_owned_by_options(public_boxes: list[dict], option_blocks: list[dict]) -> list[dict]:
    option_boxes: list[dict] = []
    for block in option_blocks or []:
        bbox_space = str(block.get("bbox_space", "") or "")
        for image_bbox in block.get("image_bboxes", []) or []:
            if not isinstance(image_bbox, dict):
                continue
            if int(image_bbox.get("w", 0) or 0) <= 0 or int(image_bbox.get("h", 0) or 0) <= 0:
                continue
            option_boxes.append({**image_bbox, "bbox_space": bbox_space})
    if not option_boxes:
        return public_boxes

    kept: list[dict] = []
    for public_box in public_boxes or []:
        public_space = str(public_box.get("bbox_space", "") or "")
        overlaps_option = any(
            public_space == str(option_box.get("bbox_space", "") or "")
            and _bbox_iou(public_box, option_box) >= 0.42
            for option_box in option_boxes
        )
        if overlaps_option:
            continue
        kept.append(public_box)
    return kept


def _empty_detection() -> dict:
    return {
        "option_visual_blocks": [],
        "stem_image_bboxes": [],
        "analysis_image_bboxes": [],
        "unassigned_image_bboxes": [],
        "global_review_flags": [],
    }


def _planner_scope(question: dict) -> dict:
    """Use the model planner as the authority for which image branches may run."""
    gate = question.get("image_need_gate")
    if not isinstance(gate, dict):
        return {
            "option": True,
            "stem": True,
            "analysis": True,
            "reason": "no_planner_gate_conservative",
            "where": [],
            "image_presence": "",
        }

    where_raw = gate.get("where", [])
    alias = {
        "stem": "stem",
        "question": "stem",
        "public": "stem",
        "public_figure": "stem",
        "题干": "stem",
        "option": "options",
        "options": "options",
        "choice": "options",
        "choices": "options",
        "选项": "options",
        "answer": "analysis",
        "answers": "analysis",
        "solution": "analysis",
        "solutions": "analysis",
        "explanation": "analysis",
        "analysis": "analysis",
        "解析": "analysis",
        "解答": "analysis",
        "答案": "analysis",
        "证明": "analysis",
    }
    where = {
        alias.get(str(item or "").strip().lower(), "")
        for item in (where_raw if isinstance(where_raw, list) else [])
        if str(item or "").strip()
    }
    where.discard("")
    image_presence = str(gate.get("image_presence", "") or "").strip().lower()

    if not bool(gate.get("needs_figure_detection", False)):
        return {
            "option": False,
            "stem": False,
            "analysis": False,
            "reason": "planner_no_figure",
            "where": sorted(where),
            "image_presence": image_presence,
        }

    if not where:
        return {
            "option": True,
            "stem": True,
            "analysis": True,
            "reason": "planner_uncertain_conservative",
            "where": [],
            "image_presence": image_presence,
        }

    return {
        "option": "options" in where,
        "stem": "stem" in where,
        "analysis": "analysis" in where,
        "reason": "planner_where_scope",
        "where": sorted(where),
        "image_presence": image_presence,
    }


def _filter_public_review_flags(flags: list, scope: dict) -> list:
    kept: list = []
    for flag in flags or []:
        value = str(flag or "")
        if not scope.get("stem", True) and "public_stem_image_detected" in value:
            continue
        if not scope.get("analysis", True) and "public_analysis_image_detected" in value:
            continue
        kept.append(flag)
    return kept


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_mineru_content_list(run_dir: Path) -> Path | None:
    primary = sorted(path for path in run_dir.rglob("*_content_list.json") if not path.name.endswith("_v2.json"))
    if primary:
        return primary[0]
    candidates = sorted(run_dir.rglob("*content_list*.json"))
    return candidates[0] if candidates else None


def _option_key_from_text(text: str) -> str:
    value = str(text or "").strip().upper()
    for key in OPTION_KEYS:
        if value == key or value.startswith(f"{key}.") or value.startswith(f"{key}．") or value.startswith(f"{key}、"):
            return key
    return ""


def _image_size_or_zero(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except Exception:
        return 0, 0


def _make_mineru_external_asset(
    *,
    question_uid: str,
    runtime_run_id: str,
    option_key: str,
    ordinal: int,
    external_path: Path,
    explicit_key: bool,
    mineru_item: dict,
) -> dict:
    suffix = external_path.suffix.lower() if external_path.suffix else ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    width, height = _image_size_or_zero(external_path)
    asset_id = make_stable_asset_id(question_uid, "option", option_key=option_key, ordinal=ordinal)
    flags = [
        "mineru_fallback",
        "figure_detection_zero_assets_recovered",
        "mineru_option_key_from_nearest_text" if explicit_key else "mineru_option_key_inferred_by_order",
    ]
    return {
        "asset_id": asset_id,
        "asset_role": "option",
        "runtime_run_id": str(runtime_run_id or "").strip(),
        "placement_scope": "option_inline",
        "option_key": option_key,
        "candidate_option_key": option_key,
        "storage_key": make_storage_key(
            question_uid,
            "option",
            option_key=option_key,
            ordinal=ordinal,
            suffix=suffix,
            runtime_run_id=runtime_run_id,
        ),
        "display_ref": make_display_ref(asset_id),
        "mime_type": "image/jpeg" if suffix in {".jpg", ".jpeg"} else f"image/{suffix.lstrip('.')}",
        "bbox_space": "option_crop",
        "bbox_json": {},
        "image_width": width,
        "image_height": height,
        "source_image_role": "question_image",
        "page_no": 1,
        "confidence": 0.84 if explicit_key else 0.78,
        "attach_status": "attached",
        "materialized": False,
        "file_status": "planned",
        "review_flags": normalize_review_flags(flags),
        "detector_source": "mineru_fallback",
        "crop_policy": "external_mineru_option_image",
        "external_label_kind": "option_key",
        "external_label_text": option_key,
        "external_asset_path": str(external_path.resolve()),
        "external_asset_source": "mineru",
        "mineru_bbox_raw": mineru_item.get("bbox", []),
        "mineru_page_idx": mineru_item.get("page_idx", 0),
        "mineru_content_order": mineru_item.get("_content_order", ordinal),
    }


def _build_mineru_fallback_assets(
    question: dict,
    *,
    question_uid: str,
    runtime_run_id: str,
    mineru_exe: str,
    mineru_api_url: str,
    mineru_out_dir: Path,
    mineru_timeout_seconds: int,
) -> tuple[list[dict], dict]:
    question_id = str(question.get("question_id", "") or question.get("record_id", "") or question_uid)
    source_raw = str(question.get("question_image", "") or question.get("stem_image", "") or "").strip()
    if not source_raw:
        return [], {"action": "mineru_fallback_failed", "reason": "missing_source_image"}
    source_path = Path(source_raw)
    if not source_path.exists():
        return [], {"action": "mineru_fallback_failed", "reason": "source_image_not_found", "source_image": source_raw}

    run_dir = mineru_out_dir / safe_slug(question_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(mineru_exe or "mineru"),
        "-p",
        str(source_path),
        "-o",
        str(run_dir),
        "-b",
        "pipeline",
        "-m",
        "ocr",
        "-l",
        "ch",
    ]
    if str(mineru_api_url or "").strip():
        cmd.extend(["--api-url", str(mineru_api_url).strip()])

    env = os.environ.copy()
    env.setdefault("NO_PROXY", "*")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            text=True,
            capture_output=True,
            timeout=max(30, int(mineru_timeout_seconds or 240)),
        )
    except Exception as exc:
        return [], {
            "action": "mineru_fallback_failed",
            "reason": "mineru_command_failed",
            "error": str(exc)[:500],
            "cmd": cmd,
            "raw_output_dir": str(run_dir),
        }
    if proc.returncode != 0:
        return [], {
            "action": "mineru_fallback_failed",
            "reason": "mineru_nonzero_exit",
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-1200:],
            "stderr_tail": (proc.stderr or "")[-1200:],
            "cmd": cmd,
            "raw_output_dir": str(run_dir),
        }

    content_list = _find_mineru_content_list(run_dir)
    if content_list is None:
        return [], {
            "action": "mineru_fallback_no_images",
            "reason": "content_list_missing",
            "returncode": proc.returncode,
            "raw_output_dir": str(run_dir),
        }
    data = read_json(content_list)
    if not isinstance(data, list):
        return [], {
            "action": "mineru_fallback_no_images",
            "reason": "content_list_not_list",
            "content_list": str(content_list),
            "raw_output_dir": str(run_dir),
        }

    base_dir = content_list.parent
    image_items: list[dict] = []
    recent_key = ""
    for order, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "") or "").strip().lower()
        if item_type == "text":
            key = _option_key_from_text(str(item.get("text", "") or ""))
            if key:
                recent_key = key
            continue
        if item_type != "image":
            continue
        raw_img = str(item.get("img_path", "") or "").strip()
        if not raw_img:
            continue
        image_path = (base_dir / raw_img).resolve()
        if not image_path.exists():
            continue
        image_items.append({**item, "_content_order": order, "_nearest_option_key": recent_key})
        recent_key = ""

    if not image_items:
        return [], {
            "action": "mineru_fallback_no_images",
            "reason": "no_image_items",
            "content_list": str(content_list),
            "raw_output_dir": str(run_dir),
        }

    explicit_count = sum(1 for item in image_items if str(item.get("_nearest_option_key", "") or "") in OPTION_KEYS)
    infer_by_order = explicit_count == 0 and len(image_items) == 4
    used_ordinals: dict[str, int] = {}
    staged: list[dict] = []
    for idx, item in enumerate(image_items, start=1):
        option_key = str(item.get("_nearest_option_key", "") or "").upper()
        explicit_key = option_key in OPTION_KEYS
        if not explicit_key and infer_by_order:
            option_key = OPTION_KEYS[idx - 1]
        if option_key not in OPTION_KEYS:
            continue
        raw_img = str(item.get("img_path", "") or "").strip()
        external_path = (base_dir / raw_img).resolve()
        used_ordinals[option_key] = used_ordinals.get(option_key, 0) + 1
        staged.append(
            _make_mineru_external_asset(
                question_uid=question_uid,
                runtime_run_id=runtime_run_id,
                option_key=option_key,
                ordinal=used_ordinals[option_key],
                external_path=external_path,
                explicit_key=explicit_key,
                mineru_item=item,
            )
        )

    action = {
        "action": "mineru_fallback_used" if staged else "mineru_fallback_no_images",
        "question_id": question_id,
        "source_image": str(source_path),
        "content_list": str(content_list),
        "raw_output_dir": str(run_dir),
        "image_item_count": len(image_items),
        "staged_asset_count": len(staged),
        "explicit_option_key_count": explicit_count,
        "inferred_by_order": infer_by_order,
    }
    return staged, action


def _should_try_mineru_fallback(question: dict, planner_scope: dict, detection: dict, staged_assets: list[dict]) -> bool:
    if staged_assets:
        return False
    if not bool(planner_scope.get("option", False)):
        return False
    gate = question.get("image_need_gate") if isinstance(question.get("image_need_gate"), dict) else {}
    if not bool(gate.get("needs_figure_detection", False)):
        return False
    flags = {str(flag) for flag in (detection.get("global_review_flags", []) or [])}
    return bool(flags.intersection({"option_anchor_missing", "figure_detection_zero_assets"})) or not (
        detection.get("option_visual_blocks", []) or []
    )


def safe_progress_print(payload: object) -> None:
    """Progress printing must never turn a completed question into a failed one."""
    try:
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    except OSError as exc:
        try:
            print(
                json.dumps(
                    {
                        "event": "progress_print_failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=False,
            )
        except Exception:
            pass


def append_jsonl(path: Path | None, payload: object) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()


def write_partial_payload(
    path: Path | None,
    source_payload: dict,
    *,
    source_json_path: Path,
    runtime_run_id: str,
    option_anchor_mode: str,
    require_vision_figure_model: bool,
    allow_heuristic_figure_fallback: bool,
    enable_mineru_fallback: bool,
    enriched_questions: list[dict],
    debug_rows: list[dict],
    current_index: int,
    total_count: int,
) -> None:
    if path is None:
        return
    write_json(
        path,
        {
            **source_payload,
            "schema_version": "option_visual_source.partial.v1.1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_json": str(source_json_path),
            "runtime_run_id": runtime_run_id,
            "option_anchor_mode": option_anchor_mode,
            "require_vision_figure_model": require_vision_figure_model,
            "allow_heuristic_figure_fallback": allow_heuristic_figure_fallback,
            "enable_mineru_fallback": enable_mineru_fallback,
            "progress": {
                "processed_count": len(enriched_questions),
                "current_index": current_index,
                "total_count": total_count,
            },
            "questions": enriched_questions,
            "option_visual_debug": debug_rows,
        },
    )


def make_question_uid(source_json_path: Path, question: dict, index: int) -> str:
    source_stem = source_json_path.parent.name
    page_no = 1
    visual_pages = question.get("visual_pages", []) or []
    if isinstance(visual_pages, list) and visual_pages:
        try:
            page_no = int(visual_pages[0])
        except Exception:
            page_no = 1
    local_no = str(question.get("local_number", "") or "").strip() or f"{index:03d}"
    return f"{source_stem}_p{page_no:03d}_q{local_no}"


def resolve_runtime_run_id(source_json_path: Path) -> str:
    explicit = str(os.environ.get("VISUAL_RUNTIME_RUN_ID", "") or "").strip()
    if explicit:
        return explicit
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"visualrun_{stamp}_{safe_slug(source_json_path.parent.name)}"


def build_prepared_payload(
    source_json_path: Path,
    *,
    option_anchor_mode: str,
    api_key: str = "",
    model: str = "",
    require_vision_figure_model: bool = False,
    allow_heuristic_figure_fallback: bool = True,
    semantic_bridge_enable_image_detection: bool = False,
    enable_mineru_fallback: bool = False,
    mineru_exe: str = "mineru",
    mineru_api_url: str = "",
    mineru_out_dir: Path | None = None,
    mineru_timeout_seconds: int = 240,
    progress_path: Path | None = None,
    partial_path: Path | None = None,
) -> dict:
    payload = read_json(source_json_path)
    if not isinstance(payload, dict):
        raise ValueError("source_json_must_be_object")
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("questions_must_be_list")
    runtime_run_id = resolve_runtime_run_id(source_json_path)
    mineru_out_dir = mineru_out_dir or (source_json_path.parent / "_mineru_fallback")

    enriched_questions: list[dict] = []
    debug_rows: list[dict] = []
    total_count = len([item for item in questions if isinstance(item, dict)])
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id", "") or question.get("record_id", "") or f"question_{index:03d}")
        started_at = datetime.now()
        append_jsonl(
            progress_path,
            {
                "event": "question_started",
                "time": started_at.isoformat(timespec="seconds"),
                "index": index,
                "total_count": total_count,
                "question_id": question_id,
            },
        )
        safe_progress_print(
            {
                "event": "question_started",
                "index": index,
                "total_count": total_count,
                "question_id": question_id,
            }
        )
        enriched = dict(question)
        question_uid = make_question_uid(source_json_path, question, index)
        try:
            enriched["question_uid"] = question_uid
            enriched["runtime_run_id"] = runtime_run_id
            bridge_contract = question.get("bridge_contract", {}) if isinstance(question.get("bridge_contract"), dict) else {}
            if (
                str(bridge_contract.get("option_prepare_policy", "") or "") == "do_not_detect_on_composite"
                and not semantic_bridge_enable_image_detection
            ):
                planner_scope = {
                    "option": False,
                    "stem": False,
                    "analysis": False,
                    "reason": "semantic_v03_bridge_uses_composite_for_transcription_only",
                }
                gating = {
                    "should_run_option_detection": False,
                    "gate_reason": planner_scope["reason"],
                    "planner_scope": planner_scope,
                }
                detection = _empty_detection()
                detection["global_review_flags"] = [
                    "option_prepare_skipped_composite_input",
                    "asset_detection_must_use_bridge_fragments",
                ]
                staged_assets: list[dict] = []
                enriched["option_anchor_mode"] = option_anchor_mode
                enriched["figure_detection_scope"] = planner_scope
                enriched["gating_result"] = gating
                enriched["option_visual_blocks"] = []
                enriched["stem_image_bboxes"] = []
                enriched["analysis_image_bboxes"] = []
                enriched["unassigned_image_bboxes"] = []
                enriched["option_detection_review_flags"] = detection["global_review_flags"]
                enriched["figure_branch_trace"] = []
                enriched["staged_visual_assets"] = staged_assets
                enriched_questions.append(enriched)
                debug_rows.append(
                    {
                        "question_id": question.get("question_id", ""),
                        "question_uid": question_uid,
                        "runtime_run_id": runtime_run_id,
                        "figure_detection_scope": planner_scope,
                        "gating": gating,
                        "detection": detection,
                        "staged_visual_assets": staged_assets,
                    }
                )
                write_partial_payload(
                    partial_path,
                    payload,
                    source_json_path=source_json_path,
                    runtime_run_id=runtime_run_id,
                    option_anchor_mode=option_anchor_mode,
                    require_vision_figure_model=require_vision_figure_model,
                    allow_heuristic_figure_fallback=allow_heuristic_figure_fallback,
                    enable_mineru_fallback=enable_mineru_fallback,
                    enriched_questions=enriched_questions,
                    debug_rows=debug_rows,
                    current_index=index,
                    total_count=total_count,
                )
                elapsed = round((datetime.now() - started_at).total_seconds(), 3)
                append_jsonl(
                    progress_path,
                    {
                        "event": "question_completed",
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "index": index,
                        "total_count": total_count,
                        "question_id": question_id,
                        "elapsed_seconds": elapsed,
                        "staged_asset_count": 0,
                        "review_flags": detection["global_review_flags"],
                    },
                )
                safe_progress_print(
                    {
                        "event": "question_completed",
                        "index": index,
                        "total_count": total_count,
                        "question_id": question_id,
                        "elapsed_seconds": elapsed,
                        "staged_asset_count": 0,
                        "prepare_policy": "skipped_composite_input",
                    }
                )
                continue
            planner_scope = _planner_scope(question)

            if planner_scope.get("option", True):
                gating = option_choice_gating.evaluate_choice_gating(
                    question_uid=question_uid,
                    option_anchor_mode=option_anchor_mode,
                    question_type=str(question.get("question_type", "") or ""),
                    stem_text=str(question.get("stem_text", "") or ""),
                    raw_ocr_text=str(question.get("transcription_ocr", "") or ""),
                    question_image_path=str(question.get("question_image", "") or ""),
                    stem_image_path=str(question.get("stem_image", "") or ""),
                )
                if not bool(gating.get("should_run_option_detection", False)):
                    gating = {
                        **gating,
                        "should_run_option_detection": True,
                        "planner_override": True,
                        "planner_override_reason": "image_need_gate_options",
                        "planner_scope": planner_scope,
                    }
                detection = _option_anchor_detection().detect_option_anchors(
                    question,
                    gating,
                    api_key=api_key,
                    model=model,
                )
            else:
                gating = {
                    "should_run_option_detection": False,
                    "gate_reason": planner_scope.get("reason", "planner_scope_skip"),
                    "planner_scope": planner_scope,
                }
                detection = _empty_detection()

            if planner_scope.get("stem", True) or planner_scope.get("analysis", True):
                public_figures = _option_anchor_detection().detect_public_figure_regions(
                    question,
                    api_key=api_key,
                    model=model,
                    require_model=require_vision_figure_model,
                    allow_heuristic_fallback=allow_heuristic_figure_fallback,
                )
            else:
                public_figures = _empty_detection()

            if not planner_scope.get("stem", True):
                if planner_scope.get("analysis", True):
                    # In packaged samples the same long crop can be stored as
                    # question/stem/analysis. Public-figure detection keeps
                    # whole-question boxes in the stem bucket, then staging
                    # reclassifies question_image boxes by the red solution
                    # boundary. Do not delete those analysis candidates here.
                    kept_for_analysis = [
                        item
                        for item in (public_figures.get("stem_image_bboxes", []) or [])
                        if str(item.get("bbox_space", "") or "") == "question_image"
                    ]
                    if kept_for_analysis:
                        public_figures["global_review_flags"] = list(public_figures.get("global_review_flags", []) or []) + [
                            "question_image_boxes_kept_for_analysis_reclassify"
                        ]
                    public_figures["stem_image_bboxes"] = kept_for_analysis
                else:
                    public_figures["stem_image_bboxes"] = []
            if not planner_scope.get("analysis", True):
                public_figures["analysis_image_bboxes"] = []
            public_figures["global_review_flags"] = _filter_public_review_flags(
                list(public_figures.get("global_review_flags", []) or []),
                planner_scope,
            )
            public_stem_boxes = _suppress_public_boxes_owned_by_options(
                list(public_figures.get("stem_image_bboxes", []) or []),
                list(detection.get("option_visual_blocks", []) or []),
            )
            detection["stem_image_bboxes"] = list(detection.get("stem_image_bboxes", []) or []) + public_stem_boxes
            detection["analysis_image_bboxes"] = list(public_figures.get("analysis_image_bboxes", []) or [])
            detection["global_review_flags"] = list(detection.get("global_review_flags", []) or []) + list(public_figures.get("global_review_flags", []) or [])
            detection["figure_branch_trace"] = list(public_figures.get("branch_trace", []) or [])
            staged_assets = option_crop_staging.build_staged_visual_assets(enriched, detection)
            if bool((question.get("image_need_gate") or {}).get("needs_figure_detection", False)) and not staged_assets:
                detection["global_review_flags"] = list(detection.get("global_review_flags", []) or []) + ["figure_detection_zero_assets"]
            mineru_action: dict | None = None
            if enable_mineru_fallback and _should_try_mineru_fallback(enriched, planner_scope, detection, staged_assets):
                mineru_assets, mineru_action = _build_mineru_fallback_assets(
                    enriched,
                    question_uid=question_uid,
                    runtime_run_id=runtime_run_id,
                    mineru_exe=mineru_exe,
                    mineru_api_url=mineru_api_url,
                    mineru_out_dir=mineru_out_dir,
                    mineru_timeout_seconds=mineru_timeout_seconds,
                )
                if mineru_assets:
                    staged_assets = mineru_assets
                    detection["global_review_flags"] = normalize_review_flags(
                        list(detection.get("global_review_flags", []) or [])
                        + ["mineru_fallback_used", "figure_detection_zero_assets_recovered"]
                    )
                else:
                    detection["global_review_flags"] = normalize_review_flags(
                        list(detection.get("global_review_flags", []) or []) + ["mineru_fallback_failed"]
                    )
            enriched["option_anchor_mode"] = option_anchor_mode
            enriched["figure_detection_scope"] = planner_scope
            enriched["gating_result"] = gating
            enriched["option_visual_blocks"] = detection.get("option_visual_blocks", []) or []
            enriched["stem_image_bboxes"] = detection.get("stem_image_bboxes", []) or []
            enriched["analysis_image_bboxes"] = detection.get("analysis_image_bboxes", []) or []
            enriched["unassigned_image_bboxes"] = detection.get("unassigned_image_bboxes", []) or []
            enriched["option_detection_review_flags"] = detection.get("global_review_flags", []) or []
            enriched["figure_branch_trace"] = detection.get("figure_branch_trace", []) or []
            enriched["staged_visual_assets"] = staged_assets
            if mineru_action is not None:
                enriched["mineru_fallback"] = mineru_action
            enriched_questions.append(enriched)

            debug_rows.append(
                {
                    "question_id": question.get("question_id", ""),
                    "question_uid": question_uid,
                    "runtime_run_id": runtime_run_id,
                    "figure_detection_scope": planner_scope,
                    "gating": gating,
                    "detection": detection,
                    "mineru_fallback": mineru_action,
                    "staged_visual_assets": staged_assets,
                }
            )
            write_partial_payload(
                partial_path,
                payload,
                source_json_path=source_json_path,
                runtime_run_id=runtime_run_id,
                option_anchor_mode=option_anchor_mode,
                require_vision_figure_model=require_vision_figure_model,
                allow_heuristic_figure_fallback=allow_heuristic_figure_fallback,
                enable_mineru_fallback=enable_mineru_fallback,
                enriched_questions=enriched_questions,
                debug_rows=debug_rows,
                current_index=index,
                total_count=total_count,
            )
            elapsed = round((datetime.now() - started_at).total_seconds(), 3)
            append_jsonl(
                progress_path,
                {
                    "event": "question_completed",
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "index": index,
                    "total_count": total_count,
                    "question_id": question_id,
                    "elapsed_seconds": elapsed,
                    "staged_asset_count": len(staged_assets),
                    "review_flags": detection.get("global_review_flags", []) or [],
                },
            )
            safe_progress_print(
                {
                    "event": "question_completed",
                    "index": index,
                    "total_count": total_count,
                    "question_id": question_id,
                    "elapsed_seconds": elapsed,
                    "staged_asset_count": len(staged_assets),
                }
            )
        except Exception as exc:
            append_jsonl(
                progress_path,
                {
                    "event": "question_failed",
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "index": index,
                    "total_count": total_count,
                    "question_id": question_id,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            write_partial_payload(
                partial_path,
                payload,
                source_json_path=source_json_path,
                runtime_run_id=runtime_run_id,
                option_anchor_mode=option_anchor_mode,
                require_vision_figure_model=require_vision_figure_model,
                allow_heuristic_figure_fallback=allow_heuristic_figure_fallback,
                enable_mineru_fallback=enable_mineru_fallback,
                enriched_questions=enriched_questions,
                debug_rows=debug_rows,
                current_index=index,
                total_count=total_count,
            )
            safe_progress_print(
                {
                    "event": "question_failed",
                    "index": index,
                    "total_count": total_count,
                    "question_id": question_id,
                    "error": str(exc),
                }
            )
            raise

    return {
        **payload,
        "schema_version": "option_visual_source.v1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_json": str(source_json_path),
        "runtime_run_id": runtime_run_id,
        "option_anchor_mode": option_anchor_mode,
        "require_vision_figure_model": require_vision_figure_model,
        "allow_heuristic_figure_fallback": allow_heuristic_figure_fallback,
        "semantic_bridge_enable_image_detection": semantic_bridge_enable_image_detection,
        "enable_mineru_fallback": enable_mineru_fallback,
        "mineru_exe": str(mineru_exe or ""),
        "mineru_api_url": str(mineru_api_url or ""),
        "mineru_out_dir": str(mineru_out_dir),
        "questions": enriched_questions,
        "option_visual_debug": debug_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an enhanced source JSON with choice gating, option anchors, and staged assets.")
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--option-anchor-mode", default="auto")
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default=DEFAULT_OPTION_ANCHOR_MODEL)
    parser.add_argument(
        "--require-vision-figure-model",
        action="store_true",
        default=str(os.environ.get("VISUAL_FIGURE_REQUIRE_MODEL", "") or "").strip() == "1",
        help="Fail before preparing if the public figure detection model cannot run.",
    )
    parser.add_argument(
        "--disable-heuristic-figure-fallback",
        action="store_true",
        default=str(os.environ.get("VISUAL_FIGURE_DISABLE_HEURISTIC_FALLBACK", "") or "").strip() == "1",
        help="Do not use heuristic public-figure detection when the model returns no boxes.",
    )
    parser.add_argument(
        "--semantic-bridge-enable-image-detection",
        action="store_true",
        default=str(os.environ.get("SEMANTIC_BRIDGE_ENABLE_IMAGE_DETECTION", "") or "").strip() == "1",
        help="Allow semantic_v03 composite bridge records to run figure detection before transcription/assets.",
    )
    parser.add_argument(
        "--enable-mineru-fallback",
        action="store_true",
        default=str(os.environ.get("MINERU_FALLBACK_ENABLED", "") or "").strip() == "1",
        help="When figure detection produces zero staged assets for option images, run MinerU and convert its images into staged assets.",
    )
    parser.add_argument("--mineru-exe", default=os.environ.get("MINERU_EXE", "mineru"))
    parser.add_argument("--mineru-api-url", default=os.environ.get("MINERU_API_URL", ""))
    parser.add_argument("--mineru-out-dir", default="")
    parser.add_argument("--mineru-timeout-seconds", type=int, default=int(os.environ.get("MINERU_TIMEOUT_SECONDS", "240") or 240))
    args = parser.parse_args()

    source_json = Path(args.source_json).expanduser().resolve()
    if not source_json.exists():
        raise SystemExit(f"source_json_not_found: {source_json}")
    api_key = str(args.api_key or "")
    if args.require_vision_figure_model and not api_key.strip():
        raise SystemExit("missing_api_key_for_required_vision_figure_model")
    out_json = Path(args.out_json).expanduser().resolve()
    progress_path = out_json.with_suffix(".progress.jsonl")
    partial_path = out_json.with_suffix(".partial.json")
    if progress_path.exists():
        progress_path.unlink()
    payload = build_prepared_payload(
        source_json,
        option_anchor_mode=str(args.option_anchor_mode or "auto"),
        api_key=api_key,
        model=str(args.model or DEFAULT_OPTION_ANCHOR_MODEL),
        require_vision_figure_model=bool(args.require_vision_figure_model),
        allow_heuristic_figure_fallback=not bool(args.disable_heuristic_figure_fallback),
        semantic_bridge_enable_image_detection=bool(args.semantic_bridge_enable_image_detection),
        enable_mineru_fallback=bool(args.enable_mineru_fallback),
        mineru_exe=str(args.mineru_exe or "mineru"),
        mineru_api_url=str(args.mineru_api_url or ""),
        mineru_out_dir=Path(args.mineru_out_dir).expanduser().resolve() if str(args.mineru_out_dir or "").strip() else out_json.parent / "_mineru_fallback",
        mineru_timeout_seconds=int(args.mineru_timeout_seconds or 240),
        progress_path=progress_path,
        partial_path=partial_path,
    )
    write_json(out_json, payload)
    write_json(out_json.with_suffix(".debug.json"), payload.get("option_visual_debug", []))
    print(
        json.dumps(
            {
                "out_json": str(out_json),
                "question_count": len(payload.get("questions", []) or []),
                "option_detection_count": sum(
                    1 for item in (payload.get("questions", []) or []) if (item.get("option_visual_blocks", []) or [])
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
