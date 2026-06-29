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
    parser.add_argument("--option-anchor-mode", default="auto", help="auto | always | off")
    parser.add_argument("--max-pages", type=int, default=0, help="Optional page cap for quick testing.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    ensure_exists(pdf_path, "pdf")
    if args.profile not in VALID_PROFILES:
        raise SystemExit(f"invalid_profile: {args.profile}")
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
    env["OPTION_ANCHOR_MODE"] = str(args.option_anchor_mode or "auto")
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
    asset_stage = result.get("question_asset_stage", {}) or {}

    summary = {
        "entry": "run_teacher_handout_full_flow.py",
        "pdf": str(pdf_path),
        "profile": args.profile,
        "split_only": args.split_only,
        "prepare_only": args.prepare_only,
        "model": args.model if transcribe_enable else "",
        "split_out_name": split_out_name,
        "transcribe_out_name": transcribe_out_name if transcribe_enable else "",
        "split_out_dir": split_stage.get("out_dir", ""),
        "split_question_count": split_stage.get("questions", 0),
        "split_transcription_json": split_stage.get("transcription_json", ""),
        "prepared_source_json": option_prepare_stage.get("prepared_source_json", ""),
        "transcribe_out_dir": transcribe_stage.get("out_dir", ""),
        "transcribe_question_count": transcribe_stage.get("question_count", 0),
        "transcribe_ok_count": transcribe_stage.get("ok_count", 0),
        "transcribe_failed_count": transcribe_stage.get("failed_count", 0),
        "question_asset_out_dir": asset_stage.get("out_dir", ""),
        "question_asset_manifest": asset_stage.get("manifest", ""),
        "question_asset_review_html": asset_stage.get("html", ""),
        "question_asset_count": asset_stage.get("asset_count", 0),
        "summary_path": result.get("summary_path", ""),
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
