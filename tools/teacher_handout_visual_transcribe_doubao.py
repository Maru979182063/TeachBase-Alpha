from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-pro-260215"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def restore_latex_control_prefixes(value: object) -> object:
    if isinstance(value, str):
        # Some model outputs use raw LaTeX like \triangle or \because inside JSON strings.
        # JSON decoders treat \t, \b, \f as control escapes, so we restore them back to
        # literal backslash-prefixed macros before storing the transcription.
        return value.replace("\t", "\\t").replace("\b", "\\b").replace("\f", "\\f")
    if isinstance(value, list):
        return [restore_latex_control_prefixes(item) for item in value]
    if isinstance(value, dict):
        return {key: restore_latex_control_prefixes(item) for key, item in value.items()}
    return value


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", str(text or "").strip())
    slug = slug.strip("._-")
    return slug or "item"


def looks_mojibake(text: str) -> bool:
    sample = normalize_text(text)
    if not sample:
        return False
    markers = ("锛", "鈻", "銆", "蟺", "鍒", "渚", "鏁", "瑙", "鐨", "涓", "鍙", "閫")
    marker_hits = sum(sample.count(marker) for marker in markers)
    return marker_hits >= 2


def clean_hint_text(text: str) -> str:
    sample = normalize_text(text)
    if not sample or looks_mojibake(sample):
        return ""
    return sample


def resolve_path(raw_path: str, base_dir: Path | None = None) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    if base_dir is not None:
        return (base_dir / candidate).resolve()
    return candidate.resolve()


