from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import visual_transcription_core as vision_core


PipelineFn = Callable[..., Any]

PIPELINE_VERSION = "vision_pipeline_v0.4"
PIPELINE_TOPOLOGY = {
    "version": PIPELINE_VERSION,
    "final_contract": "general_vision_v0.1",
    "parallel_layers": [
        {
            "layer": 1,
            "mode": "parallel",
            "nodes": ["visual_structure_node", "raw_blocks_prompt_node"],
        },
        {
            "layer": 2,
            "mode": "serial",
            "nodes": ["raw_blocks_model_node", "raw_blocks_parse_node"],
        },
        {
            "layer": 3,
            "mode": "serial",
            "nodes": ["field_mapping_prompt_node", "field_mapping_model_node", "field_mapping_parse_node"],
        },
        {
            "layer": 4,
            "mode": "serial",
            "nodes": [
                "format_normalize_prompt_node",
                "format_normalize_model_node",
                "format_normalize_parse_node",
            ],
        },
        {
            "layer": 5,
            "mode": "serial",
            "nodes": ["math_normalize_node"],
        },
        {
            "layer": 6,
            "mode": "parallel",
            "nodes": ["render_contract_node", "quality_audit_node"],
        },
        {
            "layer": 7,
            "mode": "serial",
            "nodes": ["record_assemble_node"],
        },
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _run_named_node(node_name: str, fn: PipelineFn, *args: Any, **kwargs: Any) -> dict[str, Any]:
    started_at = time.perf_counter()
    result = fn(*args, **kwargs)
    latency_seconds = round(time.perf_counter() - started_at, 4)
    return {
        "node": node_name,
        "status": "ok",
        "latency_seconds": latency_seconds,
        "result": result,
    }


def run_visual_structure_node(question: dict[str, Any]) -> dict[str, Any]:
    image_paths = [str(path) for path in vision_core.collect_image_paths(question)]
    visual_refs = vision_core.build_visual_refs(question)
    return {
        "visual_refs": visual_refs,
        "image_paths": image_paths,
        "image_count": len(image_paths),
        "question_uid": str(question.get("question_uid", "") or ""),
        "gating_result": question.get("gating_result", {}) or {},
        "option_visual_blocks": question.get("option_visual_blocks", []) or [],
        "staged_visual_assets": question.get("staged_visual_assets", []) or [],
    }


def run_prompt_packet_node(
    *,
    question: dict[str, Any],
    item: dict[str, Any],
    record_id: str,
    prompt_builder: PipelineFn,
    prompt_version: str,
    model_name: str,
    source_json_path: Path,
) -> dict[str, Any]:
    prompt = str(prompt_builder(question, record_id))
    return {
        "prepared_payload": {
            "record_id": record_id,
            "question_id": str(item["question_id"]),
            "source_transcription_json": str(source_json_path),
            "question_image": question.get("question_image", ""),
            "stem_image": question.get("stem_image", ""),
            "analysis_image": question.get("analysis_image", ""),
            "question_uid": question.get("question_uid", ""),
            "gating_result": question.get("gating_result", {}),
            "option_visual_blocks": question.get("option_visual_blocks", []),
            "staged_visual_assets": question.get("staged_visual_assets", []),
            "image_count": len(vision_core.collect_image_paths(question)),
            "raw_blocks_prompt": prompt,
            "prompt_version": prompt_version,
            "model_name": model_name,
            "tag": item.get("tag", ""),
        },
        "prompt": prompt,
    }


def run_field_mapping_prompt_node(
    *,
    question: dict[str, Any],
    record_id: str,
    raw_blocks_payload: dict[str, Any],
    prompt_builder: PipelineFn,
) -> dict[str, Any]:
    prompt = str(prompt_builder(question, record_id, raw_blocks_payload))
    return {
        "prompt": prompt,
        "raw_blocks_count": len(raw_blocks_payload.get("visible_blocks", []) or []),
    }


def run_format_normalize_prompt_node(
    *,
    question: dict[str, Any],
    record_id: str,
    field_mapping_payload: dict[str, Any],
    prompt_builder: PipelineFn,
) -> dict[str, Any]:
    prompt = str(prompt_builder(question, record_id, field_mapping_payload))
    return {
        "prompt": prompt,
        "field_presence": sorted(
            key
            for key in ("stem_text_md", "answer_text_md", "analysis_text_md", "handwriting_text_md")
            if isinstance(field_mapping_payload.get(key), str) and field_mapping_payload.get(key, "").strip()
        ),
    }


def run_raw_transcription_node(
    *,
    api_key: str,
    model_name: str,
    prompt: str,
    image_paths: list[str],
    call_model_fn: PipelineFn,
) -> dict[str, Any]:
    path_objects = [Path(path) for path in image_paths]
    return call_model_fn(api_key, model_name, prompt, path_objects)


def run_json_parse_node(raw_content: str, extract_json_fn: PipelineFn) -> dict[str, Any]:
    return dict(extract_json_fn(raw_content))


def run_math_normalize_node(
    *,
    parsed_payload: dict[str, Any],
    record_id: str,
    question_id: str,
    visual_refs: dict[str, Any],
    prompt_version: str,
    model_name: str,
    question_context: dict[str, Any],
) -> dict[str, Any]:
    return vision_core.safe_normalize_transcription_payload(
        parsed_payload,
        record_id=record_id,
        question_id=question_id,
        visual_refs=visual_refs,
        prompt_version=prompt_version,
        model_name=model_name,
        question_context=question_context,
    )


def run_render_contract_node(normalized_payload: dict[str, Any]) -> dict[str, Any]:
    display_fields = normalized_payload.get("display_normalized_text", {}) or {}
    return {
        "record_id": str(normalized_payload.get("record_id", "") or ""),
        "question_id": str(normalized_payload.get("question_id", "") or ""),
        "display_fields_present": sorted(
            key
            for key, value in display_fields.items()
            if isinstance(value, str) and value.strip()
        ),
        "has_question_visual_structure": isinstance(
            normalized_payload.get("question_visual_structure"), dict
        ),
        "has_structure_mapping": isinstance(normalized_payload.get("structure_mapping"), dict),
    }


def run_quality_audit_node(normalized_payload: dict[str, Any]) -> dict[str, Any]:
    quality_gate = normalized_payload.get("quality_gate", {}) or {}
    return {
        "ingest_decision": str(quality_gate.get("ingest_decision", "allow") or "allow"),
        "risk_span_count": len(normalized_payload.get("risk_spans", []) or []),
        "uncertain_span_count": len(normalized_payload.get("uncertain_spans", []) or []),
        "field_boundary_flag_count": len(normalized_payload.get("field_boundary_flags", []) or []),
    }


def run_record_assemble_node(
    *,
    record_id: str,
    item: dict[str, Any],
    source_json_path: Path,
    structure_result: dict[str, Any],
    model_result: dict[str, Any],
    normalized_payload: dict[str, Any],
    started_at_iso: str,
    finished_at_iso: str,
    latency_seconds: float,
    pipeline_trace: dict[str, Any],
) -> dict[str, Any]:
    visual_refs = structure_result.get("visual_refs", {}) or {}
    return {
        "record_id": record_id,
        "question_id": item["question_id"],
        "source_transcription_json": str(source_json_path),
        "status": "ok",
        "tag": item.get("tag", ""),
        "question_image": visual_refs.get("question_image", ""),
        "stem_image": visual_refs.get("stem_image", ""),
        "analysis_image": visual_refs.get("analysis_image", ""),
        "request_started_at": started_at_iso,
        "request_finished_at": finished_at_iso,
        "latency_seconds": latency_seconds,
        "usage": model_result.get("usage", {}) or {},
        "pipeline_trace": pipeline_trace,
        "transcription": normalized_payload,
    }


def build_failure_record(
    *,
    record_id: str,
    question_id: str,
    source_json_path: Path,
    tag: str,
    error: str,
    started_at_iso: str = "",
    finished_at_iso: str = "",
    latency_seconds: float = 0.0,
    usage: dict[str, Any] | None = None,
    pipeline_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "record_id": record_id,
        "question_id": question_id,
        "source_transcription_json": str(source_json_path),
        "status": "failed",
        "error": error,
        "tag": tag,
        "pipeline_trace": pipeline_trace or {},
    }
    if started_at_iso:
        payload["request_started_at"] = started_at_iso
    if finished_at_iso:
        payload["request_finished_at"] = finished_at_iso
    if latency_seconds:
        payload["latency_seconds"] = latency_seconds
    if usage:
        payload["usage"] = usage
    return payload


def run_question_pipeline(
    *,
    item: dict[str, Any],
    question: dict[str, Any],
    source_json_path: Path,
    record_id: str,
    model_name: str,
    prompt_version: str,
    api_key: str,
    prepare_only: bool,
    raw_blocks_prompt_builder: PipelineFn,
    raw_blocks_call_model_fn: PipelineFn,
    field_mapping_prompt_builder: PipelineFn,
    field_mapping_call_model_fn: PipelineFn,
    format_normalize_prompt_builder: PipelineFn,
    format_normalize_call_model_fn: PipelineFn,
    extract_json_fn: PipelineFn,
) -> dict[str, Any]:
    pipeline_trace: dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "final_contract": "general_vision_v0.1",
        "parallel_layers": PIPELINE_TOPOLOGY["parallel_layers"],
        "nodes": [],
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        structure_future = executor.submit(
            _run_named_node,
            "visual_structure_node",
            run_visual_structure_node,
            question,
        )
        packet_future = executor.submit(
            _run_named_node,
            "raw_blocks_prompt_node",
            run_prompt_packet_node,
            question=question,
            item=item,
            record_id=record_id,
            prompt_builder=raw_blocks_prompt_builder,
            prompt_version=prompt_version,
            model_name=model_name,
            source_json_path=source_json_path,
        )
        structure_node = structure_future.result()
        packet_node = packet_future.result()

    pipeline_trace["nodes"].extend([structure_node, packet_node])
    structure_result = structure_node["result"]
    packet_result = packet_node["result"]
    prepared_payload = dict(packet_result["prepared_payload"])

    if not structure_result.get("image_paths"):
        return {
            "prepared_payload": prepared_payload,
            "record": build_failure_record(
                record_id=record_id,
                question_id=str(item["question_id"]),
                source_json_path=source_json_path,
                tag=str(item.get("tag", "") or ""),
                error="no_images_found",
                pipeline_trace=pipeline_trace,
            ),
        }

    if prepare_only:
        return {
            "prepared_payload": prepared_payload,
            "record": {
                "record_id": record_id,
                "question_id": item["question_id"],
                "source_transcription_json": str(source_json_path),
                "status": "prepared",
                "tag": item.get("tag", ""),
                "image_count": int(structure_result.get("image_count", 0)),
                "pipeline_trace": pipeline_trace,
            },
        }

    started_at_iso = utc_now_iso()
    started_perf = time.perf_counter()
    raw_blocks_model_result: dict[str, Any] | None = None
    field_mapping_model_result: dict[str, Any] | None = None
    format_normalize_model_result: dict[str, Any] | None = None
    try:
        model_node = _run_named_node(
            "raw_blocks_model_node",
            run_raw_transcription_node,
            api_key=api_key,
            model_name=model_name,
            prompt=str(packet_result["prompt"]),
            image_paths=list(structure_result["image_paths"]),
            call_model_fn=raw_blocks_call_model_fn,
        )
        pipeline_trace["nodes"].append(model_node)
        raw_blocks_model_result = model_node["result"]

        parse_node = _run_named_node(
            "raw_blocks_parse_node",
            run_json_parse_node,
            str(raw_blocks_model_result.get("raw_content", "") or ""),
            extract_json_fn,
        )
        pipeline_trace["nodes"].append(parse_node)
        raw_blocks_payload = parse_node["result"]

        mapping_prompt_node = _run_named_node(
            "field_mapping_prompt_node",
            run_field_mapping_prompt_node,
            question=question,
            record_id=record_id,
            raw_blocks_payload=raw_blocks_payload,
            prompt_builder=field_mapping_prompt_builder,
        )
        pipeline_trace["nodes"].append(mapping_prompt_node)
        prepared_payload["field_mapping_prompt"] = str(mapping_prompt_node["result"].get("prompt", "") or "")
        prepared_payload["raw_blocks_payload"] = raw_blocks_payload

        field_model_node = _run_named_node(
            "field_mapping_model_node",
            run_raw_transcription_node,
            api_key=api_key,
            model_name=model_name,
            prompt=str(mapping_prompt_node["result"]["prompt"]),
            image_paths=list(structure_result["image_paths"]),
            call_model_fn=field_mapping_call_model_fn,
        )
        pipeline_trace["nodes"].append(field_model_node)
        field_mapping_model_result = field_model_node["result"]

        field_parse_node = _run_named_node(
            "field_mapping_parse_node",
            run_json_parse_node,
            str(field_mapping_model_result.get("raw_content", "") or ""),
            extract_json_fn,
        )
        pipeline_trace["nodes"].append(field_parse_node)
        parsed_payload = field_parse_node["result"]

        format_prompt_node = _run_named_node(
            "format_normalize_prompt_node",
            run_format_normalize_prompt_node,
            question=question,
            record_id=record_id,
            field_mapping_payload=parsed_payload,
            prompt_builder=format_normalize_prompt_builder,
        )
        pipeline_trace["nodes"].append(format_prompt_node)
        prepared_payload["format_normalize_prompt"] = str(format_prompt_node["result"].get("prompt", "") or "")
        prepared_payload["field_mapping_payload"] = parsed_payload

        format_model_node = _run_named_node(
            "format_normalize_model_node",
            run_raw_transcription_node,
            api_key=api_key,
            model_name=model_name,
            prompt=str(format_prompt_node["result"]["prompt"]),
            image_paths=list(structure_result["image_paths"]),
            call_model_fn=format_normalize_call_model_fn,
        )
        pipeline_trace["nodes"].append(format_model_node)
        format_normalize_model_result = format_model_node["result"]

        format_parse_node = _run_named_node(
            "format_normalize_parse_node",
            run_json_parse_node,
            str(format_normalize_model_result.get("raw_content", "") or ""),
            extract_json_fn,
        )
        pipeline_trace["nodes"].append(format_parse_node)
        parsed_payload = format_parse_node["result"]

        normalize_node = _run_named_node(
            "math_normalize_node",
            run_math_normalize_node,
            parsed_payload=parsed_payload,
            record_id=record_id,
            question_id=str(item["question_id"]),
            visual_refs=structure_result["visual_refs"],
            prompt_version=prompt_version,
            model_name=model_name,
            question_context=question,
        )
        pipeline_trace["nodes"].append(normalize_node)
        normalized_payload = normalize_node["result"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            render_future = executor.submit(
                _run_named_node,
                "render_contract_node",
                run_render_contract_node,
                normalized_payload,
            )
            audit_future = executor.submit(
                _run_named_node,
                "quality_audit_node",
                run_quality_audit_node,
                normalized_payload,
            )
            render_node = render_future.result()
            audit_node = audit_future.result()
        pipeline_trace["nodes"].extend([render_node, audit_node])
        pipeline_trace["render_contract"] = render_node["result"]
        pipeline_trace["quality_audit"] = audit_node["result"]

        finished_at_iso = utc_now_iso()
        latency_seconds = round(time.perf_counter() - started_perf, 3)
        assemble_node = _run_named_node(
            "record_assemble_node",
            run_record_assemble_node,
            record_id=record_id,
            item=item,
            source_json_path=source_json_path,
            structure_result=structure_result,
            model_result={
                "usage": {
                    key: (
                        (raw_blocks_model_result or {}).get("usage", {}) or {}
                    ).get(key, 0)
                    + ((field_mapping_model_result or {}).get("usage", {}) or {}).get(key, 0)
                    + ((format_normalize_model_result or {}).get("usage", {}) or {}).get(key, 0)
                    for key in (
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "input_tokens",
                        "output_tokens",
                        "image_tokens",
                    )
                }
            },
            normalized_payload=normalized_payload,
            started_at_iso=started_at_iso,
            finished_at_iso=finished_at_iso,
            latency_seconds=latency_seconds,
            pipeline_trace=pipeline_trace,
        )
        pipeline_trace["record_assemble_summary"] = {
            "node": "record_assemble_node",
            "status": "ok",
            "latency_seconds": assemble_node["latency_seconds"],
        }
        return {
            "prepared_payload": prepared_payload,
            "raw_blocks_response": (raw_blocks_model_result or {}).get("raw_response", {}),
            "raw_blocks_content": str((raw_blocks_model_result or {}).get("raw_content", "") or ""),
            "field_mapping_response": (field_mapping_model_result or {}).get("raw_response", {}),
            "field_mapping_content": str((field_mapping_model_result or {}).get("raw_content", "") or ""),
            "format_normalize_response": (format_normalize_model_result or {}).get("raw_response", {}),
            "format_normalize_content": str((format_normalize_model_result or {}).get("raw_content", "") or ""),
            "record": assemble_node["result"],
        }
    except Exception as exc:  # noqa: BLE001
        finished_at_iso = utc_now_iso()
        latency_seconds = round(time.perf_counter() - started_perf, 3)
        usage_totals = {
            key: (
                ((raw_blocks_model_result or {}).get("usage", {}) or {}).get(key, 0)
                + ((field_mapping_model_result or {}).get("usage", {}) or {}).get(key, 0)
                + ((format_normalize_model_result or {}).get("usage", {}) or {}).get(key, 0)
            )
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "input_tokens",
                "output_tokens",
                "image_tokens",
            )
        }
        return {
            "prepared_payload": prepared_payload,
            "raw_blocks_response": (raw_blocks_model_result or {}).get("raw_response", {}),
            "raw_blocks_content": str((raw_blocks_model_result or {}).get("raw_content", "") or ""),
            "field_mapping_response": (field_mapping_model_result or {}).get("raw_response", {}),
            "field_mapping_content": str((field_mapping_model_result or {}).get("raw_content", "") or ""),
            "format_normalize_response": (format_normalize_model_result or {}).get("raw_response", {}),
            "format_normalize_content": str((format_normalize_model_result or {}).get("raw_content", "") or ""),
            "record": build_failure_record(
                record_id=record_id,
                question_id=str(item["question_id"]),
                source_json_path=source_json_path,
                tag=str(item.get("tag", "") or ""),
                error=str(exc),
                started_at_iso=started_at_iso,
                finished_at_iso=finished_at_iso,
                latency_seconds=latency_seconds,
                usage=usage_totals,
                pipeline_trace=pipeline_trace,
            ),
        }
