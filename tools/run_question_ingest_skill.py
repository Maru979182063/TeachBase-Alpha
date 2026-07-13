from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        return str(path.resolve())


def safe_slug(text: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(text or "").strip())
    value = value.strip("._-")
    return value[:80].rstrip("._-") or "item"


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    timeout: int | None = None,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": now(),
        "log_path": str(log_path),
    }


def question_count(source_json: Path) -> int:
    payload = read_json(source_json)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    return len([item for item in questions if isinstance(item, dict)])


def make_absolute_source(source_json: Path, out_path: Path) -> Path:
    payload = read_json(source_json)
    base = source_json.parent
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    for question in questions:
        if not isinstance(question, dict):
            continue
        for key in ("question_image", "stem_image", "analysis_image"):
            raw = str(question.get(key, "") or "").strip()
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = (base / path).resolve()
            question[key] = str(path)
    write_json(out_path, payload)
    return out_path


def load_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = read_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    records = payload.get("records")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict)]
    return []


def record_key(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("question_id") or "").strip()


def build_manifest(source_json: Path, out_path: Path, question_ids: list[str], tag: str) -> Path:
    items = [
        {
            "sample_id": qid,
            "source_transcription_json": str(source_json.resolve()),
            "question_id": qid,
            "tag": tag,
        }
        for qid in question_ids
    ]
    write_json(out_path, {"schema_version": "visual_transcription_manifest_v0.1", "items": items})
    return out_path


def split_list(items: list[str], shard_count: int) -> list[list[str]]:
    shard_count = max(1, shard_count)
    return [items[index::shard_count] for index in range(shard_count)]


def failed_question_ids(results_path: Path | None) -> list[str]:
    failed_ids: list[str] = []
    seen: set[str] = set()
    for record in load_records(results_path):
        if str(record.get("status", "") or "") == "ok":
            continue
        question_id = str(record.get("question_id") or record.get("record_id") or "").strip()
        if question_id and question_id not in seen:
            seen.add(question_id)
            failed_ids.append(question_id)
    return failed_ids


def run_transcription_shards(
    *,
    args: argparse.Namespace,
    paths: dict[str, Path],
    env: dict[str, str],
    question_ids: list[str],
    run_prefix: str,
    log_prefix: str,
) -> list[Path]:
    shard_dirs: list[Path] = []
    futures: list[concurrent.futures.Future] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.transcription_concurrency)) as pool:
        for index, shard_ids in enumerate(split_list(question_ids, args.transcription_concurrency), start=1):
            if not shard_ids:
                continue
            shard_manifest = paths["transcription_dir"] / f"{run_prefix}_manifest_{index:02d}.json"
            build_manifest(paths["abs_source_json"], shard_manifest, shard_ids, f"{run_prefix}_{index:02d}")
            shard_out = paths["transcription_dir"] / f"{run_prefix}_{index:02d}"
            shard_dirs.append(shard_out)
            cmd = [
                sys.executable,
                "tools/teacher_handout_visual_transcribe_doubao.py",
                "--manifest",
                str(shard_manifest),
                "--model",
                args.model,
                "--out-dir",
                str(shard_out),
                "--sleep-seconds",
                str(args.sleep_seconds),
            ]
            futures.append(
                pool.submit(
                    run_cmd,
                    cmd,
                    cwd=paths["workspace"],
                    env=env,
                    log_path=paths["logs"] / f"{log_prefix}_{index:02d}.log",
                    timeout=None,
                )
            )
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result["returncode"] != 0:
                raise RuntimeError(f"{log_prefix}_failed: {result['log_path']}")
    return shard_dirs


def merge_transcription_runs(
    *,
    paths: dict[str, Path],
    env: dict[str, str],
    run_dirs: list[Path],
    out_dir: Path,
    log_name: str,
) -> Path:
    cmd = [sys.executable, "tools/merge_visual_transcription_results.py"]
    for run_dir in run_dirs:
        cmd += ["--run-dir", str(run_dir)]
    cmd += ["--out-dir", str(out_dir)]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / log_name)
    if result["returncode"] != 0:
        raise RuntimeError(f"merge_transcription_failed: {result['log_path']}")
    return out_dir / "visual_transcription_results.json"