def resolve_existing_path(raw_path: str, base_dirs: list[Path]) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    for base_dir in base_dirs:
        resolved = (base_dir / candidate).resolve()
        if resolved.exists():
            return resolved
    return (base_dirs[0] / candidate).resolve()


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("empty_model_response")
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    def _load_json(payload: str) -> dict:
        return restore_latex_control_prefixes(json.loads(payload))

    try:
        return _load_json(clean)
    except json.JSONDecodeError:
        pass

    def _repair_json_string_backslashes(payload: str) -> str:
        out: list[str] = []
        in_string = False
        i = 0
        while i < len(payload):
            ch = payload[i]
            if not in_string:
                out.append(ch)
                if ch == '"':
                    in_string = True
                i += 1
                continue

            if ch == '"':
                backslash_count = 0
                j = i - 1
                while j >= 0 and payload[j] == "\\":
                    backslash_count += 1
                    j -= 1
                out.append(ch)
                if backslash_count % 2 == 0:
                    in_string = False
                i += 1
                continue

            if ch == "\n":
                out.append("\\n")
                i += 1
                continue

            if ch == "\r":
                out.append("\\r")
                i += 1
                continue

            if ch != "\\":
                out.append(ch)
                i += 1
                continue

            next_ch = payload[i + 1] if i + 1 < len(payload) else ""
            if next_ch == "\\":
                out.append("\\\\")
                i += 2
                continue
            if next_ch in {'"', "/"}:
                out.append("\\" + next_ch)
                i += 2
                continue
            if next_ch == "u" and i + 5 < len(payload):
                hex_part = payload[i + 2 : i + 6]
                if re.fullmatch(r"[0-9A-Fa-f]{4}", hex_part):
                    out.append(payload[i : i + 6])
                    i += 6
                    continue
            if next_ch in "bfnrt":
                next_next = payload[i + 2] if i + 2 < len(payload) else ""
                if next_next and next_next.isalpha():
                    out.append("\\\\")
                    i += 1
                    continue
                out.append("\\" + next_ch)
                i += 2
                continue

            out.append("\\\\")
            i += 1

        return "".join(out)

    def _load_with_relaxed_backslashes(payload: str) -> dict:
        repaired = _repair_json_string_backslashes(payload)
        return _load_json(repaired)

    start = clean.find("{")
    if start < 0:
        raise ValueError("json_object_not_found")
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(clean)):
        ch = clean[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                block = clean[start : idx + 1]
                try:
                    return _load_json(block)
                except json.JSONDecodeError:
                    return _load_with_relaxed_backslashes(block)
    raise ValueError("json_object_not_closed")


def derive_record_id(item: dict, source_json_path: Path) -> str:
    explicit = str(item.get("sample_id", "") or item.get("record_id", "")).strip()
    if explicit:
        return safe_slug(explicit)
    parts = [
        safe_slug(item.get("tag", "")),
        safe_slug(source_json_path.parent.name),
        safe_slug(item.get("question_id", "")),
    ]
    return "_".join(part for part in parts if part)


def build_prompt(question: dict, record_id: str) -> str:
    context_lines = [f"- record_id: {record_id}", f"- question_id: {question.get('question_id', '')}"]
    for label, value in (
        ("checkpoint", clean_hint_text(question.get("checkpoint", ""))),
        ("component_label", clean_hint_text(question.get("component_label", ""))),
        ("local_number", clean_hint_text(question.get("local_number", ""))),
    ):
        if value:
            context_lines.append(f"- {label}: {value}")

    hint_lines = []
    for label, value in (
        ("auto_stem_text", clean_hint_text(question.get("stem_text", ""))),
        ("auto_answer_text", clean_hint_text(question.get("answer_text", ""))),
        ("auto_analysis_text", clean_hint_text(question.get("analysis_text", ""))),
    ):
        if value:
            hint_lines.append(f"- {label}: {value}")

    return (
        "You are a strict K12 teacher-handout transcription assistant.\n"
        "Task: transcribe one question from images into structured fields.\n"
        "The images are the source of truth. The auto text hints are noisy and may be wrong.\n"
        "Return JSON only. Do not add commentary or markdown fences.\n\n"
        "You may receive up to three images in this order:\n"
        "1. question_image: the full question crop\n"
        "2. stem_image: the stem-focused crop when available\n"
        "3. analysis_image: the answer/analysis-focused crop when available\n\n"
        "Rules:\n"
        "1. Preserve visible wording as faithfully as possible.\n"
        "2. Use Markdown for prose.\n"
        "3. Use standard LaTeX for math. Use $...$ for inline math and $$...$$ for display math when needed.\n"
        "4. Do not invent unreadable text. If uncertain, keep the readable part and list the uncertain span.\n"
        "5. If the stem or analysis depends on a diagram, table, or figure, still transcribe visible text and set the matching *_requires_image field to true.\n"
        "6. analysis_text_md must preserve every teacher-side explanation block that belongs to this question, including labels such as 分析, 解答, 证明, 思路, 点评, 结论. Merge them into one field in reading order. Do not drop one block just because another explanation block is present.\n"
        "7. For objective answers, keep only the answer content, such as A, C, $\\frac{3}{4}$, or $\\sqrt{2}$.\n"
        "8. If there is no standalone answer field, use an empty string for answer_text_md.\n"
        "9. If a diagram is the main evidence and text alone is insufficient, do not hallucinate the missing geometry conditions.\n\n"
        "Context:\n"
        f"{chr(10).join(context_lines)}\n\n"
        "Optional helper hints. Ignore them when they conflict with the image:\n"
        f"{chr(10).join(hint_lines) if hint_lines else '- none'}\n\n"
        "Output schema:\n"
        "{\n"
        '  "record_id": "...",\n'
        '  "question_id": "...",\n'
        '  "stem_text_md": "...",\n'
        '  "answer_text_md": "...",\n'
        '  "analysis_text_md": "...",\n'
        '  "stem_requires_image": true,\n'
        '  "analysis_requires_image": true,\n'
        '  "uncertain_spans": [\n'
        '    {"field": "stem|answer|analysis", "text": "...", "reason": "formula|symbol|diagram|table|other"}\n'
        "  ]\n"
        "}\n"
    )


def call_model(api_key: str, model: str, prompt: str, image_paths: list[Path]) -> dict:
    user_content: list[dict] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        user_content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You transcribe K12 handout questions from images. "
                    "Images are primary evidence, helper text is noisy, output must be one JSON object."
                ),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
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
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc

    payload = json.loads(raw)
    content = payload["choices"][0]["message"]["content"]
    return {
        "raw_response": payload,
        "raw_content": content,
        "usage": payload.get("usage", {}) or {},
    }


def load_source_questions(source_json_path: Path) -> dict[str, dict]:
    payload = read_json(source_json_path)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    return {str(question["question_id"]): question for question in questions}


def build_items_from_manifest(manifest_path: Path) -> list[dict]:
    payload = read_json(manifest_path)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    normalized: list[dict] = []
    base_dirs = [manifest_path.parent.resolve(), Path.cwd().resolve()]
    for item in items:
        normalized.append(
            {
                "sample_id": str(item.get("sample_id", "")).strip(),
                "source_transcription_json": str(
                    resolve_existing_path(item["source_transcription_json"], base_dirs)
                ),
                "question_id": str(item["question_id"]),
                "tag": str(item.get("tag", "")).strip(),
            }
        )
    return normalized


