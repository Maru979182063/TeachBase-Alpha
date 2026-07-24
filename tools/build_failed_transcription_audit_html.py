from __future__ import annotations

import argparse
import difflib
import html
import json
import re
from collections import Counter
from pathlib import Path

import visual_transcription_strict_eval_adapter as strict_eval_adapter


FIELD_SPECS = (
    ("stem", "题干", "stem_text_md", "gold_stem_text_md"),
    ("answer", "答案", "answer_text_md", "gold_answer_text_md"),
    ("analysis", "解析", "analysis_text_md", "gold_analysis_text_md"),
)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def strict_normalize_fields(fields: dict[str, str]) -> dict[str, str]:
    payload = {
        "display_normalized_text": {
            "stem_text_md": str(fields.get("stem_text_md", "") or ""),
            "answer_text_md": str(fields.get("answer_text_md", "") or ""),
            "analysis_text_md": str(fields.get("analysis_text_md", "") or ""),
        }
    }
    normalized = strict_eval_adapter.normalize_transcription_fields(payload)
    return {
        "stem_text_md": str(normalized.get("stem_text_md", "") or ""),
        "answer_text_md": str(normalized.get("answer_text_md", "") or ""),
        "analysis_text_md": str(normalized.get("analysis_text_md", "") or ""),
    }


def highlight_diff(auto_text: str, gold_text: str) -> tuple[str, str, list[dict]]:
    matcher = difflib.SequenceMatcher(a=auto_text, b=gold_text)
    auto_parts: list[str] = []
    gold_parts: list[str] = []
    snippets: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        auto_chunk = auto_text[i1:i2]
        gold_chunk = gold_text[j1:j2]
        if tag == "equal":
            auto_parts.append(html.escape(auto_chunk))
            gold_parts.append(html.escape(gold_chunk))
            continue
        if tag in {"replace", "delete"} and auto_chunk:
            auto_parts.append(f'<span class="diff-auto">{html.escape(auto_chunk)}</span>')
        if tag == "insert":
            auto_parts.append('<span class="diff-auto-empty">∅</span>')
        if tag in {"replace", "insert"} and gold_chunk:
            gold_parts.append(f'<span class="diff-gold">{html.escape(gold_chunk)}</span>')
        if tag == "delete":
            gold_parts.append('<span class="diff-gold-empty">∅</span>')
        if tag != "equal":
            snippets.append(
                {
                    "tag": tag,
                    "auto": auto_chunk,
                    "gold": gold_chunk,
                }
            )
    return "".join(auto_parts), "".join(gold_parts), snippets


def short_preview(text: str, limit: int = 48) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def detect_reason_tags(
    field_key: str,
    auto_text: str,
    gold_text: str,
    snippets: list[dict],
    record: dict,
) -> list[str]:
    reasons: list[str] = []
    auto_strip = auto_text.strip()
    gold_strip = gold_text.strip()
    if not auto_strip and gold_strip:
        reasons.append(f"{field_key}_missing")
    elif auto_strip and not gold_strip:
        reasons.append(f"{field_key}_extra")
    elif auto_strip != gold_strip:
        reasons.append(f"{field_key}_mismatch")

    if len(auto_strip) > max(len(gold_strip) * 2, 40):
        reasons.append(f"{field_key}_too_long")
    if gold_strip and len(auto_strip) < max(int(len(gold_strip) * 0.5), 1):
        reasons.append(f"{field_key}_too_short")

    if "tq_" in auto_text or re.search(r"\bp\d+\b", auto_text):
        reasons.append(f"{field_key}_template_noise")
    if auto_text.count("例") >= 2 or auto_text.count("【例") >= 2:
        reasons.append(f"{field_key}_multi_question_merged")
    if auto_text.count("A.") > 1 or auto_text.count("A．") > 1:
        reasons.append(f"{field_key}_options_duplicated")
    if any(token in "".join(part.get("auto", "") + part.get("gold", "") for part in snippets) for token in ("+", "-", "=", "\\frac", "\\sqrt", "^", "_", "∠", "⊥", "∥")):
        reasons.append(f"{field_key}_symbol_formula_risk")
    if record.get("transcription", {}).get(f"{field_key}_requires_image"):
        reasons.append(f"{field_key}_image_dependent")
    if record.get("transcription", {}).get("uncertain_spans"):
        reasons.append(f"{field_key}_uncertain_span")
    return sorted(set(reasons))


def build_field_summary(field_label: str, snippets: list[dict]) -> list[str]:
    lines: list[str] = []
    for snippet in snippets[:6]:
        auto_part = short_preview(snippet.get("auto", "") or "∅", 36) or "∅"
        gold_part = short_preview(snippet.get("gold", "") or "∅", 36) or "∅"
        lines.append(f"{field_label}: 模型「{auto_part}」 -> 金标「{gold_part}」")
    return lines


