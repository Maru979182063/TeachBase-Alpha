from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import vision_prompt_store


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SPLIT_SCRIPT = WORKSPACE_ROOT / "tools" / "teacher_pdf_visual_question_split_v02.py"
TRANSCRIBE_SCRIPT = WORKSPACE_ROOT / "tools" / "teacher_handout_visual_transcribe_doubao.py"
ASSETIZE_SCRIPT = WORKSPACE_ROOT / "tools" / "assetize_question_images.py"
PREPARE_OPTION_SOURCE_SCRIPT = WORKSPACE_ROOT / "tools" / "prepare_option_visual_source.py"
INGEST_RUNTIME_SCRIPT = WORKSPACE_ROOT / "tools" / "run_question_ingest_skill.py"
ROUTE_PLANNER_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ROUTE_AUTO = "auto"
ROUTE_TEXT_LAYER_FIRST = "split_text_layer_first"
ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT = "split_text_then_visual_supplement"
ROUTE_VISION_PRIMARY = "vision_primary"


def env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def env_flag_from(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw = str(env.get(name, "") or "").strip().lower()
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


def safe_slug(text: str) -> str:
    import re

    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "").strip())
    slug = slug.strip("._-")
    return slug or "item"


def extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"json_not_found_in_output: {clean[:500]}")
    return json.loads(clean[start : end + 1])


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def load_source_questions(source_json_path: Path) -> list[dict]:
    payload = read_json(source_json_path)
    if not isinstance(payload, dict):
        return []
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]


def load_source_payload(source_json_path: Path) -> dict:
    payload = read_json(source_json_path)
    return payload if isinstance(payload, dict) else {}


def count_by_key(questions: list[dict], key: str) -> dict[str, int]:
    counter: dict[str, int] = {}
    for question in questions:
        value = str(question.get(key, "") or "").strip() or "missing"
        counter[value] = counter.get(value, 0) + 1
    return counter