def build_items_from_args(source_json_path: Path, question_ids: list[str], record_prefix: str) -> list[dict]:
    prefix = safe_slug(record_prefix) if record_prefix else ""
    items: list[dict] = []
    for question_id in question_ids:
        sample_id = f"{prefix}_{question_id}" if prefix else question_id
        items.append(
            {
                "sample_id": sample_id,
                "source_transcription_json": str(source_json_path.resolve()),
                "question_id": question_id,
                "tag": prefix,
            }
        )
    return items


def collect_image_paths(question: dict) -> list[Path]:
    ordered_keys = ["question_image", "stem_image", "analysis_image"]
    paths: list[Path] = []
    seen: set[str] = set()
    for key in ordered_keys:
        raw = str(question.get(key, "") or "").strip()
        if not raw or raw in seen:
            continue
        path = Path(raw)
        if path.exists():
            paths.append(path)
            seen.add(raw)
    return paths


def summarize_record(item: dict, status: str, parsed: dict | None = None, error: str = "") -> dict:
    summary = {
        "record_id": item["record_id"],
        "question_id": item["question_id"],
        "source_transcription_json": item["source_transcription_json"],
        "status": status,
        "tag": item.get("tag", ""),
    }
    if parsed:
        summary.update(
            {
                "stem_text_md": parsed.get("stem_text_md", ""),
                "answer_text_md": parsed.get("answer_text_md", ""),
                "analysis_text_md": parsed.get("analysis_text_md", ""),
                "stem_requires_image": parsed.get("stem_requires_image", False),
                "analysis_requires_image": parsed.get("analysis_requires_image", False),
                "uncertain_span_count": len(parsed.get("uncertain_spans", []) or []),
                "latency_seconds": item.get("latency_seconds", 0.0),
                "usage_total_tokens": (item.get("usage", {}) or {}).get("total_tokens", 0),
                "usage_prompt_tokens": (item.get("usage", {}) or {}).get("prompt_tokens", 0),
                "usage_completion_tokens": (item.get("usage", {}) or {}).get("completion_tokens", 0),
            }
        )
    if error:
        summary["error"] = error
    return summary


def print_json(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def aggregate_usage(records: list[dict]) -> dict:
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "image_tokens": 0,
    }
    for record in records:
        usage = record.get("usage", {}) or {}
        for key in totals:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                totals[key] += value
    return totals