def _same_long_source(question: dict[str, Any]) -> bool:
    question_image_raw = str(question.get("question_image", "") or "").strip()
    stem_image_raw = str(question.get("stem_image", "") or "").strip()
    analysis_image_raw = str(question.get("analysis_image", "") or "").strip()
    return bool(
        question_image_raw
        and stem_image_raw
        and analysis_image_raw
        and Path(question_image_raw) == Path(stem_image_raw) == Path(analysis_image_raw)
    )


def _resolve_any_existing_image(question: dict[str, Any]) -> Path | None:
    for key in ("question_image", "stem_image", "analysis_image"):
        raw = str(question.get(key, "") or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            return path
    return None


def _read_image_size(path: Path | None) -> tuple[int, int]:
    if path is None:
        return 0, 0
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return 0, 0


def _build_figure_routing_decision(question: dict[str, Any]) -> dict[str, Any]:
    image_path = _resolve_any_existing_image(question)
    width, height = _read_image_size(image_path)
    gate = question.get("image_need_gate") if isinstance(question.get("image_need_gate"), dict) else {}
    image_presence = str(gate.get("image_presence", "") or "").strip().lower()
    same_long_source = _same_long_source(question)
    long_image = width > 0 and height > 0 and (height >= 1300 or height >= width * 1.55)
    planner_panel_presence = "panel" in image_presence

    if same_long_source:
        force_serial = True
        reason = "same_source_long_container"
    elif long_image:
        force_serial = True
        reason = "long_image"
    elif planner_panel_presence:
        force_serial = True
        reason = "planner_panel_presence"
    else:
        force_serial = False
        reason = "parallel_ok"

    return {
        "force_serial": force_serial,
        "reason": reason,
        "same_long_source": same_long_source,
        "image_path": str(image_path) if image_path else "",
        "image_width": width,
        "image_height": height,
        "long_image": long_image,
        "long_image_threshold_hit": bool(width > 0 and height > 0 and (height >= 1300 or height >= width * 1.55)),
        "image_presence": image_presence,
        "planner_panel_presence": planner_panel_presence,
        "gate_where": list(gate.get("where", [])) if isinstance(gate.get("where", []), list) else [],
    }


def _should_serial_figure_detection(question: dict[str, Any]) -> tuple[bool, str]:
    decision = _build_figure_routing_decision(question)
    return bool(decision.get("force_serial")), str(decision.get("reason", "") or "parallel_ok")


def _build_question_job_payload(source_payload: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(source_payload)
    payload["questions"] = questions
    return payload


def state_update(state_path: Path, **kwargs: Any) -> dict[str, Any]:
    state = read_json(state_path) if state_path.exists() else {}
    state.update(kwargs)
    state["updated_at"] = now()
    write_json(state_path, state)
    return state


def run_planner_gate(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str]) -> Path:
    summary_path = paths["gate_dir"] / "model_image_need_gate_summary.json"
    expected_count = question_count(paths["abs_source_json"])
    if summary_path.exists() and not args.force_planner:
        summary = read_json(summary_path)
        if int(summary.get("question_count", 0) or 0) == expected_count:
            return summary_path
    cmd = [
        sys.executable,
        "tools/model_image_need_gate.py",
        "--source-json",
        str(paths["abs_source_json"]),
        "--out-dir",
        str(paths["gate_dir"]),
        "--model",
        args.model,
        "--concurrency",
        str(args.planner_concurrency),
        "--timeout",
        str(args.model_timeout),
        "--retries",
        str(args.model_retries),
    ]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "01_model_gate.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"planner_gate_failed: {result['log_path']}")
    return summary_path


def build_candidate_sources(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str]) -> dict[str, Path]:
    cmd = [
        sys.executable,
        "tools/build_figure_candidate_source.py",
        "--source-json",
        str(paths["abs_source_json"]),
        "--gate-dir",
        str(paths["gate_dir"]),
        "--candidate-json",
        str(paths["candidate_json"]),
        "--no-image-json",
        str(paths["no_image_json"]),
        "--shard-dir",
        str(paths["candidate_shard_dir"]),
        "--shards",
        str(args.figure_concurrency),
    ]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "02_build_candidates.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"build_candidates_failed: {result['log_path']}")
    return {
        "summary": paths["candidate_json"].with_suffix(".summary.json"),
        "candidate_json": paths["candidate_json"],
        "no_image_json": paths["no_image_json"],
    }


