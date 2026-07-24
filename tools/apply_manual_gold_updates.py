from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(rows: list[dict], out_path: Path) -> None:
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    headers = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def build_preview_md(stem: str, answer: str, analysis: str) -> str:
    return "\n\n".join(
        [
            "## 题干",
            (stem or "").strip(),
            "## 答案",
            (answer or "").strip(),
            "## 解析",
            (analysis or "").strip(),
        ]
    ).strip()


def rebuild_html(rows: list[dict], out_path: Path) -> None:
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
    <div class="summary">人工逐题观察并回填的工作簿。当前总题数：__COUNT__。</div>
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
    out_path.write_text(doc.replace("__COUNT__", str(len(rows))).replace("__CARDS__", "".join(cards)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--updates", required=True)
    args = parser.parse_args()

    workbook_path = Path(args.workbook).resolve()
    updates_path = Path(args.updates).resolve()

    rows = read_json(workbook_path)
    updates = read_json(updates_path)
    update_map = {str(item["case_id"]): item for item in updates}

    for row in rows:
        case_id = str(row.get("case_id", ""))
        patch = update_map.get(case_id)
        if not patch:
            continue
        for key, value in patch.items():
            if key == "case_id":
                continue
            row[key] = value
        row["gold_preview_md"] = build_preview_md(
            str(row.get("gold_stem_text_md", "") or ""),
            str(row.get("gold_answer_text_md", "") or ""),
            str(row.get("gold_analysis_text_md", "") or ""),
        )

    workbook_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(rows, workbook_path.with_suffix(".csv"))
    rebuild_html(rows, workbook_path.with_suffix(".html"))
    print(json.dumps({"updated_cases": sorted(update_map.keys()), "workbook": str(workbook_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
