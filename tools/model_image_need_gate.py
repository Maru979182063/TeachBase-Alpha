from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import vision_prompt_store


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = clean.removeprefix("```json").removeprefix("```").strip()
        if clean.endswith("```"):
            clean = clean[:-3].strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_object_not_found")
    return json.loads(clean[start : end + 1])


def resolve_image_path(question: dict[str, Any], source_json: Path) -> Path:
    for key in ("question_image", "stem_image", "analysis_image"):
        raw = str(question.get(key, "") or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = (source_json.parent / path).resolve()
        if path.exists():
            return path
    raise FileNotFoundError("question_image_not_found")


def build_messages(question: dict[str, Any], image_path: Path) -> list[dict[str, Any]]:
    question_id = str(question.get("question_id", "") or question.get("record_id", "") or "")
    bundle = vision_prompt_store.get_image_need_gate_prompt_bundle()
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "QUESTION_ID": question_id,
            "MODULE_ZH": str(question.get("module_zh", "") or ""),
            "SUBMODULE_ZH": str(question.get("submodule_zh", "") or ""),
        },
    )
    content: list[dict[str, Any]] = []
    if bundle.get("system_prompt"):
        content.append({"type": "text", "text": bundle["system_prompt"]})
    content.append({"type": "text", "text": prompt})
    content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    return [{"role": "user", "content": content}]


def normalize_where_values(raw_where: object, *, needs_figure_detection: bool, image_presence: str) -> tuple[list[str], list[str]]:
    values = raw_where if isinstance(raw_where, list) else [raw_where]
    alias = {
        "stem": "stem",
        "question": "stem",
        "public": "stem",
        "public_figure": "stem",
        "题干": "stem",
        "option": "options",
        "options": "options",
        "choice": "options",
        "choices": "options",
        "选项": "options",
        "answer": "analysis",
        "answers": "analysis",
        "solution": "analysis",
        "solutions": "analysis",
        "explanation": "analysis",
        "analysis": "analysis",
        "解析": "analysis",
        "解答": "analysis",
        "答案": "analysis",
        "证明": "analysis",
    }
    normalized: list[str] = []
    flags: list[str] = []
    for item in values:
        key = str(item or "").strip().lower()
        if not key:
            continue
        mapped = alias.get(key)
        if not mapped:
            continue
        if mapped != key:
            flags.append("planner_where_normalized")
        if mapped not in normalized:
            normalized.append(mapped)

    presence = str(image_presence or "").strip().lower()
    if needs_figure_detection and not normalized:
        if "option" in presence:
            normalized.append("options")
        elif "analysis" in presence or "answer" in presence:
            normalized.append("analysis")
        else:
            normalized.extend(["stem", "analysis"])
        flags.append("planner_where_normalized")
    return normalized, sorted(set(flags))


def call_model(question: dict[str, Any], image_path: Path, *, api_key: str, model: str, timeout: int) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "model": model,
        "messages": build_messages(question, image_path),
        "temperature": 0,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"network_error: {exc}") from exc

    payload = json.loads(raw)
    text = payload["choices"][0]["message"]["content"]
    parsed = extract_json_object(text)
    usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
    meta = {
        "latency_seconds": round(time.time() - started, 3),
        "usage": usage,
        "raw_response": payload,
    }
    return parsed, meta


def normalize_gate(question: dict[str, Any], parsed: dict[str, Any], image_path: Path) -> dict[str, Any]:
    question_id = str(question.get("question_id", "") or question.get("record_id", "") or "")
    confidence = parsed.get("confidence", 0)
    try:
        confidence_value = float(confidence)
    except Exception:
        confidence_value = 0.0

    needs_figure_detection = bool(parsed.get("needs_figure_detection", False))
    image_presence = str(parsed.get("image_presence", "uncertain") or "uncertain")
    where, normalize_flags = normalize_where_values(
        parsed.get("where", []),
        needs_figure_detection=needs_figure_detection,
        image_presence=image_presence,
    )
    return {
        "question_id": question_id,
        "record_id": str(question.get("record_id", "") or question_id),
        "status": "ok",
        "needs_figure_detection": needs_figure_detection,
        "image_presence": image_presence,
        "where": where,
        "confidence": round(confidence_value, 4),
        "reason": str(parsed.get("reason", "") or ""),
        "review_flags": normalize_flags,
        "model_gate": True,
        "source_image": str(image_path),
        "module_zh": str(question.get("module_zh", "") or ""),
        "submodule_zh": str(question.get("submodule_zh", "") or ""),
    }


