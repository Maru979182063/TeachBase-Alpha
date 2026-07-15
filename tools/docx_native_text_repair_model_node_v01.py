from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-mini-260428"
ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "outputs" / "docx_native_text_repair_model_v0_1"
SYSTEM_PROMPT_PATH = ROOT / "config" / "docx_native_text_repair_system_prompt.md"
USER_TEMPLATE_PATH = ROOT / "config" / "docx_native_text_repair_user_template.md"


DEFAULT_SYSTEM_PROMPT = r"""你是 TeachBase DOCX native ingest 的文本修复节点。

你收到的是已经从 Word/document.xml 原生提取并切题后的单题 Markdown。你的任务是开放式修复内容表达，而不是按固定规则替换。

原则：
1. 只修复 Markdown、TeX、数学排版和结构表达，不重新切题，不解题，不改变题意。
2. 保留题干、选项、答案、分析、详解、点评等业务结构，不移动内容归属。
3. 保留所有图片占位符及顺序，尤其是 ![asset_id](asset://asset_id)。
4. 保持 K12 试卷/讲义的常见表达。不要把中文题目改写成论文式或英文式表达。
5. 保持数学符号的语义类别。几何符号、图形名、角度、圆、弧、垂直、平行、填空占位、面积记号等，只能做渲染安全化和结构化，不要改成另一类数学对象。
6. 输出必须是 renderer-safe Markdown：所有数学片段都应能被 MathJax/KaTeX 渲染；占位符、横线、空格、换行、条件组、方程组、分段表达不能被误解释成上下标、命令或未闭合定界符。
7. 对方程组、条件组、分段式、证明中的多行条件，保留行结构，并在 condition_groups 中给出结构化 rows。
8. 不确定的内容不要编造，放入 unresolved_spans。
9. 只返回合法 JSON，不要解释，不要代码块。JSON 字符串中的换行和 TeX 反斜杠必须合法转义。

返回 JSON schema：
{
  "question_id": "原 question_id",
  "repaired_display_markdown": "修复后的完整 Markdown",
  "condition_groups": [
    {
      "source_text": "原片段",
      "latex": "\\\\begin{cases}...\\\\end{cases}",
      "rows": ["..."],
      "confidence": 0.0
    }
  ],
  "repair_actions": [
    {"type": "formula|markdown|structure|uncertain", "before": "...", "after": "...", "reason": "..."}
  ],
  "unresolved_spans": [
    {"text": "...", "reason": "..."}
  ]
}
"""


DEFAULT_USER_TEMPLATE = """请根据系统原则修复下面这道 DOCX native 提取后的题目 Markdown。

只返回符合 schema 的 JSON。

输入：
{{QUESTION_JSON}}
"""


