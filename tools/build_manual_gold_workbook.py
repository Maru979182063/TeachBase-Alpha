from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_preview_md(stem: str, answer: str, analysis: str) -> str:
    return "\n\n".join(
        [
            "## 题干",
            stem.strip(),
            "## 答案",
            answer.strip(),
            "## 解析",
            analysis.strip(),
        ]
    ).strip()


def make_gold_row(row: dict) -> dict:
    stem = str(row.get("stem_text_md", "") or "")
    answer = str(row.get("answer_text_md", "") or "")
    analysis = str(row.get("analysis_text_md", "") or "")
    return {
        "case_id": row.get("case_id", ""),
        "question_id": row.get("question_id", ""),
        "module_en": row.get("module_en", ""),
        "module_zh": row.get("module_zh", ""),
        "submodule_en": row.get("submodule_en", ""),
        "submodule_zh": row.get("submodule_zh", ""),
        "tags_en": row.get("tags_en", ""),
        "tags_zh": row.get("tags_zh", ""),
        "image_path": row.get("image_path", ""),
        "question_image": row.get("question_image", ""),
        "analysis_image": row.get("analysis_image", ""),
        "usage_total_tokens": row.get("usage_total_tokens", ""),
        "latency_seconds": row.get("latency_seconds", ""),
        "auto_stem_text_md": stem,
        "auto_answer_text_md": answer,
        "auto_analysis_text_md": analysis,
        "manual_status": "pending",
        "manual_review_note": "",
        "source_issue": "",
        "gold_stem_text_md": stem,
        "gold_answer_text_md": answer,
        "gold_analysis_text_md": analysis,
        "gold_requires_image_stem": row.get("stem_requires_image", False),
        "gold_requires_image_analysis": row.get("analysis_requires_image", False),
        "gold_uncertain_spans": row.get("uncertain_spans", ""),
        "gold_preview_md": build_preview_md(stem, answer, analysis),
    }


