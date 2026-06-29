from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SPLIT_SCRIPT = WORKSPACE_ROOT / "tools" / "teacher_pdf_visual_question_split_v02.py"
TRANSCRIBE_SCRIPT = WORKSPACE_ROOT / "tools" / "teacher_handout_visual_transcribe_doubao.py"
ASSETIZE_SCRIPT = WORKSPACE_ROOT / "tools" / "assetize_question_images.py"
PREPARE_OPTION_SOURCE_SCRIPT = WORKSPACE_ROOT / "tools" / "prepare_option_visual_source.py"


def env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def resolve_workspace_path(raw: str) -> Path:
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return candidate
    return (WORKSPACE_ROOT / candidate).resolve()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def print_json(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))


def extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"json_not_found_in_output: {clean[:500]}")
    return json.loads(clean[start : end + 1])


def run_subprocess(command: list[str], env: dict[str, str]) -> dict:
    completed = subprocess.run(
        command,
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
            f"command_failed rc={completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return extract_json_block(completed.stdout)


def build_default_transcribe_out_dir(split_out_dir: Path | None, out_name: str) -> Path:
    if split_out_dir is not None:
        return split_out_dir / out_name
    return WORKSPACE_ROOT / "outputs" / "visual_transcription_v0.1" / out_name


def build_all_questions_manifest(source_json_path: Path, out_dir: Path) -> Path:
    payload = read_json(source_json_path)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    items = []
    source_stem = source_json_path.parent.name
    for question in questions:
        question_id = str(question.get("question_id", "")).strip()
        if not question_id:
            continue
        items.append(
            {
                "sample_id": f"{source_stem}_{question_id}",
                "source_transcription_json": str(source_json_path),
                "question_id": question_id,
                "tag": source_stem,
            }
        )
    manifest_path = out_dir / "all_questions_manifest.json"
    write_json(manifest_path, {"items": items})
    return manifest_path


def run_split_stage(env: dict[str, str]) -> dict:
    return run_subprocess([sys.executable, str(SPLIT_SCRIPT)], env=env)


def run_visual_transcribe_stage(
    env: dict[str, str],
    source_json_path: Path | None,
    split_out_dir: Path | None,
) -> dict:
    transcribe_out_name = (
        str(os.environ.get("VISUAL_TRANSCRIBE_OUT_NAME", "") or "").strip()
        or "visual_transcription_primary"
    )
    explicit_out_dir = str(os.environ.get("VISUAL_TRANSCRIBE_OUT_DIR", "") or "").strip()
    out_dir = (
        resolve_workspace_path(explicit_out_dir)
        if explicit_out_dir
        else build_default_transcribe_out_dir(split_out_dir, transcribe_out_name)
    )
    ensure_dir(out_dir)

    manifest_raw = str(os.environ.get("VISUAL_TRANSCRIBE_MANIFEST", "") or "").strip()
    source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
    question_ids_raw = str(os.environ.get("VISUAL_TRANSCRIBE_QUESTION_IDS", "") or "").strip()
    record_prefix = str(os.environ.get("VISUAL_TRANSCRIBE_RECORD_PREFIX", "") or "").strip()

    command = [
        sys.executable,
        str(TRANSCRIBE_SCRIPT),
        "--out-dir",
        str(out_dir),
        "--model",
        str(os.environ.get("VISUAL_TRANSCRIBE_MODEL", "") or "doubao-seed-2-0-pro-260215"),
        "--sleep-seconds",
        str(os.environ.get("VISUAL_TRANSCRIBE_SLEEP_SECONDS", "") or "0.3"),
    ]
    limit_raw = str(os.environ.get("VISUAL_TRANSCRIBE_LIMIT", "") or "").strip()
    if limit_raw:
        command.extend(["--limit", limit_raw])
    if env_flag("VISUAL_TRANSCRIBE_PREPARE_ONLY", default=False):
        command.append("--prepare-only")

    if manifest_raw:
        command.extend(["--manifest", str(resolve_workspace_path(manifest_raw))])
    else:
        effective_source_json = resolve_workspace_path(source_json_raw) if source_json_raw else source_json_path
        if effective_source_json is None:
            raise RuntimeError("missing_visual_transcribe_source_json")
        if question_ids_raw:
            command.extend(
                [
                    "--source-transcription-json",
                    str(effective_source_json),
                    "--question-ids",
                    question_ids_raw,
                ]
            )
            if record_prefix:
                command.extend(["--record-prefix", record_prefix])
        else:
            manifest_path = build_all_questions_manifest(effective_source_json, out_dir)
            command.extend(["--manifest", str(manifest_path)])

    result = run_subprocess(command, env=env)
    result["out_dir"] = str(out_dir)
    return result


def run_prepare_option_source_stage(
    env: dict[str, str],
    source_json_path: Path,
    split_out_dir: Path | None,
) -> dict:
    out_dir = split_out_dir or source_json_path.parent
    prepared_path = out_dir / "teacher_visual_question_transcription_optionprep_v1.1.json"
    command = [
        sys.executable,
        str(PREPARE_OPTION_SOURCE_SCRIPT),
        "--source-json",
        str(source_json_path),
        "--out-json",
        str(prepared_path),
        "--option-anchor-mode",
        str(os.environ.get("OPTION_ANCHOR_MODE", "") or "auto"),
        "--model",
        str(os.environ.get("OPTION_ANCHOR_MODEL", "") or "doubao-seed-2-0-lite-260428"),
    ]
    api_key = str(os.environ.get("ARK_API_KEY", "") or "").strip()
    if api_key:
        command.extend(["--api-key", api_key])
    result = run_subprocess(command, env=env)
    result["prepared_source_json"] = str(prepared_path)
    return result


def run_assetize_stage(
    env: dict[str, str],
    source_json_path: Path,
    visual_result_path: Path | None,
    split_out_dir: Path | None,
) -> dict:
    explicit_out_dir = str(os.environ.get("QUESTION_ASSET_OUT_DIR", "") or "").strip()
    out_name = str(os.environ.get("QUESTION_ASSET_OUT_NAME", "") or "").strip() or "question_asset_bundle_v0.1"
    out_dir = resolve_workspace_path(explicit_out_dir) if explicit_out_dir else (
        (split_out_dir or source_json_path.parent) / out_name
    )
    command = [
        sys.executable,
        str(ASSETIZE_SCRIPT),
        "--source-json",
        str(source_json_path),
        "--out-dir",
        str(out_dir),
    ]
    if visual_result_path is not None and visual_result_path.exists():
        command.extend(["--visual-results", str(visual_result_path)])
    return run_subprocess(command, env=env)


def main() -> None:
    transcribe_only = env_flag("VISUAL_TRANSCRIBE_ONLY", default=False)
    transcribe_enable = env_flag("VISUAL_TRANSCRIBE_ENABLE", default=False) or transcribe_only
    assetize_enable = env_flag("QUESTION_ASSETIZE_ENABLE", default=True)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    summary: dict[str, object] = {
        "runtime": "teacher_pdf_visual_runtime_vision_primary",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "transcribe_only": transcribe_only,
        "transcribe_enable": transcribe_enable,
        "assetize_enable": assetize_enable,
    }

    split_result: dict | None = None
    split_out_dir: Path | None = None
    source_json_path: Path | None = None
    prepared_source_json_path: Path | None = None

    if not transcribe_only:
        split_result = run_split_stage(env)
        split_out_dir = Path(split_result["out_dir"])
        source_json_path = Path(split_result["transcription_json"])
        summary["split_stage"] = split_result
        prepare_result = run_prepare_option_source_stage(env, source_json_path, split_out_dir)
        prepared_source_json_path = Path(prepare_result["prepared_source_json"])
        summary["option_prepare_stage"] = prepare_result
    else:
        source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
        if source_json_raw:
            source_json_path = resolve_workspace_path(source_json_raw)
            prepare_result = run_prepare_option_source_stage(env, source_json_path, source_json_path.parent)
            prepared_source_json_path = Path(prepare_result["prepared_source_json"])
            summary["option_prepare_stage"] = prepare_result

    if transcribe_enable:
        if source_json_path is None:
            source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
            if source_json_raw:
                source_json_path = resolve_workspace_path(source_json_raw)
        effective_transcribe_source = prepared_source_json_path or source_json_path
        if effective_transcribe_source is not None:
            env["VISUAL_TRANSCRIBE_SOURCE_JSON"] = str(effective_transcribe_source)
        transcribe_result = run_visual_transcribe_stage(
            env=env,
            source_json_path=effective_transcribe_source,
            split_out_dir=split_out_dir,
        )
        summary["visual_transcribe_stage"] = transcribe_result
        summary_path = Path(transcribe_result["out_dir"]) / "vision_primary_runtime_summary.json"
        visual_result_path = Path(transcribe_result["out_dir"]) / "visual_transcription_results.json"
    else:
        visual_result_path = None
        if split_out_dir is None:
            summary_path = WORKSPACE_ROOT / "outputs" / "visual_transcription_v0.1" / "vision_primary_runtime_summary.json"
        else:
            summary_path = split_out_dir / "vision_primary_runtime_summary.json"

    if assetize_enable:
        if prepared_source_json_path is None and source_json_path is None:
            source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
            if source_json_raw:
                source_json_path = resolve_workspace_path(source_json_raw)
        effective_asset_source = prepared_source_json_path or source_json_path
        if effective_asset_source is None:
            raise RuntimeError("missing_question_asset_source_json")
        assetize_result = run_assetize_stage(
            env=env,
            source_json_path=effective_asset_source,
            visual_result_path=visual_result_path,
            split_out_dir=split_out_dir,
        )
        summary["question_asset_stage"] = assetize_result

    ensure_dir(summary_path.parent)
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    print_json(summary)


if __name__ == "__main__":
    main()
