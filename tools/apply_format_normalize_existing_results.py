from __future__ import annotations

import argparse
import copy
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import assetize_question_images as assetize
import math_formula_library_gate as math_formula_gate
import teacher_handout_visual_transcribe_doubao as transcribe
import visual_transcription_core as vision_core


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_field_mapping_like_payload(record: dict[str, Any]) -> dict[str, Any]:
    transcription = record.get("transcription", {}) if isinstance(record.get("transcription"), dict) else {}
    return {
        "record_id": str(transcription.get("record_id", "") or record.get("record_id", "") or ""),
        "question_id": str(transcription.get("question_id", "") or record.get("question_id", "") or ""),
        "stem_text_md": str(transcription.get("stem_text_md", "") or ""),
        "answer_text_md": str(transcription.get("answer_text_md", "") or ""),
        "analysis_text_md": str(transcription.get("analysis_text_md", "") or ""),
        "handwriting_text_md": str(transcription.get("handwriting_text_md", "") or ""),
        "stem_requires_image": bool(transcription.get("stem_requires_image", False)),
        "analysis_requires_image": bool(transcription.get("analysis_requires_image", False)),
        "handwriting_requires_review": bool(transcription.get("handwriting_requires_review", False)),
        "handwriting_consistency": transcription.get("handwriting_consistency", {}) or {},
        "uncertain_spans": transcription.get("uncertain_spans", []) or [],
    }


def aggregate_usage(records: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "image_tokens": 0,
    }
    for record in records:
        usage = (record.get("format_normalize_only", {}) or {}).get("usage", {}) or {}
        patch_usage = (record.get("format_normalize_only", {}) or {}).get("latex_span_patch_usage", {}) or {}
        for key in totals:
            totals[key] += int(usage.get(key, 0) or 0)
            totals[key] += int(patch_usage.get(key, 0) or 0)
    return totals


def aggregate_latency(records: list[dict[str, Any]]) -> dict[str, float]:
    values = [
        float((record.get("format_normalize_only", {}) or {}).get("latency_seconds", 0.0) or 0.0)
        for record in records
        if record.get("status") == "ok"
    ]
    if not values:
        return {"count": 0, "avg_seconds": 0.0, "max_seconds": 0.0, "min_seconds": 0.0}
    return {
        "count": len(values),
        "avg_seconds": round(sum(values) / len(values), 3),
        "max_seconds": round(max(values), 3),
        "min_seconds": round(min(values), 3),
    }