def write_csv(rows: list[dict], out_path: Path) -> None:
    headers = [
        "case_id",
        "question_id",
        "module_en",
        "module_zh",
        "submodule_en",
        "submodule_zh",
        "tags_en",
        "tags_zh",
        "image_path",
        "question_image",
        "analysis_image",
        "usage_total_tokens",
        "latency_seconds",
        "manual_status",
        "manual_review_note",
        "source_issue",
        "auto_stem_text_md",
        "auto_answer_text_md",
        "auto_analysis_text_md",
        "gold_stem_text_md",
        "gold_answer_text_md",
        "gold_analysis_text_md",
        "gold_requires_image_stem",
        "gold_requires_image_analysis",
        "gold_uncertain_spans",
        "gold_preview_md",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def build_html(rows: list[dict], out_path: Path) -> None:
    cards: list[str] = []
    for row in rows:
        image_rel = ""
        image_path = str(row.get("image_path", "") or "")
        if image_path:
            try:
                image_rel = Path(image_path).relative_to(out_path.parent).as_posix()
            except ValueError:
                image_rel = Path(image_path).as_posix()
        cards.append(
            """
<section class="card">
  <div class="card-head">
    <div>
      <div class="case-id">{case_id}</div>
      <div class="module">{module_zh} / {submodule_zh}</div>
    </div>
    <div class="meta">
      <span>{manual_status}</span>
      <span>{tokens} tok</span>
      <span>{latency}s</span>
    </div>
  </div>
  <div class="body">
    <div class="image-panel">
      {image_html}
    </div>
    <div class="text-panel">
      <div class="field">
        <h4>自动转录</h4>
        <div class="md">{auto_preview}</div>
      </div>
      <div class="field">
        <h4>人工金标</h4>
        <div class="md">{gold_preview}</div>
      </div>
      <div class="field compact">
        <h4>人工审查记录</h4>
        <pre>status: {manual_status}\nsource_issue: {source_issue}\nnote: {manual_review_note}</pre>
      </div>
    </div>
  </div>
</section>
""".format(
                case_id=html.escape(str(row.get("case_id", ""))),
                module_zh=html.escape(str(row.get("module_zh", ""))),
                submodule_zh=html.escape(str(row.get("submodule_zh", ""))),
                manual_status=html.escape(str(row.get("manual_status", ""))),
                tokens=html.escape(str(row.get("usage_total_tokens", ""))),
                latency=html.escape(str(row.get("latency_seconds", ""))),
                image_html=(
                    f'<img src="{html.escape(image_rel)}" loading="lazy" />'
                    if image_rel
                    else '<div class="missing">image missing</div>'
                ),
                auto_preview=html.escape(
                    build_preview_md(
                        str(row.get("auto_stem_text_md", "") or ""),
                        str(row.get("auto_answer_text_md", "") or ""),
                        str(row.get("auto_analysis_text_md", "") or ""),
                    )
                ),
                gold_preview=html.escape(str(row.get("gold_preview_md", "") or "")),
                source_issue=html.escape(str(row.get("source_issue", "") or "")),
                manual_review_note=html.escape(str(row.get("manual_review_note", "") or "")),
            )
        )

    doc = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>200题人工金标工作簿</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" />
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f7fb; color: #172033; }}
    header {{ position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid #dce3ef; padding: 16px 20px; }}
    h1 {{ margin: 0 0 4px; font-size: 22px; }}
    .summary {{ color: #5c667a; font-size: 14px; }}
    main {{ padding: 18px; display: grid; gap: 16px; }}
    .card {{ background: #fff; border: 1px solid #dce3ef; border-radius: 12px; overflow: hidden; }}
    .card-head {{ display: flex; justify-content: space-between; gap: 16px; padding: 14px 16px; background: #eef4ff; }}
    .case-id {{ font-weight: 700; font-size: 16px; color: #173f7a; }}
    .module {{ color: #5c667a; font-size: 13px; margin-top: 4px; }}
    .meta {{ display: flex; gap: 12px; align-items: center; color: #42516d; font-size: 13px; }}
    .body {{ display: grid; grid-template-columns: minmax(320px, 42%) minmax(420px, 58%); gap: 16px; padding: 16px; }}
    .image-panel img {{ width: 100%; border: 1px solid #e5ebf4; border-radius: 8px; background: #fff; }}
    .missing {{ border: 1px dashed #d1d8e5; border-radius: 8px; min-height: 240px; display: grid; place-items: center; color: #7a869d; }}
    .text-panel {{ display: grid; gap: 12px; }}
    .field {{ border: 1px solid #e5ebf4; border-radius: 8px; overflow: hidden; }}
    .field h4 {{ margin: 0; padding: 8px 10px; font-size: 13px; background: #f8faff; border-bottom: 1px solid #e5ebf4; }}
    .field .md {{ margin: 0; padding: 10px; white-space: pre-wrap; word-break: break-word; font-family: Consolas, "Courier New", monospace; font-size: 12px; line-height: 1.7; }}
    .compact pre {{ font-size: 11px; }}
    .katex {{ font-size: 1.08em; }}
    @media (max-width: 1200px) {{
      .body {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>200题人工金标工作簿</h1>
    <div class="summary">基于自动转录底稿初始化，后续由人工逐题观察图片校正。当前总题数：__COUNT__。</div>
  </header>
  <main>
    __CARDS__
  </main>
  <script>
    document.addEventListener("DOMContentLoaded", function () {
      renderMathInElement(document.body, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false }
        ],
        throwOnError: false
      });
    });
  </script>
</body>
</html>
"""
    doc = doc.replace("__COUNT__", str(len(rows))).replace("__CARDS__", "".join(cards))
    out_path.write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-json", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    review_json = Path(args.review_json).resolve()
    out_dir = Path(args.out_dir).resolve()
    ensure_dir(out_dir)

    review_rows = read_json(review_json)
    rows = [make_gold_row(row) for row in review_rows]

    json_path = out_dir / "manual_gold_workbook.json"
    csv_path = out_dir / "manual_gold_workbook.csv"
    html_path = out_dir / "manual_gold_workbook.html"
    summary_path = out_dir / "manual_gold_workbook_summary.json"

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(rows, csv_path)
    build_html(rows, html_path)

    summary = {
        "row_count": len(rows),
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "review_json": str(review_json),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
