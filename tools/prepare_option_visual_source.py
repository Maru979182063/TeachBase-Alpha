from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import option_anchor_detection
import option_choice_gating
import option_crop_staging


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
        )
        detection["stem_image_bboxes"] = list(detection.get("stem_image_bboxes", []) or []) + list(public_figures.get("stem_image_bboxes", []) or [])
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
    args = parser.parse_args()

    source_json = Path(args.source_json).expanduser().resolve()
    if not source_json.exists():
        raise SystemExit(f"source_json_not_found: {source_json}")
    out_json = Path(args.out_json).expanduser().resolve()
    payload = build_prepared_payload(
        source_json,
        option_anchor_mode=str(args.option_anchor_mode or "auto"),
        api_key=str(args.api_key or ""),
        model=str(args.model or option_anchor_detection.DEFAULT_MODEL),
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
