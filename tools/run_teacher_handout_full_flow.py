from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_SCRIPT = WORKSPACE_ROOT / "tools" / "teacher_pdf_visual_runtime_vision_primary.py"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
VALID_PROFILES = {
    "auto",
    "english_reading_teacher",
    "senior_math_teacher",
    "junior_geometry_teacher",
}
VALID_ROUTES = {
    "auto",
    "split_text_layer_first",
    "split_text_then_visual_supplement",
    "vision_primary",
}


def safe_slug(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(text or "").strip())
    value = value.strip("._-")
    # Keep run folders short enough for Windows when nested raw response files are written.
    return (value[:40].rstrip("._-") or "teacher_handout")


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label}_not_found: {path}")


def build_default_names(pdf_path: Path) -> tuple[str, str]:
    stem = safe_slug(pdf_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (
        f"teacher_visual_question_split_{stem}_{timestamp}",
        f"visual_transcription_{stem}_{timestamp}",
    )


def run_runtime(env: dict[str, str]) -> dict:
    completed = subprocess.run(
        [sys.executable, str(RUNTIME_SCRIPT)],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"runtime_failed rc={completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    clean = str(completed.stdout or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"runtime_output_not_json:\n{clean}")
    return json.loads(clean[start : end + 1])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run teacher-handout visual split + visual transcription as one CLI flow."
    )
    parser.add_argument("--pdf", required=True, help="Absolute or relative path to the teacher PDF.")
    parser.add_argument("--profile", default="auto", help="auto | english_reading_teacher | senior_math_teacher | junior_geometry_teacher")
    parser.add_argument("--split-out-name", default="", help="Optional split output folder name.")
    parser.add_argument("--transcribe-out-name", default="", help="Optional transcription output folder name.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Visual model id for transcription.")
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""), help="ARK API key. Falls back to env ARK_API_KEY.")
    parser.add_argument("--sleep-seconds", type=float, default=0.3, help="Delay between model calls.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for quick regression.")
    parser.add_argument("--split-only", action="store_true", help="Only run visual split, skip transcription.")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare transcription packets but do not call the model.")
    parser.add_argument("--no-assetize", action="store_true", help="Skip portable question image asset bundle generation.")
    parser.add_argument("--legacy-assetize", action="store_true", help="Use the old direct assetize stage instead of the unified ingest asset runtime.")
    parser.add_argument("--option-anchor-mode", default="auto", help="auto | always | off")
    parser.add_argument("--enable-mineru-fallback", action="store_true", help="Allow MinerU as a fallback inside unified figure extraction.")
    parser.add_argument("--mineru-exe", default=os.environ.get("MINERU_EXE", "mineru"))
    parser.add_argument("--mineru-api-url", default=os.environ.get("MINERU_API_URL", ""))
    parser.add_argument("--mineru-timeout-seconds", type=int, default=int(os.environ.get("MINERU_TIMEOUT_SECONDS", "240") or 240))
    parser.add_argument("--ingest-python-exe", default=os.environ.get("QUESTION_INGEST_PYTHON_EXE", ""), help="Optional Python executable for unified ingest runtime.")
    parser.add_argument("--ingest-out-name", default="", help="Optional unified ingest output folder name.")
    parser.add_argument("--ingest-planner-concurrency", type=int, default=4)
    parser.add_argument("--ingest-figure-concurrency", type=int, default=4)
    parser.add_argument("--ingest-transcription-concurrency", type=int, default=3)
    parser.add_argument("--ingest-model-timeout", type=int, default=120)
    parser.add_argument("--ingest-model-retries", type=int, default=1)
    parser.add_argument("--skip-ingest-transcription-retry", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0, help="Optional page cap for quick testing.")
    parser.add_argument("--transcription-route", default="auto", help="auto | split_text_layer_first | split_text_then_visual_supplement | vision_primary")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    ensure_exists(pdf_path, "pdf")
    if args.profile not in VALID_PROFILES:
        raise SystemExit(f"invalid_profile: {args.profile}")
    if args.transcription_route not in VALID_ROUTES:
        raise SystemExit(f"invalid_transcription_route: {args.transcription_route}")
    ensure_exists(RUNTIME_SCRIPT, "runtime_script")

    split_out_name, transcribe_out_name = build_default_names(pdf_path)
    if args.split_out_name.strip():
        split_out_name = args.split_out_name.strip()
    if args.transcribe_out_name.strip():
        transcribe_out_name = args.transcribe_out_name.strip()

    transcribe_enable = not args.split_only
    prepare_only = bool(args.prepare_only)
    if transcribe_enable and not prepare_only and not args.api_key:
        raise SystemExit("missing_api_key: pass --api-key or set ARK_API_KEY, or use --prepare-only / --split-only")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PDF_TEACHER"] = str(pdf_path)
    env["SPLIT_OUT_NAME"] = split_out_name
    env["TEACHER_SPLIT_PROFILE"] = args.profile
    env["VISUAL_TRANSCRIBE_ONLY"] = "0"
    env["VISUAL_TRANSCRIBE_ENABLE"] = "1" if transcribe_enable else "0"
    env["VISUAL_TRANSCRIBE_PREPARE_ONLY"] = "1" if prepare_only else "0"
    env["VISUAL_TRANSCRIBE_OUT_NAME"] = transcribe_out_name
    env["VISUAL_TRANSCRIBE_MODEL"] = args.model
    env["VISUAL_TRANSCRIBE_SLEEP_SECONDS"] = str(args.sleep_seconds)
    env["QUESTION_ASSETIZE_ENABLE"] = "0" if args.no_assetize else "1"
    env["QUESTION_ASSET_UNIFIED_INGEST_ENABLE"] = "0" if args.legacy_assetize else "1"
    env["OPTION_ANCHOR_MODE"] = str(args.option_anchor_mode or "auto")
    env["VISUAL_TRANSCRIBE_ROUTE"] = str(args.transcription_route or "auto")
    env["QUESTION_INGEST_MINERU_FALLBACK_ENABLE"] = "1" if args.enable_mineru_fallback else "0"
    env["MINERU_EXE"] = str(args.mineru_exe or "mineru")
    env["MINERU_API_URL"] = str(args.mineru_api_url or "")
    env["MINERU_TIMEOUT_SECONDS"] = str(args.mineru_timeout_seconds)
    env["QUESTION_INGEST_PLANNER_CONCURRENCY"] = str(args.ingest_planner_concurrency)
    env["QUESTION_INGEST_FIGURE_CONCURRENCY"] = str(args.ingest_figure_concurrency)
    env["QUESTION_INGEST_TRANSCRIPTION_CONCURRENCY"] = str(args.ingest_transcription_concurrency)
    env["QUESTION_INGEST_MODEL_TIMEOUT"] = str(args.ingest_model_timeout)
    env["QUESTION_INGEST_MODEL_RETRIES"] = str(args.ingest_model_retries)
    env["QUESTION_INGEST_SKIP_TRANSCRIPTION_RETRY"] = "1" if args.skip_ingest_transcription_retry else "0"
    if args.ingest_python_exe.strip():
        env["QUESTION_INGEST_PYTHON_EXE"] = args.ingest_python_exe.strip()
    if args.ingest_out_name.strip():
        env["QUESTION_INGEST_OUT_NAME"] = args.ingest_out_name.strip()
    if args.limit > 0:
        env["VISUAL_TRANSCRIBE_LIMIT"] = str(args.limit)
    if args.max_pages > 0:
        env["TEACHER_SPLIT_MAX_PAGES"] = str(args.max_pages)
    if args.api_key:
        env["ARK_API_KEY"] = args.api_key

    result = run_runtime(env)
    split_stage = result.get("split_stage", {}) or {}
    option_prepare_stage = result.get("option_prepare_stage", {}) or {}
    transcribe_stage = result.get("visual_transcribe_stage", {}) or {}
    unified_ingest_stage = result.get("unified_ingest_stage", {}) or {}
    asset_stage = result.get("question_asset_stage", {}) or {}
    planner_stage = result.get("runtime_route_planner_stage", {}) or {}
    split_text_layer_stage = result.get("split_text_layer_stage", {}) or {}

    summary = {
        "entry": "run_teacher_handout_full_flow.py",
        "pdf": str(pdf_path),
        "profile": args.profile,
        "requested_transcription_route": args.transcription_route,
        "actual_transcription_route": result.get("transcription_route", ""),
        "split_only": args.split_only,
        "prepare_only": args.prepare_only,
        "legacy_assetize": args.legacy_assetize,
        "unified_ingest_enable": (not args.no_assetize and not args.legacy_assetize),
        "model": args.model if transcribe_enable else "",
        "split_out_name": split_out_name,
        "transcribe_out_name": transcribe_out_name if transcribe_enable else "",
        "split_out_dir": split_stage.get("out_dir", ""),
        "split_question_count": split_stage.get("questions", 0),
        "split_transcription_json": split_stage.get("transcription_json", ""),
        "prepared_source_json": option_prepare_stage.get("prepared_source_json", ""),
        "planner_status": planner_stage.get("status", ""),
        "planner_mode": planner_stage.get("planner_mode", ""),
        "planner_reason": planner_stage.get("reason", ""),
        "planner_confidence": planner_stage.get("confidence", 0),
        "transcribe_out_dir": transcribe_stage.get("out_dir", ""),
        "transcribe_question_count": transcribe_stage.get("question_count", 0),
        "transcribe_ok_count": transcribe_stage.get("ok_count", 0),
        "transcribe_failed_count": transcribe_stage.get("failed_count", 0),
        "pipeline_topology": transcribe_stage.get("pipeline_topology", {}),
        "unified_ingest_out_dir": unified_ingest_stage.get("out_dir", ""),
        "unified_ingest_summary": str(Path(str(unified_ingest_stage.get("out_dir", "") or "")) / "runtime_summary.json") if unified_ingest_stage else "",
        "unified_ingest_python_executable": unified_ingest_stage.get("python_executable", ""),
        "unified_ingest_planner": unified_ingest_stage.get("planner", {}),
        "unified_ingest_figure_prepared": unified_ingest_stage.get("figure_prepared", {}),
        "unified_ingest_asset_audit": unified_ingest_stage.get("asset_package_audit", {}),
        "split_text_layer_status": split_text_layer_stage.get("status", ""),
        "split_text_layer_source_json": split_text_layer_stage.get("source_json", ""),
        "question_asset_out_dir": asset_stage.get("out_dir", ""),
        "question_asset_manifest": asset_stage.get("manifest", ""),
        "question_asset_review_html": asset_stage.get("html", ""),
        "question_asset_count": asset_stage.get("asset_count", 0),
        "summary_path": result.get("summary_path", ""),
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