def run_transcription_retries(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str]) -> Path | None:
    existing_results_path = Path(args.transcription_results).expanduser().resolve() if args.transcription_results else None
    existing_records = load_records(existing_results_path)
    existing_by_key = {record_key(record): record for record in existing_records if record_key(record)}
    payload = read_json(paths["abs_source_json"])
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    all_ids = [str(q.get("question_id", "") or "") for q in questions if isinstance(q, dict)]
    retry_ids = [
        qid
        for qid in all_ids
        if not existing_by_key.get(qid) or existing_by_key.get(qid, {}).get("status") != "ok"
    ]
    write_json(paths["transcription_dir"] / "retry_question_ids.json", retry_ids)
    if not retry_ids or args.skip_transcription_retry:
        return existing_results_path

    shard_dirs = run_transcription_shards(
        args=args,
        paths=paths,
        env=env,
        question_ids=retry_ids,
        run_prefix="transcription_shard",
        log_prefix="03_transcription_shard",
    )
    merge_inputs = ([existing_results_path.parent] if existing_results_path else []) + shard_dirs
    current_results = merge_transcription_runs(
        paths=paths,
        env=env,
        run_dirs=merge_inputs,
        out_dir=paths["transcription_dir"] / "merged",
        log_name="04_merge_transcription.log",
    )

    recovery_rows: list[dict[str, Any]] = []
    for attempt in range(1, max(0, int(args.transcription_recovery_attempts or 0)) + 1):
        failed_ids = failed_question_ids(current_results)
        recovery_rows.append(
            {
                "attempt": attempt,
                "input_results": str(current_results),
                "failed_count": len(failed_ids),
                "failed_question_ids": failed_ids,
            }
        )
        if not failed_ids:
            break
        recovery_shards = run_transcription_shards(
            args=args,
            paths=paths,
            env=env,
            question_ids=failed_ids,
            run_prefix=f"recovery_{attempt:02d}",
            log_prefix=f"04_transcription_recovery_{attempt:02d}",
        )
        current_results = merge_transcription_runs(
            paths=paths,
            env=env,
            run_dirs=[current_results.parent] + recovery_shards,
            out_dir=paths["transcription_dir"] / f"merged_recovery_{attempt:02d}",
            log_name=f"04_merge_transcription_recovery_{attempt:02d}.log",
        )
        recovery_rows[-1]["output_results"] = str(current_results)
        recovery_rows[-1]["remaining_failed_count"] = len(failed_question_ids(current_results))

    final_failed_ids = failed_question_ids(current_results)
    write_json(
        paths["transcription_dir"] / "transcription_recovery_summary.json",
        {
            "schema_version": "transcription_recovery.v0.1",
            "attempt_count": len(recovery_rows),
            "final_results": str(current_results),
            "final_failed_count": len(final_failed_ids),
            "final_failed_question_ids": final_failed_ids,
            "rows": recovery_rows,
        },
    )
    return current_results


def _record_has_format_normalize_node(record: dict[str, Any]) -> bool:
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