def flatten_visual_records(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def load_visual_records_by_question_id(results_path: Path) -> dict[str, dict]:
    payload = read_json(results_path)
    records = flatten_visual_records(payload)
    by_question_id: dict[str, dict] = {}
    for record in records:
        question_id = str(record.get("question_id", "") or "").strip()
        if not question_id:
            continue
        by_question_id[question_id] = record
    return by_question_id


def parse_csv_env(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def question_needs_visual_supplement(question: dict) -> tuple[bool, str]:
    source = str(question.get("transcription_source", "") or "").strip()
    confidence = str(question.get("transcription_confidence", "") or "").strip().lower()
    stem_text = str(question.get("stem_text", "") or "").strip()
    if not stem_text:
        return True, "stem_empty"
    if source and source != "pdf_text_layer":
        return True, "source_not_pdf_text_layer"
    if confidence and confidence != "high":
        return True, f"confidence_{confidence}"
    return False, ""


def pick_visual_supplement_question_ids(questions: list[dict]) -> tuple[list[str], dict[str, str]]:
    picked: list[str] = []
    reasons: dict[str, str] = {}
    for question in questions:
        question_id = str(question.get("question_id", "") or "").strip()
        if not question_id:
            continue
        needs, reason = question_needs_visual_supplement(question)
        if needs:
            picked.append(question_id)
            reasons[question_id] = reason
    return picked, reasons


def merge_text_field(base_text: object, visual_text: object, *, allow_visual_override: bool) -> tuple[str, str]:
    base = str(base_text or "")
    visual = str(visual_text or "")
    if not base.strip() and visual.strip():
        return visual, "fill_empty_from_visual"
    if allow_visual_override and visual.strip():
        return visual, "replace_low_confidence_with_visual"
    return base, "keep_base_text"


def merge_split_text_and_visual_results(
    *,
    source_json_path: Path,
    visual_results_path: Path,
    out_dir: Path,
) -> dict:
    source_payload = load_source_payload(source_json_path)
    source_questions = source_payload.get("questions", []) if isinstance(source_payload.get("questions", []), list) else []
    visual_by_question_id = load_visual_records_by_question_id(visual_results_path)
    merged_questions: list[dict] = []
    changed_questions = 0
    changed_fields = 0
    visual_ok_count = 0
    visual_failed_count = 0

    for question in source_questions:
        if not isinstance(question, dict):
            continue
        merged = dict(question)
        question_id = str(question.get("question_id", "") or "").strip()
        base_confidence = str(question.get("transcription_confidence", "") or "").strip().lower()
        visual_record = visual_by_question_id.get(question_id, {})
        visual_status = str(visual_record.get("status", "") or "").strip()
        if visual_status == "ok":
            visual_ok_count += 1
        elif visual_status:
            visual_failed_count += 1
        transcription = visual_record.get("transcription", {}) if isinstance(visual_record.get("transcription"), dict) else {}

        route_merge: dict[str, object] = {
            "route": ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT,
            "visual_record_status": visual_status or "not_selected",
            "field_decisions": {},
        }
        question_changed = False
        allow_visual_override = base_confidence != "high"
        for split_key, visual_key in (
            ("stem_text", "stem_text_md"),
            ("answer_text", "answer_text_md"),
            ("analysis_text", "analysis_text_md"),
        ):
            merged_text, decision = merge_text_field(
                question.get(split_key, ""),
                transcription.get(visual_key, ""),
                allow_visual_override=allow_visual_override,
            )
            if merged_text != str(question.get(split_key, "") or ""):
                merged[split_key] = merged_text
                question_changed = True
                changed_fields += 1
            route_merge["field_decisions"][split_key] = decision

        if "stem_requires_image" in transcription:
            merged["stem_requires_image"] = bool(transcription.get("stem_requires_image", False))
        if "analysis_requires_image" in transcription:
            merged["analysis_requires_image"] = bool(transcription.get("analysis_requires_image", False))

        merged["route_transcription_source"] = ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT
        merged["visual_supplement_applied"] = bool(question_changed)
        merged["visual_supplement_merge"] = route_merge
        if question_changed:
            changed_questions += 1
        merged_questions.append(merged)

    merged_payload = dict(source_payload)
    merged_payload["questions"] = merged_questions
    merged_payload["route_stage_summary"] = {
        "route": ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT,
        "source_json": str(source_json_path),
        "visual_results_json": str(visual_results_path),
        "question_count": len(merged_questions),
        "visual_ok_count": visual_ok_count,
        "visual_failed_count": visual_failed_count,
        "changed_question_count": changed_questions,
        "changed_field_count": changed_fields,
    }
    merged_json_path = out_dir / "teacher_visual_question_transcription_textplusvision_v1.json"
    write_json(merged_json_path, merged_payload)
    return {
        "merged_source_json": str(merged_json_path),
        "question_count": len(merged_questions),
        "visual_ok_count": visual_ok_count,
        "visual_failed_count": visual_failed_count,
        "changed_question_count": changed_questions,
        "changed_field_count": changed_fields,
    }


def resolve_question_image_path(question: dict, base_dir: Path) -> Path | None:
    for key in ("question_image", "stem_image", "analysis_image"):
        raw = str(question.get(key, "") or "").strip()
        if not raw:
            continue
        path = Path(raw)
        resolved = path if path.is_absolute() else (base_dir / path).resolve()
        if resolved.exists():
            return resolved
    return None


def pick_route_planner_samples(questions: list[dict], base_dir: Path, limit: int = 3) -> list[dict]:
    candidates: list[dict] = []
    for question in questions:
        image_path = resolve_question_image_path(question, base_dir)
        if image_path is None:
            continue
        candidates.append(
            {
                "question_id": str(question.get("question_id", "") or ""),
                "image_path": image_path,
                "transcription_source": str(question.get("transcription_source", "") or ""),
                "transcription_confidence": str(question.get("transcription_confidence", "") or ""),
            }
        )
    if len(candidates) <= limit:
        return candidates
    middle = len(candidates) // 2
    picks = [candidates[0], candidates[middle], candidates[-1]]
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in picks:
        qid = str(item.get("question_id", "") or "")
        if qid and qid not in seen:
            deduped.append(item)
            seen.add(qid)
    return deduped


def build_route_planner_messages(
    *,
    requested_profile: str,
    source_counter: dict[str, int],
    confidence_counter: dict[str, int],
    samples: list[dict],
) -> list[dict]:
    bundle = vision_prompt_store.get_runtime_route_planner_prompt_bundle()
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "REQUESTED_PROFILE": requested_profile,
            "QUESTION_COUNT": str(sum(source_counter.values())),
            "SOURCE_COUNTER_JSON": json.dumps(source_counter, ensure_ascii=False),
            "CONFIDENCE_COUNTER_JSON": json.dumps(confidence_counter, ensure_ascii=False),
            "SAMPLE_QUESTION_IDS_JSON": json.dumps([item.get("question_id", "") for item in samples], ensure_ascii=False),
        },
    )
    content: list[dict] = []
    if bundle.get("system_prompt"):
        content.append({"type": "text", "text": bundle["system_prompt"]})
    content.append({"type": "text", "text": prompt})
    for item in samples:
        question_id = str(item.get("question_id", "") or "")
        content.append(
            {
                "type": "text",
                "text": (
                    f"sample_question_id={question_id}; "
                    f"transcription_source={item.get('transcription_source', '')}; "
                    f"transcription_confidence={item.get('transcription_confidence', '')}"
                ),
            }
        )
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(item["image_path"])}})
    return [{"role": "user", "content": content}]


