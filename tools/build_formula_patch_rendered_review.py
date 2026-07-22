from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIELD_LABELS = {
    "stem_text_md": "题干",
    "answer_text_md": "答案",
    "analysis_text_md": "解析",
    "handwriting_text_md": "手写/补充",
}


def copy_katex_assets(out_dir: Path) -> str:
    src_dir = ROOT / "runtime" / "html_assets_cache"
    asset_dir = out_dir / "_html_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for name in ("katex_css.css", "katex_js.js", "auto_render_js.js"):
        shutil.copy2(src_dir / name, asset_dir / name)
    return "_html_assets"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_field(name: str, value: str) -> str:
    if not value:
        return ""
    label = FIELD_LABELS.get(name, name)
    return (
        f"<section class=\"field\"><h4>{esc(label)}</h4>"
        f"<div class=\"md\">{esc(value)}</div></section>"
    )


def render_side(title: str, fields: dict[str, str]) -> str:
    preferred = ["stem_text_md", "answer_text_md", "analysis_text_md", "handwriting_text_md"]
    seen = set(preferred)
    names = preferred + [name for name in fields if name not in seen]
    body = "\n".join(render_field(name, fields.get(name, "")) for name in names)
    return f"<section class=\"side\"><h3>{esc(title)}</h3>{body}</section>"


def render_row(row: dict[str, Any]) -> str:
    before_ok = bool(row.get("before_valid"))
    after_ok = bool(row.get("after_valid"))
    state_class = "ok" if after_ok else "bad"
    patch_report = json.dumps(row.get("patch_report", {}), ensure_ascii=False, indent=2)
    before_matches = ", ".join(row.get("before_matches") or [])
    after_matches = ", ".join(row.get("after_matches") or [])
    return f"""
<article>
  <header class="q-head">
    <h2>{esc(row.get("record_id") or row.get("question_id"))}</h2>
    <div class="chips">
      <span class="{ 'ok' if before_ok else 'bad' }">修前 {'OK' if before_ok else 'BAD'}</span>
      <span class="{ state_class }">修后 {'OK' if after_ok else 'BAD'}</span>
      <span>patch {esc(row.get('applied_patch_count', 0))}</span>
    </div>
  </header>
  <div class="matches">
    <div>before matches: {esc(before_matches)}</div>
    <div>after matches: {esc(after_matches)}</div>
  </div>
  <div class="grid">
    {render_side("Before", row.get("fields_before") or {})}
    {render_side("After", row.get("fields_after") or {})}
  </div>
  <details>
    <summary>Patch report</summary>
    <pre>{esc(patch_report)}</pre>
  </details>
</article>
"""


def build(summary_path: Path, output_path: Path) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asset_base = copy_katex_assets(output_path.parent)
    rows = "\n".join(render_row(row) for row in summary.get("rows", []))
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Formula Patch Rendered Review</title>
  <link rel="stylesheet" href="{asset_base}/katex_css.css" />
  <style>
    body {{ margin: 0; background: #f5f7fb; color: #111827; font-family: Arial, "Microsoft YaHei", sans-serif; }}
    main {{ max-width: 1480px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    .summary {{ margin: 0 0 18px; color: #475569; }}
    article {{ background: #fff; border: 1px solid #d8dee8; border-radius: 8px; margin: 16px 0; padding: 16px; }}
    .q-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; border-bottom: 1px solid #e5e7eb; padding-bottom: 10px; }}
    .q-head h2 {{ margin: 0; font-size: 20px; }}
    .chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .chips span {{ border: 1px solid #d1d5db; border-radius: 999px; padding: 4px 10px; font-size: 13px; background: #f8fafc; }}
    .chips .ok {{ border-color: #a7f3d0; background: #ecfdf5; color: #047857; }}
    .chips .bad {{ border-color: #fecaca; background: #fef2f2; color: #b91c1c; }}
    .matches {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; color: #64748b; font-size: 13px; padding: 10px 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }}
    .side {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #ffffff; }}
    .side h3 {{ margin: 0; padding: 10px 12px; background: #f8fafc; border-bottom: 1px solid #e5e7eb; font-size: 16px; }}
    .field {{ border-top: 1px solid #eef2f7; }}
    .field:first-of-type {{ border-top: 0; }}
    .field h4 {{ margin: 0; padding: 8px 12px 0; font-size: 13px; color: #475569; }}
    .md {{ padding: 8px 12px 14px; line-height: 1.72; white-space: pre-wrap; overflow-x: auto; }}
    .katex {{ font-size: 1.05em; }}
    .katex-display {{ margin: .55em 0; overflow-x: auto; overflow-y: hidden; }}
    details {{ margin-top: 12px; }}
    pre {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e5e7eb; padding: 10px; border-radius: 6px; overflow: auto; }}
    @media (max-width: 980px) {{ .grid, .matches {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <h1>Formula Patch Rendered Review</h1>
  <p class="summary">
    questions={esc(summary.get('question_count'))}
    before_invalid={esc(summary.get('before_invalid_count'))}
    after_invalid={esc(summary.get('after_invalid_count'))}
    applied={esc(summary.get('total_applied_patch_count'))}
  </p>
  {rows}
</main>
<script defer src="{asset_base}/katex_js.js"></script>
<script defer src="{asset_base}/auto_render_js.js"></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {{
    if (!window.renderMathInElement) return;
    window.renderMathInElement(document.body, {{
      delimiters: [
        {{left: "$$", right: "$$", display: true}},
        {{left: "$", right: "$", display: false}},
        {{left: "\\\\(", right: "\\\\)", display: false}},
        {{left: "\\\\[", right: "\\\\]", display: true}}
      ],
      throwOnError: false,
      strict: "ignore"
    }});
  }});
</script>
</body>
</html>
"""
    output_path.write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.summary, args.output)


if __name__ == "__main__":
    main()