def markdown_block(text: str) -> str:
    escaped = html.escape(text or "")
    return escaped.replace("\n", "<br />")


def image_src(image_path: str, out_dir: Path) -> str:
    if not image_path:
        return ""
    path = Path(image_path)
    try:
        return path.relative_to(out_dir).as_posix()
    except ValueError:
        return path.as_uri()


def build_case_row(record: dict, gold_row: dict, out_dir: Path) -> dict:
    transcription = record.get("transcription") or {}
    auto_fields = strict_normalize_fields(
        {
            "stem_text_md": transcription.get("stem_text_md", ""),
            "answer_text_md": transcription.get("answer_text_md", ""),
            "analysis_text_md": transcription.get("analysis_text_md", ""),
        }
    )
    gold_fields = strict_normalize_fields(
        {
            "stem_text_md": gold_row.get("gold_stem_text_md", ""),
            "answer_text_md": gold_row.get("gold_answer_text_md", ""),
            "analysis_text_md": gold_row.get("gold_analysis_text_md", ""),
        }
    )
    field_rows = []
    reason_tags: list[str] = []
    reason_lines: list[str] = []
    mismatch_fields: list[str] = []

    for field_key, field_label, auto_key, gold_key in FIELD_SPECS:
        auto_text = auto_fields[auto_key]
        gold_text = gold_fields[auto_key]
        auto_html, gold_html, snippets = highlight_diff(auto_text, gold_text)
        exact = auto_text == gold_text
        if not exact:
            mismatch_fields.append(field_key)
        local_reasons = detect_reason_tags(field_key, auto_text, gold_text, snippets, record)
        reason_tags.extend(local_reasons)
        reason_lines.extend(build_field_summary(field_label, snippets))
        field_rows.append(
            {
                "field_key": field_key,
                "field_label": field_label,
                "exact": exact,
                "reason_tags": local_reasons,
                "auto_raw": auto_text,
                "gold_raw": gold_text,
                "auto_html": auto_html,
                "gold_html": gold_html,
            }
        )

    image_path = (
        str(record.get("question_image", "") or "")
        or str(gold_row.get("image_path", "") or "")
        or str(gold_row.get("question_image", "") or "")
    )
    return {
        "case_id": record.get("record_id", ""),
        "question_id": record.get("question_id", ""),
        "module_zh": gold_row.get("module_zh", ""),
        "submodule_zh": gold_row.get("submodule_zh", ""),
        "tags_zh": gold_row.get("tags_zh", ""),
        "status": record.get("status", ""),
        "latency_seconds": record.get("latency_seconds", ""),
        "usage_total_tokens": (record.get("usage") or {}).get("total_tokens", ""),
        "manual_status": gold_row.get("manual_status", ""),
        "manual_review_note": gold_row.get("manual_review_note", ""),
        "source_issue": gold_row.get("source_issue", ""),
        "image_path": image_path,
        "image_src": image_src(image_path, out_dir),
        "field_rows": field_rows,
        "reason_tags": sorted(set(reason_tags)),
        "reason_lines": reason_lines,
        "mismatch_fields": mismatch_fields,
        "mismatch_count": len(mismatch_fields),
    }


def render_badges(items: list[str], css_class: str) -> str:
    if not items:
        return '<span class="badge badge-muted">无</span>'
    return "".join(
        f'<span class="badge {css_class}">{html.escape(item)}</span>' for item in items
    )