def inspect_format_normalize_backfill(results_path: Path | None) -> dict[str, Any]:
    if results_path is None or not results_path.exists():
        return {
            "status": "missing_results",
            "results_path": str(results_path) if results_path else "",
            "record_count": 0,
            "ok_count": 0,
            "needs_backfill_count": 0,
            "already_normalized_count": 0,
            "needs_backfill_question_ids": [],
        }
    records = load_records(results_path)
    ok_records = [item for item in records if item.get("status") == "ok"]
    needs_backfill_ids: list[str] = []
    already_normalized_count = 0
    for record in ok_records:
        question_id = str(record.get("question_id", "") or record.get("record_id", "") or "").strip()
        if _record_has_format_normalize_node(record):
            already_normalized_count += 1
        else:
            needs_backfill_ids.append(question_id)
    return {
        "status": "inspect_ok",
        "results_path": str(results_path),
        "record_count": len(records),
        "ok_count": len(ok_records),
        "needs_backfill_count": len(needs_backfill_ids),
        "already_normalized_count": already_normalized_count,
        "needs_backfill_question_ids": needs_backfill_ids,
    }


def run_format_normalize_backfill(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str], visual_results: Path | None) -> tuple[Path | None, dict[str, Any]]:
    paths["transcription_format_dir"].mkdir(parents=True, exist_ok=True)
    summary_path = paths["transcription_format_dir"] / "format_normalize_only_summary.json"
    inspection = inspect_format_normalize_backfill(visual_results)
    if visual_results is None or not visual_results.exists():
        write_json(summary_path, inspection)
        return visual_results, inspection
    if int(inspection.get("needs_backfill_count", 0) or 0) <= 0:
        inspection["status"] = "skipped_already_normalized"
        write_json(summary_path, inspection)
        return visual_results, inspection

    cmd = [
        sys.executable,
        "tools/apply_format_normalize_existing_results.py",
        "--source-results",
        str(visual_results),
        "--source-json",
        str(paths["abs_source_json"]),
        "--results-out-dir",
        str(paths["transcription_format_dir"]),
        "--api-key",
        str(args.api_key or ""),
        "--model",
        str(args.model or ""),
        "--concurrency",
        str(max(1, int(args.transcription_concurrency or 1))),
        "--skip-if-already-normalized",
    ]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "04_5_format_normalize_backfill.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"format_normalize_backfill_failed: {result['log_path']}")
    if not summary_path.exists():
        raise RuntimeError(f"format_normalize_backfill_summary_missing: {summary_path}")
    summary = read_json(summary_path)
    summary["status"] = "backfill_done"
    summary["inspection"] = inspection
    summary["log_path"] = str(paths["logs"] / "04_5_format_normalize_backfill.log")
    return paths["transcription_format_dir"] / "visual_transcription_results.format_normalize_only.json", summary