def aggregate_latency(records: list[dict]) -> dict:
    values = [
        float(record.get("latency_seconds"))
        for record in records
        if isinstance(record.get("latency_seconds"), (int, float))
    ]
    if not values:
        return {
            "count": 0,
            "avg_seconds": 0.0,
            "max_seconds": 0.0,
            "min_seconds": 0.0,
        }
    return {
        "count": len(values),
        "avg_seconds": round(sum(values) / len(values), 3),
        "max_seconds": round(max(values), 3),
        "min_seconds": round(min(values), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Use a visual model to transcribe teacher-handout questions field by field.")
    parser.add_argument("--manifest")
    parser.add_argument("--source-transcription-json")
    parser.add_argument("--question-ids", default="")
    parser.add_argument("--record-prefix", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    raw_dir = out_dir / "raw"
    ensure_dir(raw_dir)

    if args.manifest:
        items = build_items_from_manifest(Path(args.manifest).resolve())
    else:
        if not args.source_transcription_json:
            raise SystemExit("missing_source_transcription_json")
        question_ids = [item.strip() for item in args.question_ids.split(",") if item.strip()]
        if not question_ids:
            raise SystemExit("missing_question_ids")
        items = build_items_from_args(Path(args.source_transcription_json), question_ids, args.record_prefix)

    if args.limit and args.limit > 0:
        items = items[: args.limit]

    source_cache: dict[str, dict[str, dict]] = {}
    records: list[dict] = []

    for item in items:
        source_json_path = Path(item["source_transcription_json"]).resolve()
        record_id = derive_record_id(item, source_json_path)
        if str(source_json_path) not in source_cache:
            source_cache[str(source_json_path)] = load_source_questions(source_json_path)
        source_questions = source_cache[str(source_json_path)]
        question = source_questions.get(item["question_id"])
        if not question:
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "failed",
                    "error": "question_not_found",
                    "tag": item.get("tag", ""),
                }
            )
            continue

        image_paths = collect_image_paths(question)
        if not image_paths:
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "failed",
                    "error": "no_images_found",
                    "tag": item.get("tag", ""),
                }
            )
            continue

        prompt = build_prompt(question, record_id)
        prepared = {
            "record_id": record_id,
            "question_id": item["question_id"],
            "source_transcription_json": str(source_json_path),
            "question_image": question.get("question_image", ""),
            "stem_image": question.get("stem_image", ""),
            "analysis_image": question.get("analysis_image", ""),
            "image_count": len(image_paths),
            "prompt": prompt,
            "tag": item.get("tag", ""),
        }
        write_json(raw_dir / f"{record_id}.prepared.json", prepared)

        if args.prepare_only:
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "prepared",
                    "tag": item.get("tag", ""),
                    "image_count": len(image_paths),
                }
            )
            continue

        if not args.api_key:
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "failed",
                    "error": "missing_api_key",
                    "tag": item.get("tag", ""),
                }
            )
            continue

        result = None
        started_at_iso = utc_now_iso()
        started_perf = time.perf_counter()
        try:
            result = call_model(args.api_key, args.model, prompt, image_paths)
            finished_at_iso = utc_now_iso()
            latency_seconds = round(time.perf_counter() - started_perf, 3)
            write_json(raw_dir / f"{record_id}.response.json", result["raw_response"])
            (raw_dir / f"{record_id}.response.txt").write_text(
                str(result.get("raw_content", "")),
                encoding="utf-8",
            )
            parsed = extract_json_block(result["raw_content"])
            if "record_id" not in parsed:
                parsed["record_id"] = record_id
            if "question_id" not in parsed:
                parsed["question_id"] = item["question_id"]
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "ok",
                    "tag": item.get("tag", ""),
                    "question_image": question.get("question_image", ""),
                    "stem_image": question.get("stem_image", ""),
                    "analysis_image": question.get("analysis_image", ""),
                    "request_started_at": started_at_iso,
                    "request_finished_at": finished_at_iso,
                    "latency_seconds": latency_seconds,
                    "usage": result.get("usage", {}) or {},
                    "transcription": parsed,
                }
            )
        except Exception as exc:  # noqa: BLE001
            finished_at_iso = utc_now_iso()
            latency_seconds = round(time.perf_counter() - started_perf, 3)
            if isinstance(result, dict) and result.get("raw_response"):
                write_json(raw_dir / f"{record_id}.response_failed_parse.json", result["raw_response"])
            if isinstance(result, dict) and result.get("raw_content") is not None:
                (raw_dir / f"{record_id}.response_failed_parse.txt").write_text(
                    str(result.get("raw_content", "")),
                    encoding="utf-8",
                )
            records.append(
                {
                    "record_id": record_id,
                    "question_id": item["question_id"],
                    "source_transcription_json": str(source_json_path),
                    "status": "failed",
                    "error": str(exc),
                    "tag": item.get("tag", ""),
                    "request_started_at": started_at_iso,
                    "request_finished_at": finished_at_iso,
                    "latency_seconds": latency_seconds,
                    "usage": result.get("usage", {}) if isinstance(result, dict) else {},
                }
            )
        time.sleep(max(args.sleep_seconds, 0.0))

    ok_records = [item for item in records if item["status"] == "ok"]
    summary = {
        "model": args.model,
        "question_count": len(records),
        "ok_count": len(ok_records),
        "prepared_count": sum(1 for item in records if item["status"] == "prepared"),
        "failed_count": sum(1 for item in records if item["status"] == "failed"),
        "usage_totals": aggregate_usage(ok_records),
        "latency_summary": aggregate_latency(records),
        "records": records,
    }
    write_json(out_dir / "visual_transcription_results.json", summary)
    compact = []
    for item in records:
        compact.append(
            summarize_record(
                item,
                status=item["status"],
                parsed=item.get("transcription"),
                error=item.get("error", ""),
            )
        )
    write_json(out_dir / "visual_transcription_compact.json", compact)
    print_json(
        {
            "out_dir": str(out_dir),
            "question_count": len(records),
            "ok_count": summary["ok_count"],
            "prepared_count": summary["prepared_count"],
            "failed_count": summary["failed_count"],
            "usage_totals": summary["usage_totals"],
            "latency_summary": summary["latency_summary"],
        }
    )


if __name__ == "__main__":
    main()