def load_prompt_text(path: Path, fallback: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return fallback.strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def slug_for(path: Path) -> str:
    value = path.parent.name or path.stem
    chars: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in "._-":
            chars.append(ch)
        else:
            chars.append("_")
    return "".join(chars).strip("_")[:120] or "docx_text_repair"


def strip_json_content(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


def call_model(api_key: str, model: str, prompt: str) -> dict[str, Any]:
    system_prompt = load_prompt_text(SYSTEM_PROMPT_PATH, DEFAULT_SYSTEM_PROMPT)
    body = {
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
            return {
                "raw_response": payload,
                "raw_content": content,
                "usage": payload.get("usage", {}) or {},
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"http_{exc.code}: {detail}")
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt >= 2:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt >= 2:
                raise RuntimeError(f"network_error: {exc}") from exc
        time.sleep(1.0 + attempt * 1.5)
    raise RuntimeError(f"network_error: {last_error}")


def build_prompt(question: dict[str, Any]) -> str:
    payload = {
        "question_id": question.get("question_id", ""),
        "asset_ids": question.get("asset_ids", []),
        "display_markdown": question.get("display_markdown", ""),
        "model_segmentation": question.get("model_segmentation", {}),
    }
    template = load_prompt_text(USER_TEMPLATE_PATH, DEFAULT_USER_TEMPLATE)
    return template.replace("{{QUESTION_JSON}}", json.dumps(payload, ensure_ascii=False, indent=2))


def build_retry_prompt(question: dict[str, Any], previous_raw_content: str, validation_issues: list[dict[str, str]]) -> str:
    payload = {
        "question_id": question.get("question_id", ""),
        "asset_ids": question.get("asset_ids", []),
        "original_display_markdown": question.get("display_markdown", ""),
        "previous_model_output": previous_raw_content,
        "validation_issues": validation_issues,
    }
    return (
        "上一次修复输出没有通过质量门。请只根据 validation_issues 修正上一次输出，仍然遵守系统原则和 schema。\n"
        "不要重新切题，不要改动图片占位符，不要编造内容。只返回合法 JSON。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def validate_repair(question: dict[str, Any], repaired_markdown: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    original = str(question.get("display_markdown") or "")
    for asset_id in question.get("asset_ids", []) or []:
        token = f"asset://{asset_id}"
        if token in original and token not in repaired_markdown:
            issues.append({"type": "asset_missing", "asset_id": str(asset_id)})
    if original.count("asset://") != repaired_markdown.count("asset://"):
        issues.append(
            {
                "type": "asset_token_count_changed",
                "before": str(original.count("asset://")),
                "after": str(repaired_markdown.count("asset://")),
            }
        )
    if "\t" in repaired_markdown:
        issues.append({"type": "control_tab_in_markdown", "reason": "likely_unescaped_latex_backslash_in_model_json"})
    if "heta" in repaired_markdown or "extRt" in repaired_markdown:
        issues.append({"type": "likely_latex_escape_loss", "reason": "model_output_contains_heta_or_extRt"})
    if "\\left{" in repaired_markdown or "\\right$" in repaired_markdown:
        issues.append({"type": "broken_condition_group_latex", "reason": "left_right_brace_not_normalized"})
    for item in repaired_markdown.split("$")[1::2]:
        if "___" in item:
            issues.append({"type": "blank_underline_inside_math", "reason": "k12_fill_blank_must_not_render_as_subscript"})
            break
    return issues


def render_preview(out_dir: Path, questions: list[dict[str, Any]], assets: list[dict[str, Any]], title: str) -> None:
    mathjax = """
<script>
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$']],
    processEscapes: true
  },
  options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] },
  chtml: { scale: 1 }
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
"""
    style = "body{margin:0;background:#eef2f7;color:#111827;font-family:'Times New Roman','SimSun','Songti SC',serif}main{max-width:1040px;margin:0 auto;padding:22px 18px}.page-title{font-family:Arial,'Microsoft YaHei',sans-serif;font-size:18px;color:#475569;margin:0 0 18px}article{background:#fff;border:1px solid #d7dee8;margin:0 0 18px;padding:26px 32px}.meta{font-family:Arial,'Microsoft YaHei',sans-serif;color:#64748b;font-size:13px;margin-bottom:14px}h2{font-family:Arial,'Microsoft YaHei',sans-serif;font-size:15px;color:#64748b;font-weight:600;margin:0 0 12px}p{font-size:21px;line-height:2.05;margin:0 0 12px}img{display:block;max-width:900px;max-height:620px;margin:10px 0;border:1px solid #d3dae6}figcaption{display:none}.MathJax{font-size:1.02em!important}"

    asset_by_id = {str(asset.get("asset_id") or ""): asset for asset in assets}
    for asset in assets:
        preview_src = str(asset.get("preview_src") or "")
        storage_key = str(asset.get("storage_key") or "")
        if not preview_src or not storage_key:
            continue
        source = (ROOT / storage_key).resolve() if not Path(storage_key).is_absolute() else Path(storage_key)
        target = out_dir / preview_src
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def render_md(markdown: str) -> str:
        escaped = html.escape(markdown)
        for asset_id, asset in asset_by_id.items():
            token = html.escape(f"![{asset_id}](asset://{asset_id})")
            preview_src = html.escape(str(asset.get("preview_src") or ""))
            replacement = (
                f"<figure><img src='{preview_src}' alt='{html.escape(asset_id)}'>"
                f"<figcaption>{html.escape(asset_id)}</figcaption></figure>"
            )
            escaped = escaped.replace(token, replacement)
        escaped = escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")
        return "<p>" + escaped + "</p>"

    cards: list[str] = []
    for question in questions:
        status = question.get("text_repair", {}).get("status", "unknown")
        action_count = len(question.get("text_repair", {}).get("repair_actions", []) or [])
        unresolved_count = len(question.get("text_repair", {}).get("unresolved_spans", []) or [])
        issue_count = len(question.get("text_repair", {}).get("validation_issues", []) or [])
        meta = f"{status} · actions {action_count} · unresolved {unresolved_count} · issues {issue_count}"
        body = render_md(str(question.get("display_markdown") or ""))
        cards.append(
            f"<article><h2>{html.escape(str(question.get('question_id') or ''))}</h2>"
            f"<div class='meta'>{html.escape(meta)}</div>{body}</article>"
        )
    page = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{style}</style>{mathjax}</head>"
        f"<body><main><h1 class='page-title'>{html.escape(title)}</h1>{''.join(cards)}</main></body></html>"
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Open-ended model repair node for DOCX native question packets.")
    parser.add_argument("--question-packets", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--repair-retries", type=int, default=1)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if not args.api_key.strip():
        raise SystemExit("missing_api_key")

    source_path = args.question_packets.resolve()
    payload = read_json(source_path)
    questions = list(payload.get("questions", []) or [])
    selected_ids = {str(item) for item in args.question_id}
    if selected_ids:
        questions = [q for q in questions if str(q.get("question_id") or "") in selected_ids]
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]

    out_dir = OUT_ROOT / args.run_id / slug_for(source_path)
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    raw_dir = out_dir / "raw_model_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)

    repaired_by_id: dict[str, dict[str, Any]] = {}
    audit_items: list[dict[str, Any]] = []

    def repair_one(index: int, question: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        qid = str(question.get("question_id") or f"q_{index:04d}")
        prompt = build_prompt(question)
        prompt_path = raw_dir / f"{qid}.prompt.json"
        prompt_path.write_text(prompt, encoding="utf-8")
        try:
            parsed: dict[str, Any] = {}
            result: dict[str, Any] = {}
            repaired_markdown = ""
            validation_issues: list[dict[str, str]] = []
            active_prompt = prompt
            raw_response_path = raw_dir / f"{qid}.response.json"
            raw_content_path = raw_dir / f"{qid}.content.txt"
            attempts_used = 0
            for attempt in range(max(0, args.repair_retries) + 1):
                attempts_used = attempt + 1
                suffix = "" if attempt == 0 else f".retry{attempt}"
                if attempt > 0:
                    retry_prompt_path = raw_dir / f"{qid}{suffix}.prompt.json"
                    retry_prompt_path.write_text(active_prompt, encoding="utf-8")
                raw_response_path = raw_dir / f"{qid}{suffix}.response.json"
                raw_content_path = raw_dir / f"{qid}{suffix}.content.txt"
                result = call_model(args.api_key.strip(), args.model, active_prompt)
                write_json(raw_response_path, result.get("raw_response", {}))
                raw_content = str(result.get("raw_content") or "")
                raw_content_path.write_text(raw_content, encoding="utf-8")
                parsed = json.loads(strip_json_content(raw_content))
                repaired_markdown = str(parsed.get("repaired_display_markdown") or "")
                validation_issues = validate_repair(question, repaired_markdown)
                if repaired_markdown and not validation_issues:
                    break
                if attempt < max(0, args.repair_retries):
                    active_prompt = build_retry_prompt(question, raw_content, validation_issues)
            status = "ok" if repaired_markdown and not validation_issues else "needs_review"
            repaired_question = {
                **question,
                "display_markdown": repaired_markdown or question.get("display_markdown", ""),
                "text_repair": {
                    "node": "docx_text_repair_model_node",
                    "status": status,
                    "model": args.model,
                    "repair_actions": parsed.get("repair_actions", []) or [],
                    "condition_groups": parsed.get("condition_groups", []) or [],
                    "unresolved_spans": parsed.get("unresolved_spans", []) or [],
                    "validation_issues": validation_issues,
                    "repair_attempts": attempts_used,
                    "raw_response_path": str(raw_response_path),
                    "raw_content_path": str(raw_content_path),
                    "usage": result.get("usage", {}) or {},
                },
            }
            audit_item = {
                "question_id": qid,
                "status": status,
                "repair_action_count": len(parsed.get("repair_actions", []) or []),
                "condition_group_count": len(parsed.get("condition_groups", []) or []),
                "unresolved_count": len(parsed.get("unresolved_spans", []) or []),
                "repair_attempts": attempts_used,
                "validation_issues": validation_issues,
            }
            return qid, repaired_question, audit_item
        except Exception as exc:
            error_message = str(exc)
            (raw_dir / f"{qid}.error.txt").write_text(error_message, encoding="utf-8")
            repaired_question = {
                **question,
                "text_repair": {
                    "node": "docx_text_repair_model_node",
                    "status": "error",
                    "model": args.model,
                    "error": error_message,
                },
            }
            return qid, repaired_question, {"question_id": qid, "status": "error", "error": error_message}

    indexed_questions = list(enumerate(questions, start=1))
    if args.max_workers > 1 and len(indexed_questions) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(repair_one, index, question) for index, question in indexed_questions]
            for future in concurrent.futures.as_completed(futures):
                qid, repaired_question, audit_item = future.result()
                repaired_by_id[qid] = repaired_question
                audit_items.append(audit_item)
                print(json.dumps({"event": "docx_text_repair_item_done", **audit_item}, ensure_ascii=False), flush=True)
    else:
        for index, question in indexed_questions:
            qid, repaired_question, audit_item = repair_one(index, question)
            repaired_by_id[qid] = repaired_question
            audit_items.append(audit_item)
            print(json.dumps({"event": "docx_text_repair_item_done", **audit_item}, ensure_ascii=False), flush=True)

    output_questions: list[dict[str, Any]] = []
    selected_qids = set(repaired_by_id)
    for question in payload.get("questions", []) or []:
        qid = str(question.get("question_id") or "")
        if qid in repaired_by_id:
            output_questions.append(repaired_by_id[qid])
        elif selected_ids or args.limit:
            output_questions.append(question)
        else:
            output_questions.append(question)

    repaired_payload = {
        **payload,
        "schema_version": "docx_formula_token_question_packets.repaired.v0.1",
        "text_repair_node": {
            "node": "docx_text_repair_model_node",
            "model": args.model,
            "source_question_packets": str(source_path),
            "selected_question_count": len(selected_qids),
            "no_runtime_import": True,
            "no_database_write": True,
        },
        "questions": output_questions,
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "question_packets_formula_tokens.repaired.json", repaired_payload)
    audit = {
        "schema_version": "docx_text_repair_audit.v0.1",
        "run_id": args.run_id,
        "model": args.model,
        "source_question_packets": str(source_path),
        "selected_question_count": len(selected_qids),
        "ok": sum(1 for item in audit_items if item.get("status") == "ok"),
        "needs_review": sum(1 for item in audit_items if item.get("status") == "needs_review"),
        "error": sum(1 for item in audit_items if item.get("status") == "error"),
        "items": audit_items,
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "text_repair_audit.json", audit)
    if selected_ids or args.limit:
        preview_questions = [question for question in output_questions if str(question.get("question_id") or "") in selected_qids]
    else:
        preview_questions = output_questions
    render_preview(out_dir, preview_questions, list(payload.get("assets", []) or []), "DOCX Text Repair Preview")

    summary = {
        "schema_version": "docx_text_repair_summary.v0.1",
        "run_id": args.run_id,
        "model": args.model,
        "out_dir": str(out_dir),
        "source_question_packets": str(source_path),
        "selected_question_count": len(selected_qids),
        "ok": audit["ok"],
        "needs_review": audit["needs_review"],
        "error": audit["error"],
        "artifacts": {
            "repaired_question_packets": str(out_dir / "question_packets_formula_tokens.repaired.json"),
            "text_repair_audit": str(out_dir / "text_repair_audit.json"),
            "raw_model_responses": str(raw_dir),
            "preview_html": str(out_dir / "index.html"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