def run_figure_detection(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str]) -> Path:
    candidate_summary = read_json(paths["candidate_json"].with_suffix(".summary.json"))
    shard_paths = [Path(item).resolve() for item in candidate_summary.get("shard_paths", [])]
    prepared_paths: list[Path] = []
    figure_jobs_dir = paths["candidate_shard_dir"]
    serial_jobs: list[tuple[Path, Path, Path, dict[str, Any]]] = []
    parallel_jobs: list[tuple[Path, Path, Path, dict[str, Any]]] = []
    routing_rows: list[dict[str, Any]] = []
    job_counter = 0
    figure_env = dict(env)
    figure_env.setdefault(
        "VISUAL_RUNTIME_RUN_ID",
        f"visualrun_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_slug(paths['out_dir'].name)}",
    )

    for shard_index, shard_path in enumerate(shard_paths, start=1):
        payload = read_json(shard_path)
        questions = payload.get("questions", []) if isinstance(payload, dict) else []
        if not questions:
            continue
        parallel_questions: list[dict[str, Any]] = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("question_id", "") or question.get("record_id", "") or f"q{job_counter + 1}")
            routing_decision = _build_figure_routing_decision(question)
            force_serial = bool(routing_decision.get("force_serial"))
            serial_reason = str(routing_decision.get("reason", "") or "parallel_ok")
            routing_rows.append({
                "question_id": question_id,
                "source_shard": str(shard_path),
                "mode": "serial" if force_serial else "parallel",
                **routing_decision,
            })
            if force_serial:
                job_counter += 1
                job_path = figure_jobs_dir / f"{shard_path.stem}__serial__{safe_slug(question_id)}.json"
                out_json = paths["figure_dir"] / f"prepared_job_{job_counter:02d}_{safe_slug(question_id)}.json"
                log_path = paths["logs"] / f"05_figure_detection_serial_{job_counter:02d}_{safe_slug(question_id)}.log"
                write_json(job_path, _build_question_job_payload(payload, [question]))
                serial_jobs.append((job_path, out_json, log_path, {"question_id": question_id, "reason": serial_reason}))
            else:
                parallel_questions.append(question)

        if parallel_questions:
            job_counter += 1
            job_path = figure_jobs_dir / f"{shard_path.stem}__parallel.json"
            out_json = paths["figure_dir"] / f"prepared_job_{job_counter:02d}_parallel.json"
            log_path = paths["logs"] / f"05_figure_detection_parallel_{job_counter:02d}.log"
            write_json(job_path, _build_question_job_payload(payload, parallel_questions))
            parallel_jobs.append((job_path, out_json, log_path, {"question_ids": [str(q.get("question_id", "") or q.get("record_id", "") or "") for q in parallel_questions]}))

    write_json(
        paths["figure_dir"] / "figure_job_routing_summary.json",
        {
            "generated_at": now(),
            "parallel_job_count": len(parallel_jobs),
            "serial_job_count": len(serial_jobs),
            "rows": routing_rows,
        },
    )

    futures: list[concurrent.futures.Future] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.figure_concurrency)) as pool:
        for job_path, out_json, log_path, _job_meta in parallel_jobs:
            prepared_paths.append(out_json)
            cmd = [
                sys.executable,
                "tools/prepare_option_visual_source.py",
                "--source-json",
                str(job_path),
                "--out-json",
                str(out_json),
                "--model",
                args.model,
                "--require-vision-figure-model",
            ]
            if args.disable_heuristic_figure_fallback:
                cmd.append("--disable-heuristic-figure-fallback")
            futures.append(
                pool.submit(
                    run_cmd,
                    cmd,
                    cwd=paths["workspace"],
                    env=figure_env,
                    log_path=log_path,
                    timeout=None,
                )
            )
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result["returncode"] != 0:
                raise RuntimeError(f"figure_detection_failed: {result['log_path']}")

    for job_path, out_json, log_path, _job_meta in serial_jobs:
        prepared_paths.append(out_json)
        cmd = [
            sys.executable,
            "tools/prepare_option_visual_source.py",
            "--source-json",
            str(job_path),
            "--out-json",
            str(out_json),
            "--model",
            args.model,
            "--require-vision-figure-model",
        ]
        if args.disable_heuristic_figure_fallback:
            cmd.append("--disable-heuristic-figure-fallback")
        result = run_cmd(
            cmd,
            cwd=paths["workspace"],
            env=figure_env,
            log_path=log_path,
            timeout=None,
        )
        if result["returncode"] != 0:
            raise RuntimeError(f"figure_detection_failed: {result['log_path']}")

    if not prepared_paths:
        copied = read_json(paths["abs_source_json"])
        for question in copied.get("questions", []):
            if isinstance(question, dict):
                question["staged_visual_assets"] = []
                question["option_detection_review_flags"] = ["figure_detection_skipped_no_candidates"]
        write_json(paths["prepared_merged_json"], copied)
        return paths["prepared_merged_json"]

    cmd = [
        sys.executable,
        "tools/merge_candidate_prepared_sources.py",
        "--full-source-json",
        str(paths["abs_source_json"]),
        "--gate-dir",
        str(paths["gate_dir"]),
        "--out-json",
        str(paths["prepared_merged_json"]),
        "--prepared-shards",
    ] + [str(path) for path in prepared_paths]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "06_merge_prepared_sources.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"merge_prepared_sources_failed: {result['log_path']}")
    return paths["prepared_merged_json"]


