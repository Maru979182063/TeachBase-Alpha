from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import teacher_handout_visual_transcribe_doubao as runtime
import visual_transcription_core as vision_core
import vision_prompt_store


DEFAULT_MODEL = "doubao-seed-1-8-251228"
DEFAULT_MAX_RISK_SPANS = 8
REFINE_PROMPT_VERSION = vision_prompt_store.get_refine_prompt_bundle()["prompt_version"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_run_records(run_dir: Path) -> tuple[dict, list[dict]]:
    results_path = run_dir / "visual_transcription_results.json"
    if not results_path.exists():
        raise SystemExit(f"missing_results_json: {results_path}")
    summary = vision_core.read_json(results_path)
    records = summary.get("records", []) if isinstance(summary, dict) else []
    return summary, records


def pick_records(records: list[dict], question_ids: list[str]) -> list[dict]:
    wanted = set(question_ids)
    picked = [record for record in records if str(record.get("question_id", "")) in wanted]
    missing = [question_id for question_id in question_ids if question_id not in {str(r.get("question_id", "")) for r in picked}]
    if missing:
        raise SystemExit(f"question_ids_not_found: {','.join(missing)}")
    return picked


def limit_risk_spans(spans: list[dict], max_items: int) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for span in spans:
        if not isinstance(span, dict):
            continue
        key = (
            str(span.get("field", "") or ""),
            str(span.get("text", "") or ""),
            str(span.get("reason", "") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
        if len(deduped) >= max_items:
            break
    return deduped


def build_refine_prompt(transcription: dict, selected_spans: list[dict], record_id: str, question_id: str) -> str:
    display_fields = transcription.get("display_normalized_text", {}) if isinstance(transcription.get("display_normalized_text"), dict) else {}
    stem_text = str(display_fields.get("stem_text_md", transcription.get("stem_text_md", "")) or "")
    answer_text = str(display_fields.get("answer_text_md", transcription.get("answer_text_md", "")) or "")
    analysis_text = str(display_fields.get("analysis_text_md", transcription.get("analysis_text_md", "")) or "")
    spans_lines = []
    for idx, span in enumerate(selected_spans, start=1):
        spans_lines.append(
            f"{idx}. field={span.get('field','')} reason={span.get('reason','')} text={json.dumps(str(span.get('text','') or ''), ensure_ascii=False)}"
        )
    spans_block = "\n".join(spans_lines) if spans_lines else "none"
    return (
        "You are a K12 math visual refinement assistant.\n"
        "Task: review only the risky spans listed below against the provided images and correct them if the image evidence clearly supports a correction.\n"
        "Keep all other text unchanged. Do not rewrite for style. Do not summarize. Do not expand '如图' into a natural-language picture description.\n"
        "If the image is cropped or unclear, keep the current text and add an unresolved span instead of guessing.\n"
        "Return JSON only.\n\n"
        "Rules:\n"
        "1. Only change text when the image evidence is clear.\n"
        "2. Preserve existing field boundaries: stem_text_md / answer_text_md / analysis_text_md.\n"
        "3. Preserve Markdown + LaTeX. Use $...$ and $$...$$ only.\n"
        "4. Never drop visible object labels such as A, B, C, D, E, F, G, M, N, P, Q, point names, line names, or angle labels.\n"
        "5. If no correction is needed, return the original fields unchanged and an empty refine_log.\n"
        "6. If you change a span, log it in refine_log with field, span_before, span_after, reason, evidence_ref_key, and confidence.\n"
        "7. If a listed span remains unclear, record it in unresolved_spans.\n\n"
        f"record_id: {record_id}\n"
        f"question_id: {question_id}\n\n"
        "Current fields:\n"
        f"stem_text_md = {json.dumps(stem_text, ensure_ascii=False)}\n"
        f"answer_text_md = {json.dumps(answer_text, ensure_ascii=False)}\n"
        f"analysis_text_md = {json.dumps(analysis_text, ensure_ascii=False)}\n\n"
        "Risk spans to inspect:\n"
        f"{spans_block}\n\n"
        "Output schema:\n"
        "{\n"
        '  "record_id": "...",\n'
        '  "question_id": "...",\n'
        '  "stem_text_md": "...",\n'
        '  "answer_text_md": "...",\n'
        '  "analysis_text_md": "...",\n'
        '  "stem_requires_image": true,\n'
        '  "analysis_requires_image": true,\n'
        '  "uncertain_spans": [],\n'
        '  "refine_log": [\n'
        '    {"field":"stem|answer|analysis","span_before":"...","span_after":"...","reason":"local_reread","evidence_ref_key":"question_image|stem_image|analysis_image","confidence":0.0}\n'
        "  ],\n"
        '  "unresolved_spans": [\n'
        '    {"field":"stem|answer|analysis","text":"...","reason":"unclear_after_reread"}\n'
        "  ]\n"
        "}\n"
    )


def build_refine_prompt(transcription: dict, selected_spans: list[dict], record_id: str, question_id: str) -> str:
    display_fields = transcription.get("display_normalized_text", {}) if isinstance(transcription.get("display_normalized_text"), dict) else {}
    stem_text = str(display_fields.get("stem_text_md", transcription.get("stem_text_md", "")) or "")
    answer_text = str(display_fields.get("answer_text_md", transcription.get("answer_text_md", "")) or "")
    analysis_text = str(display_fields.get("analysis_text_md", transcription.get("analysis_text_md", "")) or "")
    spans_lines = []
    for idx, span in enumerate(selected_spans, start=1):
        spans_lines.append(
            f"{idx}. field={span.get('field','')} reason={span.get('reason','')} text={json.dumps(str(span.get('text','') or ''), ensure_ascii=False)}"
        )
    spans_block = "\n".join(spans_lines) if spans_lines else "none"
    bundle = vision_prompt_store.get_refine_prompt_bundle()
    return vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "RECORD_ID": record_id,
            "QUESTION_ID": question_id,
            "STEM_TEXT_JSON": json.dumps(stem_text, ensure_ascii=False),
            "ANSWER_TEXT_JSON": json.dumps(answer_text, ensure_ascii=False),
            "ANALYSIS_TEXT_JSON": json.dumps(analysis_text, ensure_ascii=False),
            "RISK_SPANS_BLOCK": spans_block,
        },
    )


def normalize_refine_response(
    parsed: dict,
    *,
    source_transcription: dict,
    record: dict,
    model_name: str,
) -> dict:
    normalized = vision_core.safe_normalize_transcription_payload(
        parsed,
        record_id=str(record.get("record_id", "") or parsed.get("record_id", "")),
        question_id=str(record.get("question_id", "") or parsed.get("question_id", "")),
        visual_refs=source_transcription.get("visual_refs", {}),
        prompt_version=REFINE_PROMPT_VERSION,
        model_name=model_name,
    )
    refine_log = parsed.get("refine_log", []) if isinstance(parsed.get("refine_log"), list) else []
    unresolved = parsed.get("unresolved_spans", []) if isinstance(parsed.get("unresolved_spans"), list) else []
    normalized["refine_log"] = refine_log
    normalized["unresolved_spans"] = unresolved
    normalized["refine_prompt_version"] = REFINE_PROMPT_VERSION
    normalized["refine_source_record_id"] = str(record.get("record_id", "") or "")
    normalized["refine_source_risk_spans"] = source_transcription.get("risk_spans", [])
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply local visual refinement to high-risk transcription spans.")
    parser.add_argument("--source-run-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--question-ids", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--max-risk-spans", type=int, default=DEFAULT_MAX_RISK_SPANS)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    source_run_dir = Path(args.source_run_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    vision_core.ensure_dir(out_dir)
    raw_dir = out_dir / "raw"
    vision_core.ensure_dir(raw_dir)

    summary, records = load_run_records(source_run_dir)
    question_ids = [item.strip() for item in args.question_ids.split(",") if item.strip()]
    picked_records = pick_records(records, question_ids)

    refined_records: list[dict] = []
    for record in picked_records:
        if record.get("status") != "ok":
            refined_records.append(
                {
                    "record_id": record.get("record_id", ""),
                    "question_id": record.get("question_id", ""),
                    "source_transcription_json": record.get("source_transcription_json", ""),
                    "status": "failed",
                    "error": "source_record_not_ok",
                    "tag": record.get("tag", ""),
                }
            )
            continue

        transcription = record.get("transcription", {})
        risk_spans = limit_risk_spans(transcription.get("risk_spans", []) or [], args.max_risk_spans)
        prompt = build_refine_prompt(
            transcription,
            risk_spans,
            str(record.get("record_id", "") or ""),
            str(record.get("question_id", "") or ""),
        )
        image_paths = []
        for key in ("question_image", "stem_image", "analysis_image"):
            raw = str(record.get(key, "") or "")
            if raw:
                path = Path(raw)
                if path.exists() and path not in image_paths:
                    image_paths.append(path)

        prepared = {
            "record_id": record.get("record_id", ""),
            "question_id": record.get("question_id", ""),
            "source_run_dir": str(source_run_dir),
            "source_transcription_json": record.get("source_transcription_json", ""),
            "question_image": record.get("question_image", ""),
            "stem_image": record.get("stem_image", ""),
            "analysis_image": record.get("analysis_image", ""),
            "risk_spans": risk_spans,
            "prompt": prompt,
            "prompt_version": REFINE_PROMPT_VERSION,
            "model_name": args.model,
            "tag": record.get("tag", ""),
        }
        vision_core.write_json(raw_dir / f"{record.get('record_id','')}.prepared.json", prepared)

        if args.prepare_only:
            refined_records.append(
                {
                    "record_id": record.get("record_id", ""),
                    "question_id": record.get("question_id", ""),
                    "source_transcription_json": record.get("source_transcription_json", ""),
                    "status": "prepared",
                    "tag": record.get("tag", ""),
                }
            )
            continue

        if not args.api_key:
            refined_records.append(
                {
                    "record_id": record.get("record_id", ""),
                    "question_id": record.get("question_id", ""),
                    "source_transcription_json": record.get("source_transcription_json", ""),
                    "status": "failed",
                    "error": "missing_api_key",
                    "tag": record.get("tag", ""),
                }
            )
            continue

        result = None
        started_at_iso = utc_now_iso()
        started_perf = time.perf_counter()
        try:
            result = runtime.call_model(args.api_key, args.model, prompt, image_paths)
            finished_at_iso = utc_now_iso()
            latency_seconds = round(time.perf_counter() - started_perf, 3)
            vision_core.write_json(raw_dir / f"{record.get('record_id','')}.response.json", result["raw_response"])
            (raw_dir / f"{record.get('record_id','')}.response.txt").write_text(
                str(result.get("raw_content", "")),
                encoding="utf-8",
            )
            parsed = vision_core.extract_json_block(result["raw_content"])
            normalized = normalize_refine_response(
                parsed,
                source_transcription=transcription,
                record=record,
                model_name=args.model,
            )
            refined_records.append(
                {
                    "record_id": record.get("record_id", ""),
                    "question_id": record.get("question_id", ""),
                    "source_transcription_json": record.get("source_transcription_json", ""),
                    "status": "ok",
                    "tag": record.get("tag", ""),
                    "question_image": record.get("question_image", ""),
                    "stem_image": record.get("stem_image", ""),
                    "analysis_image": record.get("analysis_image", ""),
                    "request_started_at": started_at_iso,
                    "request_finished_at": finished_at_iso,
                    "latency_seconds": latency_seconds,
                    "usage": result.get("usage", {}) or {},
                    "transcription": normalized,
                }
            )
        except Exception as exc:  # noqa: BLE001
            finished_at_iso = utc_now_iso()
            latency_seconds = round(time.perf_counter() - started_perf, 3)
            if isinstance(result, dict) and result.get("raw_response"):
                vision_core.write_json(raw_dir / f"{record.get('record_id','')}.response_failed_parse.json", result["raw_response"])
            refined_records.append(
                {
                    "record_id": record.get("record_id", ""),
                    "question_id": record.get("question_id", ""),
                    "source_transcription_json": record.get("source_transcription_json", ""),
                    "status": "failed",
                    "error": str(exc),
                    "tag": record.get("tag", ""),
                    "request_started_at": started_at_iso,
                    "request_finished_at": finished_at_iso,
                    "latency_seconds": latency_seconds,
                    "usage": result.get("usage", {}) if isinstance(result, dict) else {},
                }
            )
        time.sleep(max(args.sleep_seconds, 0.0))

    ok_records = [item for item in refined_records if item.get("status") == "ok"]
    results_summary = {
        "model": args.model,
        "source_run_dir": str(source_run_dir),
        "question_count": len(refined_records),
        "ok_count": len(ok_records),
        "prepared_count": sum(1 for item in refined_records if item.get("status") == "prepared"),
        "failed_count": sum(1 for item in refined_records if item.get("status") == "failed"),
        "usage_totals": vision_core.aggregate_usage(ok_records),
        "latency_summary": vision_core.aggregate_latency(refined_records),
        "records": refined_records,
    }
    vision_core.write_json(out_dir / "visual_transcription_results.json", results_summary)
    compact = []
    for item in refined_records:
        compact.append(
            vision_core.summarize_record(
                item,
                status=item.get("status", ""),
                parsed=item.get("transcription"),
                error=item.get("error", ""),
            )
        )
    vision_core.write_json(out_dir / "visual_transcription_compact.json", compact)
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "model": args.model,
                "question_count": len(refined_records),
                "ok_count": results_summary["ok_count"],
                "failed_count": results_summary["failed_count"],
                "usage_totals": results_summary["usage_totals"],
                "latency_summary": results_summary["latency_summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
