from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_storage_key(storage_key: str) -> Path:
    value = str(storage_key or "").replace("\\", "/")
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / value


def rel_url(target: Path, base_dir: Path) -> str:
    return Path(target).resolve().relative_to(base_dir.resolve()).as_posix()


def safe_rel_url(target: Path, base_dir: Path) -> str:
    try:
        return rel_url(target, base_dir)
    except Exception:
        return Path(target).as_posix()


def asset_map(question: dict[str, Any], out_dir: Path) -> dict[str, dict[str, str]]:
    qvs = question.get("question_visual_structure") if isinstance(question.get("question_visual_structure"), dict) else {}
    assets = {}
    for asset in qvs.get("visual_assets", []) or []:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id") or "").strip()
        storage_key = str(asset.get("storage_key") or "").strip()
        if not asset_id:
            continue
        file_path = resolve_storage_key(storage_key)
        assets[asset_id] = {
            "asset_id": asset_id,
            "url": safe_rel_url(file_path, out_dir),
            "storage_key": storage_key,
            "width_px": str(asset.get("width_px") or ""),
            "height_px": str(asset.get("height_px") or ""),
            "paragraph_index": str((asset.get("docx_anchor") or {}).get("paragraph_index") or ""),
            "placement_scope": str(asset.get("placement_scope") or ""),
            "asset_role": str(asset.get("asset_role") or ""),
        }
    return assets