def build_html(case_rows: list[dict], out_path: Path) -> None:
    field_counter = Counter()
    reason_counter = Counter()
    for row in case_rows:
        field_counter.update(row["mismatch_fields"])
        reason_counter.update(row["reason_tags"])

    cards: list[str] = []
    for row in case_rows:
        field_blocks: list[str] = []
        for field in row["field_rows"]:
            field_blocks.append(
                """
<section class="field-card {status_class}">
  <div class="field-head">
    <div class="field-title">{field_label}</div>
    <div class="field-meta">
      <span class="state">{state}</span>
      {reason_badges}
    </div>
  </div>
  <div class="field-panels">
    <div class="panel">
      <div class="panel-title">模型输出</div>
      <div class="diff-box">{auto_html}</div>
    </div>
    <div class="panel">
      <div class="panel-title">人工金标</div>
      <div class="diff-box">{gold_html}</div>
    </div>
  </div>
</section>
""".format(
                    status_class="field-bad" if not field["exact"] else "field-good",
                    field_label=html.escape(field["field_label"]),
                    state="一致" if field["exact"] else "不一致",
                    reason_badges=render_badges(field["reason_tags"], "badge-reason"),
                    auto_html=field["auto_html"] or '<span class="empty">∅</span>',
                    gold_html=field["gold_html"] or '<span class="empty">∅</span>',
                )
            )

        reason_lines = row["reason_lines"][:10]
        cards.append(
            """
<article class="card">
  <div class="card-head">
    <div>
      <div class="case-id">{case_id}</div>
      <div class="case-meta">{module_zh} / {submodule_zh}</div>
      <div class="case-tags">{tags_zh}</div>
    </div>
    <div class="head-right">
      <div class="metrics">
        <span>{status}</span>
        <span>{tokens} tok</span>
        <span>{latency}s</span>
      </div>
      <div class="badges">
        {field_badges}
      </div>
    </div>
  </div>
  <div class="card-body">
    <div class="image-column">
      {image_html}
      <div class="note-box">
        <div class="note-title">问题摘要</div>
        <div class="badge-row">{reason_badges}</div>
        <ul>{reason_list}</ul>
      </div>
      <div class="note-box compact">
        <div class="note-title">金标备注</div>
        <pre>manual_status: {manual_status}\nsource_issue: {source_issue}\nnote: {manual_review_note}</pre>
      </div>
    </div>
    <div class="fields-column">
      {field_blocks}
    </div>
  </div>
</article>
""".format(
                case_id=html.escape(str(row["case_id"])),
                module_zh=html.escape(str(row["module_zh"])),
                submodule_zh=html.escape(str(row["submodule_zh"])),
                tags_zh=html.escape(str(row["tags_zh"])),
                status=html.escape(str(row["status"])),
                tokens=html.escape(str(row["usage_total_tokens"])),
                latency=html.escape(str(row["latency_seconds"])),
                field_badges=render_badges(row["mismatch_fields"], "badge-field"),
                image_html=(
                    f'<img src="{html.escape(row["image_src"])}" loading="lazy" />'
                    if row["image_src"]
                    else '<div class="missing">image missing</div>'
                ),
                reason_badges=render_badges(row["reason_tags"], "badge-reason"),
                reason_list="".join(f"<li>{html.escape(line)}</li>" for line in reason_lines) or "<li>无</li>",
                manual_status=html.escape(str(row["manual_status"])),
                source_issue=html.escape(str(row["source_issue"])),
                manual_review_note=html.escape(str(row["manual_review_note"])),
                field_blocks="".join(field_blocks),
            )
        )

    summary_html = """
<div class="summary-grid">
  <section class="summary-card">
    <h3>字段命中概览</h3>
    <div class="summary-line">题干不一致：{stem_count}</div>
    <div class="summary-line">答案不一致：{answer_count}</div>
    <div class="summary-line">解析不一致：{analysis_count}</div>
  </section>
  <section class="summary-card">
    <h3>高频错因</h3>
    <div class="counter-list">{reason_counts}</div>
  </section>
</div>
""".format(
        stem_count=field_counter.get("stem", 0),
        answer_count=field_counter.get("answer", 0),
        analysis_count=field_counter.get("analysis", 0),
        reason_counts="".join(
            f'<div class="counter-item"><span>{html.escape(reason)}</span><strong>{count}</strong></div>'
            for reason, count in reason_counter.most_common()
        )
        or '<div class="counter-item"><span>无</span><strong>0</strong></div>',
    )

    doc = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>41题失败转录审查页</title>
  <style>
    body { margin: 0; background: #f4f6fb; color: #182230; font-family: "Microsoft YaHei", Arial, sans-serif; }
    header { position: sticky; top: 0; z-index: 5; background: rgba(255,255,255,0.95); backdrop-filter: blur(10px); border-bottom: 1px solid #d9e2f0; padding: 18px 24px; }
    h1 { margin: 0 0 6px; font-size: 24px; }
    .subtitle { color: #5b6578; font-size: 14px; }
    main { padding: 18px; display: grid; gap: 16px; }
    .summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .summary-card, .card { background: #fff; border: 1px solid #dde5f2; border-radius: 14px; box-shadow: 0 10px 24px rgba(16, 24, 40, 0.04); }
    .summary-card { padding: 16px 18px; }
    .summary-card h3 { margin: 0 0 10px; font-size: 16px; }
    .summary-line { margin: 8px 0; font-size: 14px; color: #344054; }
    .counter-list { display: grid; gap: 8px; }
    .counter-item { display: flex; justify-content: space-between; gap: 16px; font-size: 13px; padding: 8px 10px; border-radius: 10px; background: #f8fbff; }
    .card-head { display: flex; justify-content: space-between; gap: 18px; padding: 16px 18px; border-bottom: 1px solid #e8eef7; background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%); }
    .case-id { font-size: 18px; font-weight: 700; color: #183b73; }
    .case-meta, .case-tags { margin-top: 4px; font-size: 13px; color: #596579; }
    .head-right { display: grid; justify-items: end; gap: 10px; }
    .metrics, .badges, .badge-row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
    .badge { display: inline-flex; align-items: center; padding: 4px 8px; border-radius: 999px; font-size: 12px; }
    .badge-field { background: #fee4e2; color: #b42318; }
    .badge-reason { background: #fff1f3; color: #c01048; }
    .badge-muted { background: #eef2f6; color: #667085; }
    .card-body { display: grid; grid-template-columns: minmax(320px, 32%) minmax(660px, 68%); gap: 16px; padding: 16px; }
    .image-column, .fields-column { display: grid; gap: 12px; align-content: start; }
    img { width: 100%; border-radius: 10px; border: 1px solid #e5ebf4; background: #fff; }
    .missing { min-height: 220px; border: 1px dashed #c6d0e1; border-radius: 10px; display: grid; place-items: center; color: #6b7280; background: #fbfcfe; }
    .note-box { border: 1px solid #e5ebf4; border-radius: 10px; padding: 12px; background: #fbfdff; }
    .note-title { font-size: 13px; font-weight: 700; margin-bottom: 8px; color: #334155; }
    .note-box ul { margin: 8px 0 0 18px; padding: 0; }
    .note-box li { margin: 6px 0; color: #475467; font-size: 13px; }
    .note-box pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.55; font-family: Consolas, "Courier New", monospace; }
    .field-card { border: 1px solid #e5ebf4; border-radius: 12px; overflow: hidden; }
    .field-good { background: #fcfffd; }
    .field-bad { background: #fffdfd; }
    .field-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 10px 12px; border-bottom: 1px solid #edf2f7; background: #f9fbff; }
    .field-title { font-size: 14px; font-weight: 700; }
    .field-meta { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
    .state { font-size: 12px; color: #475467; }
    .field-panels { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px; }
    .panel { border: 1px solid #edf2f7; border-radius: 10px; overflow: hidden; background: #fff; }
    .panel-title { padding: 8px 10px; font-size: 12px; font-weight: 700; background: #f8fafc; border-bottom: 1px solid #edf2f7; }
    .diff-box { padding: 10px; min-height: 64px; white-space: pre-wrap; word-break: break-word; line-height: 1.65; font-size: 12px; font-family: Consolas, "Courier New", monospace; }
    .diff-auto { background: #ffe2e0; color: #b42318; border-radius: 4px; }
    .diff-gold { background: #dcfae6; color: #067647; border-radius: 4px; }
    .diff-auto-empty, .diff-gold-empty, .empty { color: #98a2b3; font-style: italic; }
    @media (max-width: 1300px) {
      .summary-grid, .card-body, .field-panels { grid-template-columns: 1fr; }
      .head-right { justify-items: start; }
      .metrics, .badges, .badge-row { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <header>
    <h1>41题失败转录审查页</h1>
    <div class="subtitle">按字段对照当前 skill 输出与人工金标。模型错误片段标红，金标对应差异标绿，便于人工逐题扫查。</div>
  </header>
  <main>
    __SUMMARY__
    __CARDS__
  </main>
</body>
</html>
"""
    doc = doc.replace("__SUMMARY__", summary_html).replace("__CARDS__", "".join(cards))
    out_path.write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-json", required=True)
    parser.add_argument("--gold-json", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    run_json = Path(args.run_json).resolve()
    gold_json = Path(args.gold_json).resolve()
    out_dir = Path(args.out_dir).resolve()
    ensure_dir(out_dir)

    run_payload = read_json(run_json)
    gold_rows = read_json(gold_json)
    gold_by_case = {str(row.get("case_id", "")): row for row in gold_rows}

    case_rows = []
    for record in run_payload.get("records", []):
        case_id = str(record.get("record_id", ""))
        gold_row = gold_by_case.get(case_id)
        if not gold_row:
            continue
        case_rows.append(build_case_row(record, gold_row, out_dir))

    case_rows.sort(key=lambda row: (-row["mismatch_count"], row["case_id"]))

    json_path = out_dir / "failed_cases_audit.json"
    html_path = out_dir / "failed_cases_audit.html"
    summary_path = out_dir / "failed_cases_audit_summary.json"

    json_path.write_text(json.dumps(case_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    build_html(case_rows, html_path)
    summary = {
        "case_count": len(case_rows),
        "run_json": str(run_json),
        "gold_json": str(gold_json),
        "html": str(html_path),
        "json": str(json_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
