from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parent.parent


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def count_questions(path: Path) -> int:
    data = read_json(path)
    questions = data.get("questions", [])
    return len(questions) if isinstance(questions, list) else 0


def count_files(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    return len(list(path.glob(pattern)))


def copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def package_instance(out_dir: Path) -> tuple[Path, Path]:
    package_dir = out_dir / "instance_package"
    zip_base = out_dir / "instance_package"
    zip_path = out_dir / "instance_package.zip"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    if zip_path.exists():
        zip_path.unlink()
    package_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "runtime_summary.json",
        "state.json",
        "source.abs.json",
        "visible_runtime_stdout.log",
        "visible_runtime_stderr.log",
        "logs",
        "01_model_image_need_gate",
        "02_candidate_source",
        "03_transcription",
        "05_prepared_merged",
        "06_asset_bundle",
        "07_asset_package_audit",
    ]:
        copy_if_exists(out_dir / name, package_dir / name)
    shutil.make_archive(str(zip_base), "zip", package_dir)
    return package_dir, zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible progress wrapper for question ingest runtime.")
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--transcription-results", default="")
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--planner-concurrency", type=int, default=4)
    parser.add_argument("--figure-concurrency", type=int, default=4)
    parser.add_argument("--transcription-concurrency", type=int, default=4)
    parser.add_argument("--model-timeout", type=int, default=120)
    parser.add_argument("--model-retries", type=int, default=1)
    parser.add_argument("--skip-transcription-retry", action="store_true")
    parser.add_argument("--disable-heuristic-figure-fallback", action="store_true")
    args = parser.parse_args()

    source_json = Path(args.source_json).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    transcription_results = Path(args.transcription_results).expanduser().resolve() if args.transcription_results else None
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.api_key.strip():
        print("Missing API key. Set ARK_API_KEY or pass --api-key.", flush=True)
        return 1

    stdout_log = out_dir / "visible_runtime_stdout.log"
    stderr_log = out_dir / "visible_runtime_stderr.log"

    cmd = [
        sys.executable,
        "tools/run_question_ingest_skill.py",
        "--source-json",
        str(source_json),
        "--out-dir",
        str(out_dir),
        "--model",
        args.model,
        "--planner-concurrency",
        str(args.planner_concurrency),
        "--figure-concurrency",
        str(args.figure_concurrency),
        "--transcription-concurrency",
        str(args.transcription_concurrency),
        "--model-timeout",
        str(args.model_timeout),
        "--model-retries",
        str(args.model_retries),
    ]
    if transcription_results:
        cmd += ["--transcription-results", str(transcription_results)]
    if args.skip_transcription_retry:
        cmd.append("--skip-transcription-retry")
    if args.disable_heuristic_figure_fallback:
        cmd.append("--disable-heuristic-figure-fallback")

    env = os.environ.copy()
    env["ARK_API_KEY"] = args.api_key.strip()
    env["PYTHONIOENCODING"] = "utf-8"

    print("Starting visual ingest runtime", flush=True)
    print(f"Source: {source_json}", flush=True)
    print(f"OutDir: {out_dir}", flush=True)
    print(f"Model: {args.model}", flush=True)
    print(
        f"Concurrency: planner={args.planner_concurrency}, figure={args.figure_concurrency}, transcription={args.transcription_concurrency}",
        flush=True,
    )
    print("", flush=True)

    with stdout_log.open("w", encoding="utf-8") as out, stderr_log.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=WORKSPACE, env=env, stdout=out, stderr=err, text=True)
        total = count_questions(source_json)
        last_line = ""
        while proc.poll() is None:
            state = read_json(out_dir / "state.json")
            gate_done = count_files(out_dir / "01_model_image_need_gate" / "gate", "*.gate.json")
            prepared_done = count_files(out_dir / "04_figure_detection", "prepared_shard_*.json")
            candidate_summary = read_json(out_dir / "02_candidate_source" / "candidate_source.summary.json")
            candidate_count = candidate_summary.get("candidate_count", "?")
            no_image_count = candidate_summary.get("no_image_count", "?")
            asset_status = "generated" if (out_dir / "06_asset_bundle" / "question_asset_manifest_v0.1.json").exists() else "not_generated"
            audit_status = "generated" if (out_dir / "07_asset_package_audit" / "asset_package_audit_summary.json").exists() else "not_generated"
            line = (
                f"{time.strftime('%H:%M:%S')} | status={state.get('status', '')} "
                f"planner={state.get('planner', '')} gate={gate_done}/{total} "
                f"candidate={candidate_count} no_image={no_image_count} "
                f"figure_shards={prepared_done} asset={asset_status} audit={audit_status}"
            )
            if line != last_line:
                print(line, flush=True)
                last_line = line
            time.sleep(5)
        rc = proc.wait()

    print("", flush=True)
    print(f"Runtime process finished. exit={rc}", flush=True)
    print(f"stdout: {stdout_log}", flush=True)
    print(f"stderr: {stderr_log}", flush=True)
    summary = out_dir / "runtime_summary.json"
    review_html = out_dir / "06_asset_bundle" / "question_asset_review.html"
    if summary.exists():
        print(f"summary: {summary}", flush=True)
    if review_html.exists():
        print(f"review html: {review_html}", flush=True)
    if rc == 0:
        package_dir, zip_path = package_instance(out_dir)
        print(f"instance package dir: {package_dir}", flush=True)
        print(f"instance package zip: {zip_path}", flush=True)
    else:
        print("Runtime failed. Last stderr lines:", flush=True)
        if stderr_log.exists():
            lines = stderr_log.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-80:]:
                print(line, flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