def run_assetize(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str], visual_results: Path | None) -> Path:
    cmd = [
        sys.executable,
        "tools/assetize_question_images.py",
        "--source-json",
        str(paths["prepared_merged_json"]),
        "--out-dir",
        str(paths["asset_bundle_dir"]),
        "--include-debug-paths",
    ]
    if visual_results:
        cmd += ["--visual-results", str(visual_results)]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "07_assetize.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"assetize_failed: {result['log_path']}")
    return paths["asset_bundle_dir"] / "question_asset_manifest_v0.1.json"


def run_asset_visual_consolidation(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str], manifest_path: Path) -> Path:
    cmd = [
        sys.executable,
        "tools/consolidate_visual_assets.py",
        "--manifest",
        str(manifest_path),
        "--out-dir",
        str(paths["asset_consolidation_dir"]),
        "--model",
        str(args.model or ""),
        "--model-timeout",
        str(args.model_timeout),
    ]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "08_asset_visual_consolidation.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"asset_visual_consolidation_failed: {result['log_path']}")
    return paths["asset_consolidation_dir"] / "consolidated_manifest.json"


def run_asset_reconcile_refine(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str], manifest_path: Path) -> Path:
    cmd = [
        sys.executable,
        "tools/reconcile_and_refine_visual_assets.py",
        "--manifest",
        str(manifest_path),
        "--out-dir",
        str(paths["asset_reconcile_dir"]),
        "--model",
        str(args.model or ""),
        "--model-timeout",
        str(args.model_timeout),
    ]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "08_5_asset_reconcile_refine.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"asset_reconcile_refine_failed: {result['log_path']}")
    return paths["asset_reconcile_dir"] / "reconciled_refined_manifest.json"


def run_asset_package_audit(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str], manifest_path: Path) -> Path:
    cmd = [
        sys.executable,
        "tools/audit_question_asset_package.py",
        "--manifest",
        str(manifest_path),
        "--out-dir",
        str(paths["asset_audit_dir"]),
    ]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "09_asset_package_audit.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"asset_package_audit_failed: {result['log_path']}")
    return paths["asset_audit_dir"] / "asset_package_audit_summary.json"


