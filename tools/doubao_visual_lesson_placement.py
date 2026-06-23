# Purpose:
# - Python companion for Doubao-based visual lesson placement and markdown summary export.
# - This version is useful when OCR/image preprocessing is easier to express in Python utilities.

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-pro-260215"


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


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
    text = str(text or "").strip()
    if not text:
      raise ValueError("empty_model_response")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError("json_object_not_found")

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
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
                return json.loads(text[start : idx + 1])
    raise ValueError("json_object_not_closed")


def build_candidate_packet(knowledge_points: list[dict]) -> list[dict]:
    packet = []
    for point in knowledge_points:
        packet.append(
            {
                "knowledge_id": point["knowledge_id"],
                "module": point["level_2_module"],
                "min_knowledge_point": point["level_3_min_knowledge_point"],
                "lesson_title": point["lesson_title"],
                "stage": point["stage"],
                "grade": point["grade"],
                "season": point["season"],
            }
        )
    return packet


def build_prompt(lesson: dict, knowledge_points: list[dict], question: dict) -> str:
    candidates = build_candidate_packet(knowledge_points)
    return (
        "你是领世培优一对一数学教研落位助手。"
        "这次不是泛化分类，而是把一道题落到当前既有暑假讲义课次里的最小知识点。"
        "请先看题图，OCR 文字只作为辅助。"
        "不要偷懒复述已有考点名，必须根据题目内容判断。"
        "\n\n"
        "已知外层范围已经锁定：\n"
        f"- 学科：数学\n- 学段：{lesson['stage']}\n- 年级：{lesson['grade']}\n- 季节：{lesson['season']}\n"
        f"- 课次：{lesson['lesson_title']}（{lesson['lesson_id']}）\n"
        "\n候选最小知识点如下，只能从这里面选 Top3：\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n"
        "\n当前题目信息：\n"
        f"- question_id: {question['question_id']}\n"
        f"- 讲义内标签: {question.get('checkpoint', '')}\n"
        f"- 组件: {question.get('component_label', '')}\n"
        f"- 本地题号: {question.get('local_number', '')}\n"
        f"- 页码: {','.join(map(str, question.get('visual_pages', [])))}\n"
        f"- OCR辅助文本: {normalize_text(question.get('text_preview', ''))}\n"
        "\n输出要求：\n"
        "1. 只输出一个 JSON 对象，不要加代码块。\n"
        "2. stage / grade / lesson 三层都要给出判断理由，即使范围已锁定，也要写你为什么确认。\n"
        "3. fine_point.top_candidates 与 final_top3 的 knowledge_id 必须来自候选表。\n"
        "4. confidence 只能写 high / medium / low。\n"
        "5. review_status 只能写 accepted_candidate 或 needs_teacher_review。\n"
        "6. question_reading 要像老师一样概括题型、条件、所求和是否依赖图像。\n"
        "\n严格按下面结构输出：\n"
        "{\n"
        '  "question_id": "...",\n'
        '  "question_reading": {\n'
        '    "core_objects": ["..."],\n'
        '    "conditions": ["..."],\n'
        '    "asked_result": "...",\n'
        '    "visual_dependency": "none|formula|diagram|unknown"\n'
        "  },\n"
        '  "layered_trace": {\n'
        '    "stage": {"prediction": "初中|高中", "confidence": "high|medium|low", "reason": "..."},\n'
        '    "grade": {"top_candidates": [{"grade": "...", "confidence": "...", "reason": "..."}]},\n'
        '    "lesson": {"top_candidates": [{"lesson_id": "...", "lesson_title": "...", "confidence": "...", "reason": "..."}]},\n'
        '    "module": {"top_candidates": [{"module": "...", "confidence": "...", "reason": "..."}]},\n'
        '    "fine_point": {"top_candidates": [{"knowledge_id": "...", "module": "...", "min_knowledge_point": "...", "confidence": "...", "reason": "..."}]}\n'
        "  },\n"
        '  "final_top3": [\n'
        '    {"rank": 1, "knowledge_id": "...", "grade": "...", "lesson_title": "...", "module": "...", "min_knowledge_point": "...", "confidence": "high|medium|low", "teacher_review_note": "..."}\n'
        "  ],\n"
        '  "review_status": "accepted_candidate|needs_teacher_review"\n'
        "}"
    )


def call_model(api_key: str, model: str, prompt: str, image_path: Path, include_image: bool) -> dict:
    user_content: str | list[dict]
    if include_image:
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
        ]
    else:
        user_content = prompt
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的K12数学教研落位助手。输出必须是JSON对象。视觉优先，OCR只做辅助。",
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
    parsed = extract_json_block(content)
    return {
        "raw_response": payload,
        "parsed": parsed,
    }


