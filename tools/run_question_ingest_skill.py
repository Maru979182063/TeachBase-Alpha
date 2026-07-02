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

    shard_dirs: list[Path] = []
    futures: list[concurrent.futures.Future] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.transcription_concurrency)) as pool:
        for index, shard_ids in enumerate(split_list(retry_ids, args.transcription_concurrency), start=1):
            if not shard_ids:
                continue
            shard_manifest = paths["transcription_dir"] / f"retry_manifest_{index:02d}.json"
            build_manifest(paths["abs_source_json"], shard_manifest, shard_ids, f"retry_shard_{index:02d}")
            shard_out = paths["transcription_dir"] / f"retry_shard_{index:02d}"
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
                    log_path=paths["logs"] / f"03_transcription_retry_{index:02d}.log",
                    timeout=None,
                )
            )
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result["returncode"] != 0:
                raise RuntimeError(f"transcription_retry_failed: {result['log_path']}")

    merge_out = paths["transcription_dir"] / "merged"
    cmd = [sys.executable, "tools/merge_visual_transcription_results.py"]
    if existing_results_path:
        cmd += ["--run-dir", str(existing_results_path.parent)]
    for shard_out in shard_dirs:
        cmd += ["--run-dir", str(shard_out)]
    cmd += ["--out-dir", str(merge_out)]
    result = run_cmd(cmd, cwd=paths["workspace"], env=env, log_path=paths["logs"] / "04_merge_transcription.log")
    if result["returncode"] != 0:
        raise RuntimeError(f"merge_transcription_failed: {result['log_path']}")
    return merge_out / "visual_transcription_results.json"


def run_figure_detection(args: argparse.Namespace, paths: dict[str, Path], env: dict[str, str]) -> Path:
    candidate_summary = read_json(paths["candidate_json"].with_suffix(".summary.json"))
    shard_paths = [Path(item).resolve() for item in candidate_summary.get("shard_paths", [])]
    prepared_paths: list[Path] = []
    futures: list[concurrent.futures.Future] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.figure_concurrency)) as pool:
        for index, shard_path in enumerate(shard_paths, start=1):
            payload = read_json(shard_path)
            questions = payload.get("questions", []) if isinstance(payload, dict) else []
            if not questions:
                continue
            out_json = paths["figure_dir"] / f"prepared_shard_{index:02d}.json"
            prepared_paths.append(out_json)
            cmd = [
                sys.executable,
                "tools/prepare_option_visual_source.py",
                "--source-json",
                str(shard_path),
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
                    env=env,
                    log_path=paths["logs"] / f"05_figure_detection_{index:02d}.log",
                    timeout=None,
                )
            )
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
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
    return {
        "generated_at": now(),
        "status": "complete",
        "source_json": str(paths["source_json"]),
        "visual_results": str(visual_results) if visual_results else "",
        "planner": {k: gate_summary.get(k) for k in ("question_count", "ok_count", "failed_count", "needs_figure_detection_count", "no_figure_count", "total_tokens")},
        "candidate": candidate_summary,
        "figure_prepared": prepared_summary,
        "transcription": {
            "question_count": len(visual_records),
            "ok_count": sum(1 for item in visual_records if item.get("status") == "ok"),
            "failed_count": sum(1 for item in visual_records if item.get("status") == "failed"),
        },
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
