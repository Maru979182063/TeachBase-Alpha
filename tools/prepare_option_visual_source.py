from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import option_anchor_detection
import option_choice_gating
import option_crop_staging


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


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def build_prepared_payload(
    source_json_path: Path,
    *,
    option_anchor_mode: str,
    api_key: str = "",
    model: str = "",
    require_vision_figure_model: bool = False,
    allow_heuristic_figure_fallback: bool = True,
) -> dict:
    payload = read_json(source_json_path)
    if not isinstance(payload, dict):
        raise ValueError("source_json_must_be_object")
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("questions_must_be_list")

    enriched_questions: list[dict] = []
    debug_rows: list[dict] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        enriched = dict(question)
        question_uid = make_question_uid(source_json_path, question, index)
        enriched["question_uid"] = question_uid

        gating = option_choice_gating.evaluate_choice_gating(
            question_uid=question_uid,
            option_anchor_mode=option_anchor_mode,
            question_type=str(question.get("question_type", "") or ""),
            stem_text=str(question.get("stem_text", "") or ""),
            raw_ocr_text=str(question.get("transcription_ocr", "") or ""),
            question_image_path=str(question.get("question_image", "") or ""),
            stem_image_path=str(question.get("stem_image", "") or ""),
        )
        detection = option_anchor_detection.detect_option_anchors(
            question,
            gating,
            api_key=api_key,
            model=model,
        )
        public_figures = option_anchor_detection.detect_public_figure_regions(
            question,
            api_key=api_key,
            model=model,
            require_model=require_vision_figure_model,
            allow_heuristic_fallback=allow_heuristic_figure_fallback,
        )
        public_stem_boxes = _suppress_public_boxes_owned_by_options(
            list(public_figures.get("stem_image_bboxes", []) or []),
            list(detection.get("option_visual_blocks", []) or []),
        )
        detection["stem_image_bboxes"] = list(detection.get("stem_image_bboxes", []) or []) + public_stem_boxes
        detection["analysis_image_bboxes"] = list(public_figures.get("analysis_image_bboxes", []) or [])
        detection["global_review_flags"] = list(detection.get("global_review_flags", []) or []) + list(public_figures.get("global_review_flags", []) or [])
        staged_assets = option_crop_staging.build_staged_visual_assets(enriched, detection)
        enriched["option_anchor_mode"] = option_anchor_mode
        enriched["gating_result"] = gating
        enriched["option_visual_blocks"] = detection.get("option_visual_blocks", []) or []
        enriched["stem_image_bboxes"] = detection.get("stem_image_bboxes", []) or []
        enriched["analysis_image_bboxes"] = detection.get("analysis_image_bboxes", []) or []
        enriched["unassigned_image_bboxes"] = detection.get("unassigned_image_bboxes", []) or []
        enriched["option_detection_review_flags"] = detection.get("global_review_flags", []) or []
        enriched["staged_visual_assets"] = staged_assets
        enriched_questions.append(enriched)

        debug_rows.append(
            {
                "question_id": question.get("question_id", ""),
                "question_uid": question_uid,
                "gating": gating,
                "detection": detection,
                "staged_visual_assets": staged_assets,
            }
        )

    return {
        **payload,
        "schema_version": "option_visual_source.v1.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_json": str(source_json_path),
        "option_anchor_mode": option_anchor_mode,
        "require_vision_figure_model": require_vision_figure_model,
        "allow_heuristic_figure_fallback": allow_heuristic_figure_fallback,
        "questions": enriched_questions,
        "option_visual_debug": debug_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an enhanced source JSON with choice gating, option anchors, and staged assets.")
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--option-anchor-mode", default="auto")
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default=option_anchor_detection.DEFAULT_MODEL)
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
    args = parser.parse_args()

    source_json = Path(args.source_json).expanduser().resolve()
    if not source_json.exists():
        raise SystemExit(f"source_json_not_found: {source_json}")
    api_key = str(args.api_key or "")
    if args.require_vision_figure_model and not api_key.strip():
        raise SystemExit("missing_api_key_for_required_vision_figure_model")
    out_json = Path(args.out_json).expanduser().resolve()
    payload = build_prepared_payload(
        source_json,
        option_anchor_mode=str(args.option_anchor_mode or "auto"),
        api_key=api_key,
        model=str(args.model or option_anchor_detection.DEFAULT_MODEL),
        require_vision_figure_model=bool(args.require_vision_figure_model),
        allow_heuristic_figure_fallback=not bool(args.disable_heuristic_figure_fallback),
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