def build_markdown_summary(
    lesson: dict,
    knowledge_points: list[dict],
    results: list[dict],
    out_path: Path,
) -> None:
    top1_counter = Counter()
    needs_review = []
    for item in results:
        parsed = item.get("placement", {})
        top3 = parsed.get("final_top3") or []
        if top3:
            top1_counter[top3[0].get("knowledge_id", "unmatched")] += 1
        if parsed.get("review_status") != "accepted_candidate":
            needs_review.append(item)

    point_map = {point["knowledge_id"]: point for point in knowledge_points}
    lines = [
        f"# 豆包视觉落位结果\n\n",
        f"- 课次：{lesson['lesson_title']}（{lesson['lesson_id']}）\n",
        f"- 学段/年级：{lesson['stage']} / {lesson['grade']}\n",
        f"- 处理题数：{len(results)}\n",
        f"- 需要教师复核：{len(needs_review)}\n\n",
        "## Top1 分布\n\n",
    ]
    for knowledge_id, count in top1_counter.most_common():
        point = point_map.get(knowledge_id, {})
        lines.append(
            f"- {knowledge_id} | {point.get('level_2_module', '')} / {point.get('level_3_min_knowledge_point', '')} ：{count}题\n"
        )
    lines.append("\n## 需要复核\n\n")
    if not needs_review:
        lines.append("- 本轮未出现强制复核题。\n")
    else:
        for item in needs_review:
            parsed = item.get("placement", {})
            top1 = (parsed.get("final_top3") or [{}])[0]
            lines.append(
                f"- {item['question_id']} | {item['checkpoint']} | Top1={top1.get('knowledge_id', '')} | {top1.get('teacher_review_note', '')}\n"
            )
    out_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Use Doubao vision to place split lesson questions into lesson-level knowledge points.")
    parser.add_argument("--split-json", required=True)
    parser.add_argument("--knowledge-json", required=True)
    parser.add_argument("--lessons-json", required=True)
    parser.add_argument("--lesson-id", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--disable-image", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("missing_api_key")

    split_json = Path(args.split_json)
    knowledge_json = Path(args.knowledge_json)
    lessons_json = Path(args.lessons_json)
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    split_data = read_json(split_json)
    all_points = read_json(knowledge_json)
    all_lessons = read_json(lessons_json)
    lesson = next((item for item in all_lessons if item["lesson_id"] == args.lesson_id), None)
    if not lesson:
        raise SystemExit(f"lesson_not_found: {args.lesson_id}")

    knowledge_points = [item for item in all_points if item["lesson_id"] == args.lesson_id]
    if not knowledge_points:
        raise SystemExit(f"knowledge_points_not_found: {args.lesson_id}")

    questions = split_data.get("questions", [])
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    input_mode = "text_only" if args.disable_image else "text_plus_image"
    records = []
    raw_dir = out_dir / "raw"
    ensure_dir(raw_dir)

    for idx, question in enumerate(questions, start=1):
        crop_path = Path(question["crop_path"])
        if not crop_path.exists():
            records.append(
                {
                    "question_id": question["question_id"],
                    "checkpoint": question.get("checkpoint", ""),
                    "status": "failed",
                    "error": f"missing_crop: {crop_path}",
                }
            )
            continue

        prompt = build_prompt(lesson, knowledge_points, question)
        try:
            result = call_model(args.api_key, args.model, prompt, crop_path, include_image=not args.disable_image)
            raw_path = raw_dir / f"{question['question_id']}.response.json"
            raw_path.write_text(json.dumps(result["raw_response"], ensure_ascii=False, indent=2), encoding="utf-8")
            records.append(
                {
                    "question_id": question["question_id"],
                    "checkpoint": question.get("checkpoint", ""),
                    "component_label": question.get("component_label", ""),
                    "crop_path": str(crop_path),
                    "input_mode": input_mode,
                    "placement": result["parsed"],
                    "status": "ok",
                }
            )
        except Exception as exc:  # noqa: BLE001
            records.append(
                {
                    "question_id": question["question_id"],
                    "checkpoint": question.get("checkpoint", ""),
                    "component_label": question.get("component_label", ""),
                    "crop_path": str(crop_path),
                    "input_mode": input_mode,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        time.sleep(max(args.sleep_seconds, 0.0))

    summary = {
        "lesson_id": args.lesson_id,
        "lesson_title": lesson["lesson_title"],
        "question_count": len(records),
        "ok_count": sum(1 for item in records if item["status"] == "ok"),
        "failed_count": sum(1 for item in records if item["status"] != "ok"),
        "model": args.model,
        "input_mode": input_mode,
        "records": records,
    }

    json_path = out_dir / "placement_results.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = []
    for item in records:
        parsed = item.get("placement", {})
        top1 = (parsed.get("final_top3") or [{}])[0]
        compact.append(
            {
                "question_id": item["question_id"],
                "checkpoint": item.get("checkpoint", ""),
                "status": item["status"],
                "top1_knowledge_id": top1.get("knowledge_id", ""),
                "top1_module": top1.get("module", ""),
                "top1_min_knowledge_point": top1.get("min_knowledge_point", ""),
                "review_status": parsed.get("review_status", ""),
                "top1_confidence": top1.get("confidence", ""),
            }
        )
    (out_dir / "placement_compact.json").write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    build_markdown_summary(lesson, knowledge_points, [item for item in records if item["status"] == "ok"], out_dir / "placement_summary.md")
    print(json.dumps({"out_dir": str(out_dir), "question_count": len(records), "ok_count": summary["ok_count"], "failed_count": summary["failed_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