def inline_format(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def render_condition_group(block: str) -> str:
    lines = [line.strip() for line in block.strip().splitlines()]
    header = lines[0] if lines else ":::condition-group"
    source_match = re.search(r"source=([A-Za-z0-9._:-]+)", header)
    source = source_match.group(1) if source_match else ""
    items = []
    for line in lines[1:]:
        if line.startswith(":::"):
            continue
        if line.startswith("-"):
            items.append(line[1:].strip())
    item_html = "".join(f"<li>{inline_format(item)}</li>" for item in items)
    source_html = f"<span class=\"cg-source\">{html.escape(source)}</span>" if source else ""
    return f"<div class=\"condition-group\"><div class=\"cg-title\">condition_group {source_html}</div><ul>{item_html}</ul></div>"


def markdown_to_html(markdown: str, assets: dict[str, dict[str, str]]) -> str:
    text = str(markdown or "").replace("\r\n", "\n")
    parts: list[str] = []
    pos = 0
    pattern = re.compile(r":::condition-group[\s\S]*?:::", re.MULTILINE)
    for match in pattern.finditer(text):
        if match.start() > pos:
            parts.append(render_plain_markdown(text[pos : match.start()], assets))
        parts.append(render_condition_group(match.group(0)))
        pos = match.end()
    if pos < len(text):
        parts.append(render_plain_markdown(text[pos:], assets))
    return "\n".join(part for part in parts if part.strip())


def render_plain_markdown(text: str, assets: dict[str, dict[str, str]]) -> str:
    chunks = []
    for raw_para in re.split(r"\n{2,}", text):
        para = raw_para.strip()
        if not para:
            continue
        image_only = re.fullmatch(r"!\[([^\]]*)\]\(asset://([^)]+)\)", para)
        if image_only:
            alt, asset_id = image_only.group(1), image_only.group(2)
            chunks.append(render_image(asset_id, alt, assets))
            continue
        rendered = []
        last = 0
        for match in re.finditer(r"!\[([^\]]*)\]\(asset://([^)]+)\)", para):
            if match.start() > last:
                rendered.append(inline_format(para[last : match.start()]))
            rendered.append(render_image(match.group(2), match.group(1), assets))
            last = match.end()
        if last < len(para):
            rendered.append(inline_format(para[last:]))
        chunks.append(f"<p>{''.join(rendered)}</p>")
    return "\n".join(chunks)


def render_image(asset_id: str, alt: str, assets: dict[str, dict[str, str]]) -> str:
    asset = assets.get(asset_id)
    if not asset:
        return f"<span class=\"missing-asset\">missing asset://{html.escape(asset_id)}</span>"
    meta = " · ".join(
        item
        for item in [
            asset.get("storage_key", ""),
            f"p{asset.get('paragraph_index')}" if asset.get("paragraph_index") else "",
            f"{asset.get('width_px')}x{asset.get('height_px')}" if asset.get("width_px") and asset.get("height_px") else "",
        ]
        if item
    )
    return (
        "<figure class=\"native-figure\">"
        f"<img src=\"{html.escape(asset['url'])}\" alt=\"{html.escape(alt or asset_id)}\" loading=\"lazy\">"
        f"<figcaption>{html.escape(asset_id)}<span>{html.escape(meta)}</span></figcaption>"
        "</figure>"
    )


def render_question_card(question: dict[str, Any], index: int, out_dir: Path) -> str:
    qid = str(question.get("question_id") or question.get("question_uid") or f"q{index:03d}")
    title = str(question.get("stem_text_md") or "").splitlines()[0][:120]
    assets = asset_map(question, out_dir)
    qvs = question.get("question_visual_structure") if isinstance(question.get("question_visual_structure"), dict) else {}
    content_blocks = qvs.get("content_blocks", []) if isinstance(qvs.get("content_blocks"), list) else []
    condition_count = len([b for b in content_blocks if isinstance(b, dict) and b.get("block_type") == "condition_group"])
    image_count = len(assets)
    gating = qvs.get("gating") if isinstance(qvs.get("gating"), dict) else {}
    status = str(gating.get("release_status") or "unknown")
    body = markdown_to_html(question.get("display_markdown") or qvs.get("legacy_stem_md") or "", assets)
    anchor_rows = []
    docx_native = (question.get("source_refs_json") or {}).get("docx_native", {}) if isinstance(question.get("source_refs_json"), dict) else {}
    for anchor in docx_native.get("image_anchors", []) or []:
        if not isinstance(anchor, dict):
            continue
        anchor_rows.append(
            "<tr>"
            f"<td>{html.escape(str(anchor.get('image_ref_id') or ''))}</td>"
            f"<td>{html.escape(str(anchor.get('asset_id') or ''))}</td>"
            f"<td>{html.escape(str(anchor.get('field') or ''))}</td>"
            f"<td>{html.escape(str(anchor.get('paragraph_index') or ''))}</td>"
            f"<td>{html.escape(str(anchor.get('mode') or ''))}</td>"
            "</tr>"
        )
    anchors_html = ""
    if anchor_rows:
        anchors_html = (
            "<details class=\"anchors\"><summary>图片插入点</summary>"
            "<table><thead><tr><th>image_ref</th><th>asset</th><th>field</th><th>paragraph</th><th>mode</th></tr></thead>"
            f"<tbody>{''.join(anchor_rows)}</tbody></table></details>"
        )
    return f"""
<article class="question-card" id="{html.escape(qid)}">
  <header>
    <div>
      <h2>{html.escape(qid)}</h2>
      <p>{html.escape(title)}</p>
    </div>
    <div class="badges">
      <span class="badge status-{html.escape(status)}">{html.escape(status)}</span>
      <span class="badge">{image_count} images</span>
      <span class="badge">{condition_count} condition_groups</span>
    </div>
  </header>
  <section class="question-body">{body}</section>
  {anchors_html}
</article>
"""


def build_html(manifest: dict[str, Any], out_dir: Path) -> str:
    questions = manifest.get("questions", []) if isinstance(manifest.get("questions"), list) else []
    cards = [render_question_card(question, index + 1, out_dir) for index, question in enumerate(questions)]
    nav = "\n".join(
        f"<a href=\"#{html.escape(str(q.get('question_id') or q.get('question_uid') or ''))}\">{html.escape(str(q.get('question_id') or q.get('question_uid') or ''))}</a>"
        for q in questions
        if isinstance(q, dict)
    )
    total_images = sum(
        len(((q.get("question_visual_structure") or {}).get("visual_assets") or []))
        for q in questions
        if isinstance(q, dict)
    )
    total_conditions = sum(
        len([b for b in ((q.get("question_visual_structure") or {}).get("content_blocks") or []) if isinstance(b, dict) and b.get("block_type") == "condition_group"])
        for q in questions
        if isinstance(q, dict)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DOCX Native Backend Preview</title>
  <script>
    window.MathJax = {{
      tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] }},
      svg: {{ fontCache: 'global' }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d2430;
      --muted: #637083;
      --line: #dce2ea;
      --accent: #2563eb;
      --review: #b45309;
      --ok: #047857;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    .layout {{ display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 100vh; }}
    aside {{ position: sticky; top: 0; height: 100vh; overflow: auto; border-right: 1px solid var(--line); background: #fff; padding: 18px; }}
    aside h1 {{ font-size: 18px; line-height: 1.25; margin: 0 0 10px; }}
    .stats {{ color: var(--muted); font-size: 13px; line-height: 1.7; margin-bottom: 16px; }}
    nav {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }}
    nav a {{ color: var(--accent); text-decoration: none; font-size: 13px; padding: 5px 6px; border: 1px solid var(--line); border-radius: 6px; text-align: center; background: #fbfdff; }}
    main {{ padding: 24px; max-width: 1080px; width: 100%; }}
    .question-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 20px 22px; margin: 0 0 18px; box-shadow: 0 1px 2px rgba(16, 24, 40, .04); }}
    .question-card header {{ display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; border-bottom: 1px solid var(--line); padding-bottom: 12px; margin-bottom: 16px; }}
    h2 {{ font-size: 18px; margin: 0 0 6px; }}
    header p {{ margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .badges {{ display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; min-width: 220px; }}
    .badge {{ border: 1px solid var(--line); border-radius: 999px; color: var(--muted); padding: 4px 8px; font-size: 12px; white-space: nowrap; }}
    .status-review {{ color: var(--review); border-color: #f3c77c; background: #fff7ed; }}
    .status-allow_preview {{ color: var(--ok); border-color: #9ad8bd; background: #ecfdf5; }}
    .question-body {{ font-size: 16px; line-height: 1.9; }}
    .question-body p {{ margin: 0 0 12px; }}
    .native-figure {{ display: inline-block; margin: 10px 0 14px; max-width: 100%; vertical-align: top; }}
    .native-figure img {{ display: block; max-width: min(100%, 520px); height: auto; border: 1px solid var(--line); background: white; }}
    .native-figure figcaption {{ font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.5; }}
    .native-figure figcaption span {{ display: block; overflow-wrap: anywhere; }}
    .condition-group {{ border-left: 4px solid #22c55e; background: #f0fdf4; padding: 10px 12px; margin: 12px 0 14px; }}
    .cg-title {{ color: #166534; font-size: 12px; font-weight: 700; margin-bottom: 6px; }}
    .cg-source {{ color: #64748b; font-weight: 500; margin-left: 8px; }}
    .condition-group ul {{ margin: 0; padding-left: 22px; }}
    .condition-group li {{ margin: 4px 0; }}
    details.anchors {{ margin-top: 14px; color: var(--muted); font-size: 13px; }}
    details table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
    th, td {{ border: 1px solid var(--line); padding: 6px 8px; text-align: left; }}
    th {{ background: #f8fafc; color: #475569; }}
    .missing-asset {{ color: #be123c; font-weight: 700; }}
    @media (max-width: 860px) {{
      .layout {{ grid-template-columns: 1fr; }}
      aside {{ position: static; height: auto; }}
      main {{ padding: 14px; }}
      .question-card header {{ display: block; }}
      .badges {{ justify-content: flex-start; margin-top: 10px; min-width: 0; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <h1>DOCX Native Backend Preview</h1>
      <div class="stats">
        <div>Questions: {len(questions)}</div>
        <div>Images: {total_images}</div>
        <div>Condition groups: {total_conditions}</div>
        <div>Schema: {html.escape(str((manifest.get('runtime_contract') or {}).get('question_visual_structure_schema') or ''))}</div>
      </div>
      <nav>{nav}</nav>
    </aside>
    <main>
      {''.join(cards)}
    </main>
  </div>
</body>
</html>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = WORKSPACE_ROOT / manifest_path
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = WORKSPACE_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(manifest_path)
    html_text = build_html(manifest, out_dir)
    index_path = out_dir / "index.html"
    index_path.write_text(html_text, encoding="utf-8")
    return {
        "status": "ok",
        "manifest": str(manifest_path),
        "out_dir": str(out_dir),
        "index": str(index_path),
        "question_count": len(manifest.get("questions", []) or []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