def call_route_planner_model(
    *,
    requested_profile: str,
    source_counter: dict[str, int],
    confidence_counter: dict[str, int],
    samples: list[dict],
    api_key: str,
    model: str,
    timeout_seconds: int,
) -> tuple[dict, dict]:
    body = {
        "model": model,
        "messages": build_route_planner_messages(
            requested_profile=requested_profile,
            source_counter=source_counter,
            confidence_counter=confidence_counter,
            samples=samples,
        ),
        "temperature": 0,
    }
    request = urllib.request.Request(
        ROUTE_PLANNER_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    content = payload["choices"][0]["message"]["content"]
    parsed = extract_json_block(content)
    meta = {
        "latency_seconds": round(time.time() - started, 3),
        "usage": payload.get("usage", {}) if isinstance(payload, dict) else {},
        "raw_response": payload,
    }
    return parsed, meta


def normalize_route(value: object) -> str:
    route = str(value or "").strip()
    if route == ROUTE_TEXT_LAYER_FIRST:
        return ROUTE_TEXT_LAYER_FIRST
    if route == ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT:
        return ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT
    if route == ROUTE_VISION_PRIMARY:
        return ROUTE_VISION_PRIMARY
    return ROUTE_VISION_PRIMARY


def build_local_route_plan(
    *,
    requested_profile: str,
    question_count: int,
    source_counter: dict[str, int],
    confidence_counter: dict[str, int],
    reason_prefix: str,
) -> dict:
    pdf_count = int(source_counter.get("pdf_text_layer", 0) or 0)
    high_medium = int(confidence_counter.get("high", 0) or 0) + int(confidence_counter.get("medium", 0) or 0)
    low_count = int(confidence_counter.get("low", 0) or 0)
    pdf_share = (pdf_count / question_count) if question_count > 0 else 0.0
    quality_share = (high_medium / question_count) if question_count > 0 else 0.0
    if requested_profile == "english_reading_teacher" and pdf_share >= 0.75 and low_count > 0:
        return {
            "route": ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT,
            "subject_guess": "english",
            "ocr_policy": "fallback_only",
            "visual_policy": "run_full_visual",
            "confidence": 0.78,
            "reason": f"{reason_prefix}: english profile with reliable pdf_text_layer but remaining low-confidence questions",
        }
    if requested_profile == "english_reading_teacher" and pdf_share >= 0.75 and quality_share >= 0.75:
        return {
            "route": ROUTE_TEXT_LAYER_FIRST,
            "subject_guess": "english",
            "ocr_policy": "fallback_only",
            "visual_policy": "skip_full_visual",
            "confidence": 0.72,
            "reason": f"{reason_prefix}: english profile with strong pdf_text_layer coverage",
        }
    return {
        "route": ROUTE_VISION_PRIMARY,
        "subject_guess": "math" if requested_profile != "english_reading_teacher" else "mixed",
        "ocr_policy": "use_if_text_layer_missing",
        "visual_policy": "run_full_visual",
        "confidence": 0.51,
        "reason": f"{reason_prefix}: keep conservative visual-primary route",
    }


def run_runtime_route_planner(
    *,
    env: dict[str, str],
    source_json_path: Path,
    split_out_dir: Path | None,
) -> dict:
    requested_route = str(os.environ.get("VISUAL_TRANSCRIBE_ROUTE", "") or "").strip() or ROUTE_AUTO
    requested_profile = str(os.environ.get("TEACHER_SPLIT_PROFILE", "") or "auto").strip() or "auto"
    questions = load_source_questions(source_json_path)
    source_counter = count_by_key(questions, "transcription_source")
    confidence_counter = count_by_key(questions, "transcription_confidence")
    question_count = len(questions)
    samples = pick_route_planner_samples(questions, source_json_path.parent, limit=3)
    summary_path = (split_out_dir or source_json_path.parent) / "runtime_route_planner_summary.json"
    raw_path = (split_out_dir or source_json_path.parent) / "runtime_route_planner_response.json"

    base_summary = {
        "requested_route": requested_route,
        "requested_profile": requested_profile,
        "question_count": question_count,
        "source_counter": source_counter,
        "confidence_counter": confidence_counter,
        "sample_question_ids": [str(item.get("question_id", "") or "") for item in samples],
        "sample_image_paths": [str(item.get("image_path", "")) for item in samples],
    }

    if requested_route in {ROUTE_TEXT_LAYER_FIRST, ROUTE_VISION_PRIMARY}:
        summary = dict(base_summary)
        summary.update(
            {
                "status": "override",
                "planner_mode": "manual_override",
                "route": requested_route,
                "subject_guess": "override",
                "ocr_policy": "fallback_only" if requested_route == ROUTE_TEXT_LAYER_FIRST else "use_if_text_layer_missing",
                "visual_policy": "skip_full_visual" if requested_route == ROUTE_TEXT_LAYER_FIRST else "run_full_visual",
                "confidence": 1.0,
                "reason": "manual_route_override",
            }
        )
        write_json(summary_path, summary)
        return summary

    planner_enable = env_flag("RUNTIME_ROUTE_PLANNER_ENABLE", default=True)
    api_key = str(os.environ.get("ARK_API_KEY", "") or "").strip()
    planner_model = str(os.environ.get("RUNTIME_ROUTE_PLANNER_MODEL", "") or "doubao-seed-2-0-lite-260428").strip()

    if planner_enable and api_key and samples:
        try:
            parsed, meta = call_route_planner_model(
                requested_profile=requested_profile,
                source_counter=source_counter,
                confidence_counter=confidence_counter,
                samples=samples,
                api_key=api_key,
                model=planner_model,
                timeout_seconds=int(str(os.environ.get("RUNTIME_ROUTE_PLANNER_TIMEOUT", "") or "120")),
            )
            summary = dict(base_summary)
            summary.update(
                {
                    "status": "ok",
                    "planner_mode": "model",
                    "route": normalize_route(parsed.get("route")),
                    "subject_guess": str(parsed.get("subject_guess", "") or ""),
                    "ocr_policy": str(parsed.get("ocr_policy", "") or ""),
                    "visual_policy": str(parsed.get("visual_policy", "") or ""),
                    "confidence": float(parsed.get("confidence", 0) or 0),
                    "reason": str(parsed.get("reason", "") or ""),
                    "planner_model": planner_model,
                    "latency_seconds": meta["latency_seconds"],
                    "usage": meta["usage"],
                }
            )
            write_json(summary_path, summary)
            write_json(raw_path, meta["raw_response"])
            return summary
        except Exception as exc:
            summary = dict(base_summary)
            summary.update(
                build_local_route_plan(
                    requested_profile=requested_profile,
                    question_count=question_count,
                    source_counter=source_counter,
                    confidence_counter=confidence_counter,
                    reason_prefix=f"planner_fallback_after_error:{exc}",
                )
            )
            summary["status"] = "fallback_local"
            summary["planner_mode"] = "local_after_model_error"
            summary["planner_model"] = planner_model
            write_json(summary_path, summary)
            return summary

    summary = dict(base_summary)
    summary.update(
        build_local_route_plan(
            requested_profile=requested_profile,
            question_count=question_count,
            source_counter=source_counter,
            confidence_counter=confidence_counter,
            reason_prefix="planner_local_only",
        )
    )
    summary["status"] = "fallback_local"
    summary["planner_mode"] = "local_only"
    summary["planner_model"] = planner_model
    write_json(summary_path, summary)
    return summary


def run_subprocess(command: list[str], env: dict[str, str], timeout_seconds: float | None = None) -> dict:
    try:
        completed = subprocess.run(
            command,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command_timeout_after_{timeout_seconds}s: {' '.join(command)}") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"command_failed rc={completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return extract_json_block(completed.stdout)


def python_has_module(executable: str, module: str) -> bool:
    try:
        completed = subprocess.run(
            [executable, "-c", f"import {module}"],
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
    except Exception:
        return False
    return completed.returncode == 0


def select_unified_ingest_python(env: dict[str, str]) -> str:
    explicit = str(env.get("QUESTION_INGEST_PYTHON_EXE", "") or "").strip()
    if explicit and python_has_module(explicit, "cv2"):
        return explicit
    if python_has_module(sys.executable, "cv2"):
        return sys.executable
    candidate = shutil.which("python")
    if candidate and python_has_module(candidate, "cv2"):
        return candidate
    return sys.executable


def build_default_transcribe_out_dir(split_out_dir: Path | None, out_name: str) -> Path:
    if split_out_dir is not None:
        return split_out_dir / out_name
    return WORKSPACE_ROOT / "outputs" / "visual_transcription_v0.1" / out_name


def resolve_runtime_run_id() -> str:
    explicit = str(os.environ.get("VISUAL_RUNTIME_RUN_ID", "") or "").strip()
    if explicit:
        return explicit
    source_hint = (
        str(os.environ.get("VISUAL_TRANSCRIBE_OUT_NAME", "") or "").strip()
        or str(os.environ.get("SPLIT_OUT_NAME", "") or "").strip()
        or Path(str(os.environ.get("PDF_TEACHER", "") or "visual_runtime")).stem
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"visualrun_{stamp}_{safe_slug(source_hint)}"


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
        str(env.get("VISUAL_TRANSCRIBE_OUT_NAME", "") or "").strip()
        or "visual_transcription_primary"
    )
    explicit_out_dir = str(env.get("VISUAL_TRANSCRIBE_OUT_DIR", "") or "").strip()
    out_dir = (
        resolve_workspace_path(explicit_out_dir)
        if explicit_out_dir
        else build_default_transcribe_out_dir(split_out_dir, transcribe_out_name)
    )
    ensure_dir(out_dir)

    manifest_raw = str(env.get("VISUAL_TRANSCRIBE_MANIFEST", "") or "").strip()
    source_json_raw = str(env.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
    question_ids_raw = str(env.get("VISUAL_TRANSCRIBE_QUESTION_IDS", "") or "").strip()
    record_prefix = str(env.get("VISUAL_TRANSCRIBE_RECORD_PREFIX", "") or "").strip()

    command = [
        sys.executable,
        str(TRANSCRIBE_SCRIPT),
        "--out-dir",
        str(out_dir),
        "--model",
        str(env.get("VISUAL_TRANSCRIBE_MODEL", "") or "doubao-seed-2-0-pro-260215"),
        "--sleep-seconds",
        str(env.get("VISUAL_TRANSCRIBE_SLEEP_SECONDS", "") or "0.3"),
    ]
    limit_raw = str(env.get("VISUAL_TRANSCRIBE_LIMIT", "") or "").strip()
    if limit_raw:
        command.extend(["--limit", limit_raw])
    if env_flag_from(env, "VISUAL_TRANSCRIBE_PREPARE_ONLY", default=False):
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
    timeout_raw = str(os.environ.get("OPTION_PREPARE_TIMEOUT_SECONDS", "") or "").strip()
    timeout_seconds = float(timeout_raw) if timeout_raw else 240.0
    result = run_subprocess(command, env=env, timeout_seconds=timeout_seconds)
    result["prepared_source_json"] = str(prepared_path)
    return result


def try_run_prepare_option_source_stage(
    env: dict[str, str],
    source_json_path: Path,
    split_out_dir: Path | None,
) -> tuple[dict | None, Path | None]:
    try:
        result = run_prepare_option_source_stage(env, source_json_path, split_out_dir)
    except Exception as exc:
        return (
            {
                "status": "failed_fallback_to_source_json",
                "error": str(exc),
                "source_json": str(source_json_path),
            },
            None,
        )
    prepared_source_json = Path(str(result.get("prepared_source_json", "") or "")).resolve()
    return result, prepared_source_json


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


def run_unified_ingest_stage(
    env: dict[str, str],
    source_json_path: Path,
    visual_result_path: Path | None,
    split_out_dir: Path | None,
) -> dict:
    explicit_out_dir = str(os.environ.get("QUESTION_INGEST_OUT_DIR", "") or "").strip()
    out_name = str(os.environ.get("QUESTION_INGEST_OUT_NAME", "") or "").strip() or "question_ingest_runtime_v0.1"
    out_dir = resolve_workspace_path(explicit_out_dir) if explicit_out_dir else (
        (split_out_dir or source_json_path.parent) / out_name
    )
    python_exe = select_unified_ingest_python(env)
    command = [
        python_exe,
        str(INGEST_RUNTIME_SCRIPT),
        "--source-json",
        str(source_json_path),
        "--out-dir",
        str(out_dir),
        "--model",
        str(env.get("QUESTION_INGEST_MODEL", "") or env.get("VISUAL_TRANSCRIBE_MODEL", "") or "doubao-seed-2-0-lite-260428"),
        "--planner-concurrency",
        str(env.get("QUESTION_INGEST_PLANNER_CONCURRENCY", "") or "4"),
        "--figure-concurrency",
        str(env.get("QUESTION_INGEST_FIGURE_CONCURRENCY", "") or "4"),
        "--transcription-concurrency",
        str(env.get("QUESTION_INGEST_TRANSCRIPTION_CONCURRENCY", "") or "3"),
        "--model-timeout",
        str(env.get("QUESTION_INGEST_MODEL_TIMEOUT", "") or "120"),
        "--model-retries",
        str(env.get("QUESTION_INGEST_MODEL_RETRIES", "") or "1"),
    ]
    if visual_result_path is not None and visual_result_path.exists():
        command.extend(["--transcription-results", str(visual_result_path)])
    if env_flag_from(env, "QUESTION_INGEST_SKIP_TRANSCRIPTION_RETRY", default=False):
        command.append("--skip-transcription-retry")
    if env_flag_from(env, "QUESTION_INGEST_DISABLE_HEURISTIC_FIGURE_FALLBACK", default=False):
        command.append("--disable-heuristic-figure-fallback")
    if env_flag_from(env, "QUESTION_INGEST_MINERU_FALLBACK_ENABLE", default=False):
        command.append("--enable-mineru-fallback")
        mineru_exe = str(env.get("MINERU_EXE", "") or "mineru")
        mineru_api_url = str(env.get("MINERU_API_URL", "") or "")
        mineru_timeout = str(env.get("MINERU_TIMEOUT_SECONDS", "") or "240")
        command.extend(
            [
                "--mineru-exe",
                mineru_exe,
                "--mineru-api-url",
                mineru_api_url,
                "--mineru-timeout-seconds",
                mineru_timeout,
            ]
        )

    result = run_subprocess(command, env=env, timeout_seconds=None)
    result["out_dir"] = str(out_dir)
    result["python_executable"] = python_exe
    result["source_json"] = str(source_json_path)
    result["visual_results"] = str(visual_result_path) if visual_result_path is not None else ""
    return result


def build_question_asset_stage_from_unified(unified_result: dict) -> dict:
    asset_bundle = unified_result.get("asset_bundle", {}) if isinstance(unified_result.get("asset_bundle"), dict) else {}
    return {
        "status": "from_unified_ingest",
        "out_dir": str(Path(str(unified_result.get("out_dir", "") or "")) / "06_asset_bundle"),
        "manifest": str(asset_bundle.get("manifest", "") or ""),
        "html": str(asset_bundle.get("review_html", "") or ""),
        "question_count": asset_bundle.get("question_count", 0),
        "asset_count": asset_bundle.get("asset_count", 0),
        "unified_ingest_summary": str(Path(str(unified_result.get("out_dir", "") or "")) / "runtime_summary.json"),
        "python_executable": str(unified_result.get("python_executable", "") or ""),
    }


def main() -> None:
    transcribe_only = env_flag("VISUAL_TRANSCRIBE_ONLY", default=False)
    transcribe_enable = env_flag("VISUAL_TRANSCRIBE_ENABLE", default=False) or transcribe_only
    assetize_enable = env_flag("QUESTION_ASSETIZE_ENABLE", default=True)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    runtime_run_id = resolve_runtime_run_id()
    env["VISUAL_RUNTIME_RUN_ID"] = runtime_run_id
    summary: dict[str, object] = {
        "runtime": "teacher_pdf_visual_runtime_vision_primary",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "runtime_run_id": runtime_run_id,
        "transcribe_only": transcribe_only,
        "transcribe_enable": transcribe_enable,
        "assetize_enable": assetize_enable,
    }

    split_result: dict | None = None
    split_out_dir: Path | None = None
    source_json_path: Path | None = None
    prepared_source_json_path: Path | None = None
    merged_source_json_path: Path | None = None
    route_planner_result: dict | None = None

    if not transcribe_only:
        split_result = run_split_stage(env)
        split_out_dir = Path(split_result["out_dir"])
        source_json_path = Path(split_result["transcription_json"])
        summary["split_stage"] = split_result
    else:
        source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
        if source_json_raw:
            source_json_path = resolve_workspace_path(source_json_raw)
    if transcribe_enable and not transcribe_only and source_json_path is not None:
        route_planner_result = run_runtime_route_planner(
            env=env,
            source_json_path=source_json_path,
            split_out_dir=split_out_dir,
        )
        summary["runtime_route_planner_stage"] = route_planner_result

    if transcribe_enable:
        if source_json_path is None:
            source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
            if source_json_raw:
                source_json_path = resolve_workspace_path(source_json_raw)
        chosen_route = ROUTE_VISION_PRIMARY if transcribe_only else normalize_route((route_planner_result or {}).get("route"))
        summary["transcription_route"] = chosen_route
        if chosen_route == ROUTE_TEXT_LAYER_FIRST:
            summary["option_prepare_stage"] = {
                "status": "skipped_by_route",
                "reason": "split_text_layer_first",
                "source_json": str(source_json_path) if source_json_path is not None else "",
            }
            summary["split_text_layer_stage"] = {
                "status": "used_split_transcription_json",
                "source_json": str(source_json_path) if source_json_path is not None else "",
                "question_count": len(load_source_questions(source_json_path)) if source_json_path is not None else 0,
                "reason": "planner_prefers_pdf_text_layer_or_structured_split_output",
            }
            summary["visual_transcribe_stage"] = {
                "status": "skipped_by_route",
                "route": ROUTE_TEXT_LAYER_FIRST,
                "reason": "planner_prefers_text_layer",
                "question_count": 0,
                "ok_count": 0,
                "failed_count": 0,
                "out_dir": "",
            }
            visual_result_path = None
            summary_path = (split_out_dir or source_json_path.parent) / "vision_primary_runtime_summary.json"
        elif chosen_route == ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT:
            if source_json_path is None:
                raise RuntimeError("missing_visual_supplement_source_json")
            source_questions = load_source_questions(source_json_path)
            question_ids, supplement_reasons = pick_visual_supplement_question_ids(source_questions)
            summary["split_text_layer_stage"] = {
                "status": "used_split_transcription_json",
                "source_json": str(source_json_path),
                "question_count": len(source_questions),
                "reason": "pdf_text_layer_as_base_before_visual_supplement",
            }
            summary["option_prepare_stage"] = {
                "status": "skipped_by_route",
                "reason": "split_text_then_visual_supplement",
                "source_json": str(source_json_path),
            }
            summary["visual_supplement_selection_stage"] = {
                "status": "ok",
                "selected_question_count": len(question_ids),
                "selected_question_ids": question_ids,
                "selection_reasons": supplement_reasons,
            }
            if question_ids:
                env["VISUAL_TRANSCRIBE_SOURCE_JSON"] = str(source_json_path)
                env["VISUAL_TRANSCRIBE_QUESTION_IDS"] = ",".join(question_ids)
                transcribe_result = run_visual_transcribe_stage(
                    env=env,
                    source_json_path=source_json_path,
                    split_out_dir=split_out_dir,
                )
                summary["visual_transcribe_stage"] = transcribe_result
                visual_result_path = Path(transcribe_result["out_dir"]) / "visual_transcription_results.json"
                merge_result = merge_split_text_and_visual_results(
                    source_json_path=source_json_path,
                    visual_results_path=visual_result_path,
                    out_dir=Path(transcribe_result["out_dir"]),
                )
                merged_source_json_path = Path(str(merge_result["merged_source_json"]))
                summary["textplusvision_merge_stage"] = merge_result
                summary_path = Path(transcribe_result["out_dir"]) / "vision_primary_runtime_summary.json"
            else:
                summary["visual_transcribe_stage"] = {
                    "status": "skipped_no_low_confidence_questions",
                    "route": ROUTE_TEXT_THEN_VISUAL_SUPPLEMENT,
                    "reason": "all_questions_already_high_confidence_pdf_text_layer",
                    "question_count": 0,
                    "ok_count": 0,
                    "failed_count": 0,
                    "out_dir": "",
                }
                summary["textplusvision_merge_stage"] = {
                    "status": "skipped_no_selected_questions",
                    "merged_source_json": str(source_json_path),
                    "question_count": len(source_questions),
                    "visual_ok_count": 0,
                    "visual_failed_count": 0,
                    "changed_question_count": 0,
                    "changed_field_count": 0,
                }
                merged_source_json_path = source_json_path
                visual_result_path = None
                summary_path = (split_out_dir or source_json_path.parent) / "vision_primary_runtime_summary.json"
        else:
            if source_json_path is None:
                raise RuntimeError("missing_visual_transcribe_source_json")
            prepare_result, prepared_source_json_path = try_run_prepare_option_source_stage(
                env,
                source_json_path,
                split_out_dir or source_json_path.parent,
            )
            summary["option_prepare_stage"] = prepare_result
            effective_transcribe_source = prepared_source_json_path or source_json_path
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
        if prepared_source_json_path is None and merged_source_json_path is None and source_json_path is None:
            source_json_raw = str(os.environ.get("VISUAL_TRANSCRIBE_SOURCE_JSON", "") or "").strip()
            if source_json_raw:
                source_json_path = resolve_workspace_path(source_json_raw)
        effective_asset_source = prepared_source_json_path or merged_source_json_path or source_json_path
        if effective_asset_source is None:
            raise RuntimeError("missing_question_asset_source_json")
        unified_ingest_enable = env_flag("QUESTION_ASSET_UNIFIED_INGEST_ENABLE", default=True)
        prepare_only = env_flag("VISUAL_TRANSCRIBE_PREPARE_ONLY", default=False)
        if unified_ingest_enable and not prepare_only:
            unified_result = run_unified_ingest_stage(
                env=env,
                source_json_path=effective_asset_source,
                visual_result_path=None if merged_source_json_path is not None else visual_result_path,
                split_out_dir=split_out_dir,
            )
            summary["unified_ingest_stage"] = unified_result
            summary["question_asset_stage"] = build_question_asset_stage_from_unified(unified_result)
        else:
            assetize_result = run_assetize_stage(
                env=env,
                source_json_path=effective_asset_source,
                visual_result_path=None if merged_source_json_path is not None else visual_result_path,
                split_out_dir=split_out_dir,
            )
            summary["question_asset_stage"] = assetize_result

    ensure_dir(summary_path.parent)
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    print_json(summary)


if __name__ == "__main__":
    main()