def render_compact(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for record in records:
        compact_item = {
            "record_id": str(record.get("record_id", "") or ""),
            "question_id": str(record.get("question_id", "") or ""),
            "status": str(record.get("status", "") or ""),
            "tag": str(record.get("tag", "") or ""),
            "source_visual_status": str(record.get("source_visual_status", "") or ""),
        }
        transcription = record.get("transcription", {}) if isinstance(record.get("transcription"), dict) else {}
        compact_item.update(
            {
                "stem_text_md": str(transcription.get("stem_text_md", "") or ""),
                "answer_text_md": str(transcription.get("answer_text_md", "") or ""),
                "analysis_text_md": str(transcription.get("analysis_text_md", "") or ""),
                "handwriting_text_md": str(transcription.get("handwriting_text_md", "") or ""),
                "stem_requires_image": bool(transcription.get("stem_requires_image", False)),
                "analysis_requires_image": bool(transcription.get("analysis_requires_image", False)),
                "format_fix_count": len(transcription.get("format_fix_log", []) or []),
                "unresolved_format_span_count": len(transcription.get("unresolved_format_spans", []) or []),
                "uncertain_span_count": len(transcription.get("uncertain_spans", []) or []),
            }
        )
        node_meta = record.get("format_normalize_only", {}) if isinstance(record.get("format_normalize_only"), dict) else {}
        compact_item.update(
            {
                "format_normalize_latency_seconds": float(node_meta.get("latency_seconds", 0.0) or 0.0),
                "format_normalize_total_tokens": int(((node_meta.get("usage", {}) or {}).get("total_tokens", 0) or 0)),
            }
        )
        if record.get("status") != "ok":
            compact_item["error"] = str(record.get("error", "") or "")
        compact.append(compact_item)
    return compact


def rebuild_manifest_with_new_text(
    *,
    base_manifest_path: Path,
    manifest_out_path: Path,
    html_out_path: Path,
    results_by_question_id: dict[str, dict[str, Any]],
    results_meta: dict[str, Any],
) -> dict[str, Any]:
    payload = read_json(base_manifest_path)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    updated_count = 0
    changed_fields_summary: dict[str, int] = {"stem": 0, "answer": 0, "analysis": 0}
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id", "") or "").strip()
        result_record = results_by_question_id.get(question_id)
        if not result_record:
            continue
        transcription = result_record.get("transcription", {}) if isinstance(result_record.get("transcription"), dict) else {}
        if not transcription:
            continue

        old_stem = str(question.get("stem_text_md", "") or "")
        old_answer = str(question.get("answer_text_md", "") or "")
        old_analysis = str(question.get("analysis_text_md", "") or "")

        question["stem_text_md"] = str(transcription.get("stem_text_md", "") or "")
        question["answer_text_md"] = str(transcription.get("answer_text_md", "") or "")
        question["analysis_text_md"] = str(transcription.get("analysis_text_md", "") or "")
        question["stem_requires_image"] = bool(transcription.get("stem_requires_image", question.get("stem_requires_image", False)))
        question["analysis_requires_image"] = bool(transcription.get("analysis_requires_image", question.get("analysis_requires_image", False)))

        qvs = transcription.get("question_visual_structure", {})
        if isinstance(qvs, dict) and qvs:
            question["question_visual_structure"] = qvs

        question["display_blocks"] = assetize.build_display_blocks(question)
        question["display_markdown"] = assetize.build_qvs_display_markdown(
            question.get("question_visual_structure", {}) if isinstance(question.get("question_visual_structure"), dict) else {},
            question,
        )
        updated_count += 1
        if old_stem != question["stem_text_md"]:
            changed_fields_summary["stem"] += 1
        if old_answer != question["answer_text_md"]:
            changed_fields_summary["answer"] += 1
        if old_analysis != question["analysis_text_md"]:
            changed_fields_summary["analysis"] += 1

    payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
    payload["text_refresh_source"] = {
        "mode": "format_normalize_only_reprocess",
        "source_manifest": str(base_manifest_path),
        "source_results": str(results_meta.get("results_path", "") or ""),
        "model": str(results_meta.get("model", "") or ""),
        "prompt_version": str(results_meta.get("prompt_version", "") or ""),
        "updated_question_count": updated_count,
        "changed_fields_summary": changed_fields_summary,
    }
    write_json(manifest_out_path, payload)
    assetize.write_html_clean(html_out_path, payload)
    return {
        "manifest_path": str(manifest_out_path),
        "html_path": str(html_out_path),
        "updated_question_count": updated_count,
        "changed_fields_summary": changed_fields_summary,
    }


def record_has_format_normalize_node(record: dict[str, Any]) -> bool:
    format_normalize_only = record.get("format_normalize_only")
    if isinstance(format_normalize_only, dict):
        return True
    pipeline_trace = record.get("pipeline_trace", {}) if isinstance(record.get("pipeline_trace"), dict) else {}
    nodes = pipeline_trace.get("nodes", []) if isinstance(pipeline_trace.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("node", "") or "").strip() == "format_normalize_model_node":
            return True
    layers = pipeline_trace.get("parallel_layers", []) if isinstance(pipeline_trace.get("parallel_layers"), list) else []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        node_names = layer.get("nodes", []) if isinstance(layer.get("nodes"), list) else []
        if "format_normalize_model_node" in node_names:
            return True
    return False


def run_one_record(
    *,
    record: dict[str, Any],
    question: dict[str, Any],
    api_key: str,
    model: str,
    raw_dir: Path,
) -> dict[str, Any]:
    record_id = str(record.get("record_id", "") or "")
    question_id = str(record.get("question_id", "") or "")
    started_at = now_iso()
    started_perf = time.perf_counter()
    field_mapping_payload = build_field_mapping_like_payload(record)
    prompt = transcribe.build_format_normalize_prompt(question, record_id, field_mapping_payload)
    image_paths = transcribe.collect_image_paths(question)
    prompt_path = raw_dir / f"{record_id}.format_normalize_only.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    base_record = {
        "record_id": record_id,
        "question_id": question_id,
        "source_transcription_json": str(question.get("source_transcription_json", "") or record.get("source_transcription_json", "") or ""),
        "status": "ok",
        "tag": str(record.get("tag", "") or ""),
        "question_image": str(question.get("question_image", "") or record.get("question_image", "") or ""),
        "stem_image": str(question.get("stem_image", "") or record.get("stem_image", "") or ""),
        "analysis_image": str(question.get("analysis_image", "") or record.get("analysis_image", "") or ""),
        "source_visual_status": str(record.get("status", "") or ""),
        "source_visual_usage": record.get("usage", {}) or {},
        "source_pipeline_trace": record.get("pipeline_trace", {}) or {},
    }

    try:
        model_result = transcribe.call_format_normalize_model(api_key, model, prompt, image_paths)
        raw_response = model_result.get("raw_response", {}) or {}
        raw_content = str(model_result.get("raw_content", "") or "")
        raw_response_path = raw_dir / f"{record_id}.format_normalize_only.response.json"
        raw_content_path = raw_dir / f"{record_id}.format_normalize_only.response.txt"
        write_json(raw_response_path, raw_response)
        raw_content_path.write_text(raw_content, encoding="utf-8")

        parsed_payload = transcribe.extract_json_block(raw_content)
        parsed_path = raw_dir / f"{record_id}.format_normalize_only.parsed.json"
        write_json(parsed_path, parsed_payload)

        normalized_payload = vision_core.safe_normalize_transcription_payload(
            parsed_payload,
            record_id=record_id,
            question_id=question_id,
            visual_refs=vision_core.build_visual_refs(question),
            prompt_version=str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
            model_name=model,
            question_context=question,
        )
        latex_span_patch_report: dict[str, Any] = {
            "schema": "latex_span_patch_application_v0.1",
            "task_count": 0,
            "applied": [],
            "rejected": [],
            "unresolved": [],
            "skip_reason": "no_latex_validation_tasks",
        }
        latex_span_patch_usage: dict[str, Any] = {}
        latex_span_patch_tasks = math_formula_gate.build_patch_tasks(normalized_payload)
        if latex_span_patch_tasks:
            deterministic_actions = math_formula_gate.build_deterministic_patch_actions(
                record_id=record_id,
                question_id=question_id,
                tasks=latex_span_patch_tasks,
            )
            if deterministic_actions.get("patches"):
                patched_payload, latex_span_patch_report = math_formula_gate.apply_patch_actions(
                    normalized_payload,
                    deterministic_actions,
                    latex_span_patch_tasks,
                )
                normalized_payload = vision_core.safe_normalize_transcription_payload(
                    patched_payload,
                    record_id=record_id,
                    question_id=question_id,
                    visual_refs=vision_core.build_visual_refs(question),
                    prompt_version=str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
                    model_name=model,
                    question_context=question,
                )
                latex_span_patch_report["deterministic"] = True
                latex_span_patch_tasks = math_formula_gate.build_patch_tasks(normalized_payload)
        if latex_span_patch_tasks:
            patch_input = math_formula_gate.build_patch_input(
                record_id=record_id,
                question_id=question_id,
                normalized_payload=normalized_payload,
                tasks=latex_span_patch_tasks,
            )
            patch_prompt = transcribe.build_latex_span_patch_prompt(question, record_id, patch_input)
            patch_prompt_path = raw_dir / f"{record_id}.latex_span_patch.prompt.txt"
            patch_prompt_path.write_text(patch_prompt, encoding="utf-8")
            patch_model_result = transcribe.call_latex_span_patch_model(api_key, model, patch_prompt, image_paths)
            latex_span_patch_usage = patch_model_result.get("usage", {}) or {}
            patch_raw_response_path = raw_dir / f"{record_id}.latex_span_patch.response.json"
            patch_raw_content_path = raw_dir / f"{record_id}.latex_span_patch.response.txt"
            write_json(patch_raw_response_path, patch_model_result.get("raw_response", {}) or {})
            patch_raw_content_path.write_text(str(patch_model_result.get("raw_content", "") or ""), encoding="utf-8")
            patch_parsed = transcribe.extract_json_block(str(patch_model_result.get("raw_content", "") or ""))
            patch_parsed_path = raw_dir / f"{record_id}.latex_span_patch.parsed.json"
            write_json(patch_parsed_path, patch_parsed)
            patched_payload, latex_span_patch_report = math_formula_gate.apply_patch_actions(
                normalized_payload,
                patch_parsed,
                latex_span_patch_tasks,
            )
            normalized_payload = vision_core.safe_normalize_transcription_payload(
                patched_payload,
                record_id=record_id,
                question_id=question_id,
                visual_refs=vision_core.build_visual_refs(question),
                prompt_version=str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
                model_name=model,
                question_context=question,
            )

        finished_at = now_iso()
        latency_seconds = round(time.perf_counter() - started_perf, 3)
        base_record["format_normalize_only"] = {
            "started_at": started_at,
            "finished_at": finished_at,
            "latency_seconds": latency_seconds,
            "usage": model_result.get("usage", {}) or {},
            "model": model,
            "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
            "prompt_path": str(prompt_path),
            "raw_response_path": str(raw_response_path),
            "raw_content_path": str(raw_content_path),
            "parsed_path": str(parsed_path),
            "image_count": len(image_paths),
            "latex_span_patch": latex_span_patch_report,
            "latex_span_patch_usage": latex_span_patch_usage,
        }
        base_record["transcription"] = normalized_payload
        return base_record
    except Exception as exc:
        failed_at = now_iso()
        latency_seconds = round(time.perf_counter() - started_perf, 3)
        error_message = f"{type(exc).__name__}: {exc}"
        (raw_dir / f"{record_id}.format_normalize_only.error.txt").write_text(error_message, encoding="utf-8")
        base_record["status"] = "failed"
        base_record["error"] = error_message
        base_record["format_normalize_only"] = {
            "started_at": started_at,
            "finished_at": failed_at,
            "latency_seconds": latency_seconds,
            "usage": {},
            "model": model,
            "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
            "prompt_path": str(prompt_path),
            "error_path": str(raw_dir / f"{record_id}.format_normalize_only.error.txt"),
            "image_count": len(image_paths),
        }
        return base_record


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply only the format-normalize model node to an existing visual transcription result set.")
    parser.add_argument("--source-results", required=True)
    parser.add_argument("--source-json", required=True, help="Prepared/full source json with questions array.")
    parser.add_argument("--base-manifest", default="", help="Existing reconciled_refined_manifest.json for rerender.")
    parser.add_argument("--results-out-dir", required=True)
    parser.add_argument("--manifest-out-dir", default="")
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default=transcribe.DEFAULT_MODEL)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--skip-if-already-normalized", action="store_true")
    args = parser.parse_args()

    if not args.api_key.strip():
        raise SystemExit("missing_api_key")

    source_results_path = Path(args.source_results).expanduser().resolve()
    source_json_path = Path(args.source_json).expanduser().resolve()
    base_manifest_path = Path(args.base_manifest).expanduser().resolve() if args.base_manifest.strip() else None
    results_out_dir = Path(args.results_out_dir).expanduser().resolve()
    manifest_out_dir = Path(args.manifest_out_dir).expanduser().resolve() if args.manifest_out_dir.strip() else None

    results_out_dir.mkdir(parents=True, exist_ok=True)
    if manifest_out_dir is not None:
        manifest_out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = results_out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    source_summary = read_json(source_results_path)
    source_records = [item for item in source_summary.get("records", []) if isinstance(item, dict)]
    source_questions = transcribe.load_source_questions(source_json_path)

    records_to_run = [item for item in source_records if str(item.get("status", "") or "") == "ok"]
    completed_by_id: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, int(args.concurrency or 1))) as executor:
        future_map = {}
        for record in records_to_run:
            question_id = str(record.get("question_id", "") or "")
            if args.skip_if_already_normalized and record_has_format_normalize_node(record):
                passthrough = copy.deepcopy(record)
                passthrough["source_visual_status"] = str(record.get("status", "") or "")
                passthrough["format_normalize_only"] = {
                    "started_at": "",
                    "finished_at": "",
                    "latency_seconds": 0.0,
                    "usage": {},
                    "model": args.model,
                    "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
                    "image_count": 0,
                    "skipped_reason": "already_contains_format_normalize_node",
                }
                completed_by_id[str(record.get("record_id", "") or "")] = passthrough
                continue
            question = source_questions.get(question_id)
            if not isinstance(question, dict):
                failed_record = {
                    "record_id": str(record.get("record_id", "") or ""),
                    "question_id": question_id,
                    "status": "failed",
                    "error": f"question_not_found_in_source_json: {question_id}",
                    "tag": str(record.get("tag", "") or ""),
                    "source_visual_status": str(record.get("status", "") or ""),
                    "format_normalize_only": {
                        "started_at": now_iso(),
                        "finished_at": now_iso(),
                        "latency_seconds": 0.0,
                        "usage": {},
                        "model": args.model,
                        "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
                        "image_count": 0,
                    },
                }
                completed_by_id[str(record.get("record_id", "") or "")] = failed_record
                continue

            question = copy.deepcopy(question)
            question["source_transcription_json"] = str(source_json_path)
            future = executor.submit(
                run_one_record,
                record=copy.deepcopy(record),
                question=question,
                api_key=args.api_key,
                model=args.model,
                raw_dir=raw_dir,
            )
            future_map[future] = str(record.get("record_id", "") or "")

        for future in as_completed(future_map):
            result_record = future.result()
            completed_by_id[str(result_record.get("record_id", "") or "")] = result_record

    output_records: list[dict[str, Any]] = []
    for record in source_records:
        record_id = str(record.get("record_id", "") or "")
        if record_id in completed_by_id:
            output_records.append(completed_by_id[record_id])
        else:
            passthrough = copy.deepcopy(record)
            passthrough["source_visual_status"] = str(record.get("status", "") or "")
            passthrough["format_normalize_only"] = {
                "started_at": "",
                "finished_at": "",
                "latency_seconds": 0.0,
                "usage": {},
                "model": args.model,
                "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
                "image_count": 0,
                "skipped_reason": "source_record_not_ok",
            }
            output_records.append(passthrough)

    ok_records = [item for item in output_records if str(item.get("status", "") or "") == "ok"]
    failed_records = [item for item in output_records if str(item.get("status", "") or "") != "ok"]

    results_payload = {
        "schema_version": "format_normalize_only_reprocess_v0.1",
        "generated_at": now_iso(),
        "source_visual_results": str(source_results_path),
        "source_question_json": str(source_json_path),
        "source_manifest": str(base_manifest_path),
        "model": args.model,
        "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
        "record_count": len(output_records),
        "ok_count": len(ok_records),
        "failed_count": len(failed_records),
        "format_normalize_only_usage_totals": aggregate_usage(ok_records),
        "format_normalize_only_latency_summary": aggregate_latency(ok_records),
        "records": output_records,
    }
    compact_payload = render_compact(output_records)

    results_path = results_out_dir / "visual_transcription_results.format_normalize_only.json"
    compact_path = results_out_dir / "visual_transcription_compact.format_normalize_only.json"
    write_json(results_path, results_payload)
    write_json(compact_path, compact_payload)

    rerender_meta = {
        "manifest_path": "",
        "html_path": "",
        "updated_question_count": 0,
        "changed_fields_summary": {"stem": 0, "answer": 0, "analysis": 0},
    }
    if base_manifest_path is not None and manifest_out_dir is not None:
        manifest_name = "reconciled_refined_manifest.format_normalize_only.json"
        html_name = "question_asset_review.format_normalize_only.html"
        rerender_meta = rebuild_manifest_with_new_text(
            base_manifest_path=base_manifest_path,
            manifest_out_path=manifest_out_dir / manifest_name,
            html_out_path=manifest_out_dir / html_name,
            results_by_question_id={str(item.get("question_id", "") or ""): item for item in output_records if str(item.get("status", "") or "") == "ok"},
            results_meta={
                "results_path": str(results_path),
                "model": args.model,
                "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
            },
        )

    summary = {
        "mode": "format_normalize_only_existing_results",
        "source_visual_results": str(source_results_path),
        "source_question_json": str(source_json_path),
        "source_manifest": str(base_manifest_path) if base_manifest_path is not None else "",
        "results_path": str(results_path),
        "compact_path": str(compact_path),
        "rerender_manifest_path": rerender_meta["manifest_path"],
        "rerender_html_path": rerender_meta["html_path"],
        "record_count": len(output_records),
        "ok_count": len(ok_records),
        "failed_count": len(failed_records),
        "format_normalize_only_usage_totals": results_payload["format_normalize_only_usage_totals"],
        "format_normalize_only_latency_summary": results_payload["format_normalize_only_latency_summary"],
        "changed_fields_summary": rerender_meta["changed_fields_summary"],
        "updated_question_count": rerender_meta["updated_question_count"],
        "model": args.model,
        "prompt_version": str(transcribe.FORMAT_NORMALIZE_PROMPT.get("prompt_version", "") or ""),
    }
    summary_path = results_out_dir / "format_normalize_only_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