def summarize(paths: dict[str, Path], visual_results: Path | None) -> dict[str, Any]:
    if visual_results is not None and not isinstance(visual_results, Path):
        visual_results = Path(visual_results).expanduser().resolve()
    gate_summary = read_json(paths["gate_dir"] / "model_image_need_gate_summary.json")
    candidate_summary = read_json(paths["candidate_json"].with_suffix(".summary.json"))
    prepared_summary = (
        read_json(paths["prepared_merged_json"].with_suffix(".summary.json"))
        if paths["prepared_merged_json"].with_suffix(".summary.json").exists()
        else {}
    )
    figure_job_routing_summary_path = paths["figure_dir"] / "figure_job_routing_summary.json"
    figure_job_routing_summary = (
        read_json(figure_job_routing_summary_path)
        if figure_job_routing_summary_path.exists()
        else {}
    )
    asset_manifest = (
        read_json(paths["asset_bundle_dir"] / "question_asset_manifest_v0.1.json")
        if (paths["asset_bundle_dir"] / "question_asset_manifest_v0.1.json").exists()
        else {}
    )
    asset_consolidation = (
        read_json(paths["asset_consolidation_dir"] / "asset_visual_consolidation_summary.json")
        if (paths["asset_consolidation_dir"] / "asset_visual_consolidation_summary.json").exists()
        else {}
    )
    asset_reconcile = (
        read_json(paths["asset_reconcile_dir"] / "reconcile_refine_summary.json")
        if (paths["asset_reconcile_dir"] / "reconcile_refine_summary.json").exists()
        else {}
    )
    asset_audit = (
        read_json(paths["asset_audit_dir"] / "asset_package_audit_summary.json")
        if (paths["asset_audit_dir"] / "asset_package_audit_summary.json").exists()
        else {}
    )
    visual_records = load_records(visual_results)
    format_normalize_summary_path = paths["transcription_format_dir"] / "format_normalize_only_summary.json"
    format_normalize_summary = read_json(format_normalize_summary_path) if format_normalize_summary_path.exists() else {}
    transcription_recovery_path = paths["transcription_dir"] / "transcription_recovery_summary.json"
    transcription_recovery_summary = read_json(transcription_recovery_path) if transcription_recovery_path.exists() else {}
    return {
        "generated_at": now(),
        "status": "complete",
        "source_json": str(paths["source_json"]),
        "visual_results": str(visual_results) if visual_results else "",
        "planner": {k: gate_summary.get(k) for k in ("question_count", "ok_count", "failed_count", "needs_figure_detection_count", "no_figure_count", "total_tokens")},
        "candidate": candidate_summary,
        "figure_prepared": prepared_summary,
        "figure_job_routing": {
            "summary": str(figure_job_routing_summary_path),
            "parallel_job_count": figure_job_routing_summary.get("parallel_job_count", 0),
            "serial_job_count": figure_job_routing_summary.get("serial_job_count", 0),
            "row_count": len(figure_job_routing_summary.get("rows", [])) if isinstance(figure_job_routing_summary.get("rows", []), list) else 0,
        },
        "transcription": {
            "question_count": len(visual_records),
            "ok_count": sum(1 for item in visual_records if item.get("status") == "ok"),
            "failed_count": sum(1 for item in visual_records if item.get("status") == "failed"),
            "recovery_summary": str(transcription_recovery_path),
            "recovery_final_failed_count": transcription_recovery_summary.get("final_failed_count", 0),
            "recovery_final_failed_question_ids": transcription_recovery_summary.get("final_failed_question_ids", []),
        },
        "format_normalize_backfill": format_normalize_summary,
        "asset_bundle": {
            "manifest": str(paths["asset_bundle_dir"] / "question_asset_manifest_v0.1.json"),
            "review_html": str(paths["asset_bundle_dir"] / "question_asset_review.html"),
            "question_count": asset_manifest.get("question_count", 0),
            "asset_count": asset_manifest.get("asset_count", 0),
        },
        "asset_visual_consolidation": {
            "summary": str(paths["asset_consolidation_dir"] / "asset_visual_consolidation_summary.json"),
            "manifest": str(paths["asset_consolidation_dir"] / "consolidated_manifest.json"),
            "html": str(paths["asset_consolidation_dir"] / "consolidation_review.html"),
            "action_count": asset_consolidation.get("action_count", 0),
            "action_counts": asset_consolidation.get("action_counts", {}),
        },
        "asset_reconcile_refine": {
            "summary": str(paths["asset_reconcile_dir"] / "reconcile_refine_summary.json"),
            "manifest": str(paths["asset_reconcile_dir"] / "reconciled_refined_manifest.json"),
            "html": str(paths["asset_reconcile_dir"] / "reconcile_refine_review.html"),
            "ownership_action_count": asset_reconcile.get("ownership_action_count", 0),
            "ownership_action_counts": asset_reconcile.get("ownership_action_counts", {}),
            "quality_action_count": asset_reconcile.get("quality_action_count", 0),
            "quality_action_counts": asset_reconcile.get("quality_action_counts", {}),
        },
        "asset_package_audit": {
            "summary": str(paths["asset_audit_dir"] / "asset_package_audit_summary.json"),
            "html": str(paths["asset_audit_dir"] / "asset_package_audit.html"),
            "status_counts": asset_audit.get("status_counts", {}),
            "issue_counts": asset_audit.get("issue_counts", {}),
            "warning_counts": asset_audit.get("warning_counts", {}),
        },
        "logs_dir": str(paths["logs"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified model-planned runtime for math question ingestion.")
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--transcription-results", default="")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--planner-concurrency", type=int, default=4)
    parser.add_argument("--transcription-concurrency", type=int, default=3)
    parser.add_argument("--figure-concurrency", type=int, default=4)
    parser.add_argument("--model-timeout", type=int, default=120)
    parser.add_argument("--model-retries", type=int, default=1)
    parser.add_argument("--transcription-recovery-attempts", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--skip-transcription-retry", action="store_true")
    parser.add_argument("--skip-figure-detection", action="store_true")
    parser.add_argument("--disable-heuristic-figure-fallback", action="store_true")
    parser.add_argument("--force-planner", action="store_true")
    args = parser.parse_args()

    workspace = Path(__file__).resolve().parent.parent
    source_json = Path(args.source_json).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "workspace": workspace,
        "source_json": source_json,
        "out_dir": out_dir,
        "state": out_dir / "state.json",
        "logs": out_dir / "logs",
        "abs_source_json": out_dir / "source.abs.json",
        "gate_dir": out_dir / "01_model_image_need_gate",
        "candidate_json": out_dir / "02_candidate_source" / "figure_candidates.json",
        "no_image_json": out_dir / "02_candidate_source" / "no_image.json",
        "candidate_shard_dir": out_dir / "02_candidate_source" / "shards",
        "transcription_dir": out_dir / "03_transcription",
        "figure_dir": out_dir / "04_figure_detection",
        "prepared_merged_json": out_dir / "05_prepared_merged" / "prepared_merged.json",
        "transcription_format_dir": out_dir / "03_5_format_normalize_backfill",
        "asset_bundle_dir": out_dir / "06_asset_bundle",
        "asset_consolidation_dir": out_dir / "06_5_asset_visual_consolidation",
        "asset_reconcile_dir": out_dir / "06_6_asset_reconcile_refine",
        "asset_audit_dir": out_dir / "07_asset_package_audit",
        "summary": out_dir / "runtime_summary.json",
    }
    for key in ("logs", "transcription_dir", "figure_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)

    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("missing_api_key")
    env = os.environ.copy()
    env["ARK_API_KEY"] = api_key
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    state_update(paths["state"], status="running", source_json=str(source_json), started_at=now())
    make_absolute_source(source_json, paths["abs_source_json"])
    state_update(paths["state"], abs_source_json=str(paths["abs_source_json"]))

    run_planner_gate(args, paths, env)
    state_update(paths["state"], planner="done")

    build_candidate_sources(args, paths, env)
    state_update(paths["state"], candidate_split="done")

    visual_results = Path(args.transcription_results).expanduser().resolve() if args.transcription_results else None
    visual_results = run_transcription_retries(args, paths, env) or visual_results
    state_update(paths["state"], transcription="done", visual_results=str(visual_results) if visual_results else "")

    visual_results, format_normalize_stage = run_format_normalize_backfill(args, paths, env, visual_results)
    state_update(
        paths["state"],
        format_normalize_backfill=str(format_normalize_stage.get("status", "") or ""),
        visual_results=str(visual_results) if visual_results else "",
    )

    if args.skip_figure_detection:
        shutil.copy2(paths["abs_source_json"], paths["prepared_merged_json"])
    else:
        run_figure_detection(args, paths, env)
    state_update(paths["state"], figure_detection="done")

    manifest_path = run_assetize(args, paths, env, visual_results)
    state_update(paths["state"], assetize="done")

    consolidated_manifest_path = run_asset_visual_consolidation(args, paths, env, manifest_path)
    state_update(paths["state"], asset_visual_consolidation="done")

    reconciled_manifest_path = run_asset_reconcile_refine(args, paths, env, consolidated_manifest_path)
    state_update(paths["state"], asset_reconcile_refine="done")

    run_asset_package_audit(args, paths, env, reconciled_manifest_path)
    state_update(paths["state"], asset_package_audit="done")

    summary = summarize(paths, visual_results)
    write_json(paths["summary"], summary)
    state_update(paths["state"], status="complete", summary=str(paths["summary"]))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