def process_one(
    question: dict[str, Any],
    *,
    source_json: Path,
    out_dir: Path,
    api_key: str,
    model: str,
    timeout: int,
    retries: int,
    force: bool,
) -> dict[str, Any]:
    question_id = str(question.get("question_id", "") or question.get("record_id", "") or "")
    gate_path = out_dir / "gate" / f"{question_id}.gate.json"
    if gate_path.exists() and not force:
        return read_json(gate_path)

    image_path = resolve_image_path(question, source_json)
    last_error = ""
    for attempt in range(1, retries + 2):
        try:
            parsed, meta = call_model(question, image_path, api_key=api_key, model=model, timeout=timeout)
            gate = normalize_gate(question, parsed, image_path)
            gate["attempt"] = attempt
            gate["latency_seconds"] = meta["latency_seconds"]
            gate["usage"] = meta["usage"]
            write_json(gate_path, gate)
            raw_path = out_dir / "gate_raw" / f"{question_id}.response.json"
            write_json(raw_path, meta["raw_response"])
            return gate
        except Exception as exc:
            last_error = str(exc)
            if attempt <= retries:
                time.sleep(min(2 * attempt, 8))
                continue

    gate = {
        "question_id": question_id,
        "record_id": str(question.get("record_id", "") or question_id),
        "status": "failed",
        "needs_figure_detection": True,
        "image_presence": "uncertain",
        "where": ["stem", "analysis"],
        "confidence": 0.0,
        "reason": "gate_model_failed; route to figure detection conservatively",
        "review_flags": ["planner_where_normalized"],
        "model_gate": True,
        "error": last_error,
        "source_image": str(image_path),
        "module_zh": str(question.get("module_zh", "") or ""),
        "submodule_zh": str(question.get("submodule_zh", "") or ""),
    }
    write_json(gate_path, gate)
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description="Model-based image need gate for math question crops.")
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("missing_api_key")

    source_json = Path(args.source_json).expanduser().resolve()
    payload = read_json(source_json)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as executor:
        futures = [
            executor.submit(
                process_one,
                question,
                source_json=source_json,
                out_dir=out_dir,
                api_key=api_key,
                model=str(args.model or DEFAULT_MODEL),
                timeout=int(args.timeout),
                retries=int(args.retries),
                force=bool(args.force),
            )
            for question in questions
            if isinstance(question, dict)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: str(item.get("question_id", "")))
    summary = {
        "schema_version": "model_image_need_gate.v0.2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_json": str(source_json),
        "model": str(args.model or DEFAULT_MODEL),
        "concurrency": int(args.concurrency),
        "question_count": len(results),
        "ok_count": sum(1 for item in results if item.get("status") == "ok"),
        "failed_count": sum(1 for item in results if item.get("status") != "ok"),
        "needs_figure_detection_count": sum(1 for item in results if item.get("needs_figure_detection")),
        "no_figure_count": sum(1 for item in results if not item.get("needs_figure_detection")),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens") or 0) for item in results),
        "prompt_tokens": sum(int((item.get("usage") or {}).get("prompt_tokens") or 0) for item in results),
        "completion_tokens": sum(int((item.get("usage") or {}).get("completion_tokens") or 0) for item in results),
        "results": results,
    }
    write_json(out_dir / "model_image_need_gate_summary.json", summary)
    candidates = [
        item["question_id"]
        for item in results
        if item.get("needs_figure_detection") or item.get("status") != "ok"
    ]
    write_json(out_dir / "figure_candidate_ids.json", candidates)
    print(json.dumps({k: summary[k] for k in summary if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
