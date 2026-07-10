from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import option_choice_gating
import option_crop_staging


DEFAULT_OPTION_ANCHOR_MODEL = "doubao-seed-2-0-lite-260428"


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
