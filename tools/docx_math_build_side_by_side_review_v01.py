from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_OUT_ROOT = Path("outputs/docx_math_side_by_side_review_v0_1")
DEFAULT_BLOCK_STREAM_ROOT = Path("outputs/docx_native_block_tagger_v0_1/block_tagger_accuracy_pilot_20260716_v03")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_pdftoppm() -> str:
    exe_candidate = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe"
    if exe_candidate.exists():
        return str(exe_candidate)
    found = shutil.which("pdftoppm") or shutil.which("pdftoppm.cmd")
    if found:
        return found
    candidate = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm.cmd"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError("pdftoppm was not found on PATH or in the bundled runtime override directory")


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:120] or "doc"


def find_block_stream(doc_id: str, root: Path) -> Path:
    matches = []
    for path in root.rglob("immutable_block_stream.json"):
        payload = read_json(path)
        if payload.get("blocks") and str(path.parent.name) == doc_id:
            matches.append(path)
        elif str(payload.get("source_docx") or "") and doc_id in str(path.parent.name):
            matches.append(path)
    if not matches:
        raise FileNotFoundError(f"no immutable_block_stream.json found for doc_id={doc_id}")
    if len(matches) > 1:
        exact = [path for path in matches if path.parent.name == doc_id]
        if len(exact) == 1:
            return exact[0]
        raise RuntimeError(f"multiple block streams matched doc_id={doc_id}: {matches}")
    return matches[0]


def powershell_quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def export_docx_pages(docx_path: Path, out_dir: Path, *, force: bool = False) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    staged_docx_path = out_dir / "source.docx"
    if force or not staged_docx_path.exists():
        shutil.copy2(docx_path, staged_docx_path)
    pdf_path = out_dir / "original.pdf"
    page_json_path = out_dir / "paragraph_pages.json"
    ps1_path = out_dir / "export_docx_pages.ps1"
    ps1_path.write_text(
        r"""
param(
  [Parameter(Mandatory=$true)][string]$DocxPath,
  [Parameter(Mandatory=$true)][string]$PdfPath,
  [Parameter(Mandatory=$true)][string]$PageJsonPath
)
$ErrorActionPreference = "Stop"
$word = $null
$doc = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $word.DisplayAlerts = 0
  $doc = $word.Documents.Open($DocxPath, $false, $true)
  $doc.ExportAsFixedFormat($PdfPath, 17)
  $items = New-Object System.Collections.Generic.List[object]
  for ($i = 1; $i -le $doc.Paragraphs.Count; $i++) {
    $p = $doc.Paragraphs.Item($i)
    $items.Add([pscustomobject]@{
      paragraph_index = $i - 1
      page = $p.Range.Information(3)
    })
  }
  $items | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PageJsonPath -Encoding UTF8
}
finally {
  if ($doc -ne $null) { $doc.Close($false) | Out-Null }
  if ($word -ne $null) { $word.Quit() | Out-Null }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    if force or not pdf_path.exists() or not page_json_path.exists():
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1_path.resolve()),
                "-DocxPath",
                str(staged_docx_path.resolve()),
                "-PdfPath",
                str(pdf_path.resolve()),
                "-PageJsonPath",
                str(page_json_path.resolve()),
            ],
            check=True,
            text=True,
            encoding="utf-8",
        )
    first_png = out_dir / "page-1.png"
    if force or not first_png.exists():
        for old in out_dir.glob("page-*.png"):
            old.unlink()
        subprocess.run(
            [find_pdftoppm(), "-png", "-r", "144", str(pdf_path.resolve()), str((out_dir / "page").resolve())],
            check=True,
        )
    pages = sorted(out_dir.glob("page-*.png"), key=lambda p: int(re.search(r"-(\d+)\.png$", p.name).group(1)))
    raw_page_map = json.loads(page_json_path.read_text(encoding="utf-8-sig"))
    if isinstance(raw_page_map, dict):
        raw_page_map = [raw_page_map]
    paragraph_pages = {int(item["paragraph_index"]): int(item["page"]) for item in raw_page_map}
    return {
        "pdf": str(pdf_path),
        "page_count": len(pages),
        "paragraph_pages": paragraph_pages,
        "page_images": {idx + 1: page for idx, page in enumerate(pages)},
    }


def packet_block_ids(packet: dict[str, Any], draft_ref_by_group: dict[str, dict[str, Any]] | None = None) -> dict[str, list[str]]:
    source_refs = packet.get("source_refs") or {}
    result: dict[str, list[str]] = {}
    if isinstance(source_refs, dict):
        for key, value in source_refs.items():
            if isinstance(value, list):
                result[key] = [str(item) for item in value if str(item).startswith("b_")]
    fallback = packet.get("source_group_block_ids") or []
    if fallback and not result:
        result["source_group_block_ids"] = [str(item) for item in fallback if str(item).startswith("b_")]
    if not result and draft_ref_by_group:
        group_id = str(packet.get("source_group_id") or "")
        draft_refs = draft_ref_by_group.get(group_id) or {}
        draft_source_refs = draft_refs.get("source_refs")
        if isinstance(draft_source_refs, list):
            result["source_group_block_ids"] = [str(item) for item in draft_source_refs if str(item).startswith("b_")]
        draft_block_ids = draft_refs.get("source_group_block_ids")
        if isinstance(draft_block_ids, list):
            result["source_group_block_ids"] = [str(item) for item in draft_block_ids if str(item).startswith("b_")]
    return result


def choose_pages(refs: dict[str, list[str]], block_by_id: dict[str, dict[str, Any]], paragraph_pages: dict[int, int]) -> dict[str, Any]:
    locating_keys = [
        "stem_refs",
        "subquestion_refs",
        "option_refs",
        "answer_refs",
        "explanation_refs",
        "asset_block_refs",
        "source_group_block_ids",
    ]
    context_keys = ["context_refs", "teaching_note_refs", "other_evidence_refs"]
    locating_pages: list[int] = []
    context_pages: list[int] = []
    block_ranges: list[int] = []

    def add_pages(keys: list[str], target: list[int]) -> None:
        for key in keys:
            for block_id in refs.get(key, []):
                block = block_by_id.get(block_id)
                if not block:
                    continue
                source_order = block.get("source_order")
                if isinstance(source_order, int):
                    block_ranges.append(source_order)
                paragraph_index = block.get("paragraph_index")
                if isinstance(paragraph_index, int) and paragraph_index in paragraph_pages:
                    target.append(paragraph_pages[paragraph_index])

    add_pages(locating_keys, locating_pages)
    add_pages(context_keys, context_pages)
    pages = sorted(set(locating_pages or context_pages))
    if locating_pages:
        primary_page = Counter(locating_pages).most_common(1)[0][0]
    elif context_pages:
        primary_page = Counter(context_pages).most_common(1)[0][0]
    else:
        primary_page = None
    return {
        "primary_page": primary_page,
        "source_pages": pages,
        "context_pages": sorted(set(context_pages)),
        "block_order_min": min(block_ranges) if block_ranges else None,
        "block_order_max": max(block_ranges) if block_ranges else None,
    }


def source_subquestion_labels(draft_ref: dict[str, Any] | None) -> list[str]:
    markdown = ""
    if isinstance(draft_ref, dict):
        fields = draft_ref.get("fields") if isinstance(draft_ref.get("fields"), dict) else {}
        subquestions = fields.get("subquestions") if isinstance(fields.get("subquestions"), dict) else {}
        markdown = str(subquestions.get("markdown") or "")
    labels: list[str] = []
    for line in markdown.splitlines():
        text = line.strip()
        if not text:
            continue
        match = re.match(r"^((?:\(|（)\s*[0-9一二三四五六七八九十]+\s*(?:\)|）)|[①②③④⑤⑥⑦⑧⑨⑩])", text)
        if match:
            labels.append(match.group(1).replace(" ", ""))
    return labels


def markdown_for_packet(packet: dict[str, Any], draft_ref: dict[str, Any] | None = None) -> str:
    q = packet.get("standard_question") or {}
    render = str(q.get("render_markdown") or "").strip()
    if render:
        return render
    parts: list[str] = []
    title = str(q.get("title") or "").strip()
    if title:
        parts.append(title)
    stem = str(q.get("stem_md") or "").strip()
    if stem:
        parts.append(stem)
    subquestions = q.get("subquestions") if isinstance(q.get("subquestions"), list) else []
    source_labels = source_subquestion_labels(draft_ref)
    for sub_index, item in enumerate(subquestions):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        markdown = str(item.get("markdown") or "").strip()
        if not label and len(source_labels) == len(subquestions):
            label = source_labels[sub_index]
        if label and markdown and not markdown.startswith(label):
            parts.append(f"{label}{markdown}" if label.endswith((")", "）", ".")) else f"{label} {markdown}")
        elif markdown or label:
            parts.append(markdown or label)
    options = q.get("options") if isinstance(q.get("options"), list) else []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        markdown = str(option.get("markdown") or "").strip()
        if label or markdown:
            parts.append(f"{label}. {markdown}".strip())
    answer = str(q.get("answer_md") or "").strip()
    if answer:
        parts.append(f"【答案】{answer}")
    explanation = str(q.get("explanation_md") or "").strip()
    if explanation:
        parts.append(f"【解析】{explanation}")
    teaching_note = str(q.get("teaching_note_md") or "").strip()
    if teaching_note:
        parts.append(f"【点睛】{teaching_note}")
    if parts:
        return "\n\n".join(parts)
    return str(q.get("render_markdown") or "").strip()


def copy_assets(run_dir: Path, doc_out_dir: Path) -> dict[str, str]:
    asset_resolution_path = run_dir / "asset_resolution.json"
    if not asset_resolution_path.exists():
        return {}
    payload = read_json(asset_resolution_path)
    asset_local = payload.get("asset_local") or {}
    result: dict[str, str] = {}
    for asset_id, rel in asset_local.items():
        src = run_dir / rel
        if not src.exists():
            continue
        dst = doc_out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        result[str(asset_id)] = rel.replace("\\", "/")
    return result


def replace_asset_urls(markdown: str, asset_rel: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        alt = match.group(1)
        asset_id = match.group(2)
        rel = asset_rel.get(asset_id)
        if not rel:
            return f"[[MISSING_ASSET:{asset_id}]]"
        return f"![{alt}]({rel})"

    markdown = re.sub(r"!\[([^\]]*)\]\(asset://(docx_media_\d+)\)", repl, markdown)
    markdown = re.sub(r"asset://(docx_media_\d+)", r"[[MISSING_ASSET:\1]]", markdown)
    return markdown


def page_image_rel(doc_slug: str, page: int, out_dir: Path) -> str:
    page_dir = out_dir / "docs" / doc_slug / "original_pages"
    for name in [f"page-{page:02d}.png", f"page-{page}.png", f"page-{page:03d}.png"]:
        if (page_dir / name).exists():
            return f"docs/{doc_slug}/original_pages/{name}"
    return f"docs/{doc_slug}/original_pages/page-{page:02d}.png"


def markdown_to_static_html(markdown: str) -> str:
    markdown = markdown.strip()
    if not markdown:
        return '<div class="empty-render">无可渲染内容</div>'
    chunks = re.split(r"\n{2,}", markdown)
    html_parts: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", chunk):
            match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", chunk)
            alt = html.escape(match.group(1))
            src = html.escape(match.group(2))
            html_parts.append(f'<p><img src="{src}" alt="{alt}"></p>')
            continue
        escaped = html.escape(chunk)
        escaped = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}">',
            escaped,
        )
        escaped = re.sub(
            r"\[\[MISSING_ASSET:(docx_media_\d+)\]\]",
            lambda m: f'<span class="missing-asset">未解析图片: asset://{m.group(1)}</span>',
            escaped,
        )
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        escaped = escaped.replace("\n", "<br>")
        html_parts.append(f"<p>{escaped}</p>")
    return "\n".join(html_parts)


def build_doc_review(run_dir: Path, out_dir: Path, block_stream_root: Path, *, doc_index: int, force_render: bool) -> dict[str, Any]:
    packets_payload = read_json(run_dir / "final_packets.json")
    summary = packets_payload.get("summary") or {}
    doc_id = str(summary.get("doc_id") or packets_payload.get("doc_id") or run_dir.name)
    doc_slug = f"doc{doc_index:02d}_{slugify(run_dir.name)}"
    doc_out_dir = out_dir / "docs" / doc_slug
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    block_stream_path = find_block_stream(doc_id, block_stream_root)
    block_stream = read_json(block_stream_path)
    draft_ref_by_group: dict[str, dict[str, Any]] = {}
    input_draft_payload = summary.get("input_draft_payload")
    if input_draft_payload and Path(input_draft_payload).exists():
        draft_payload = read_json(Path(input_draft_payload))
        for item in draft_payload.get("draft_items") or []:
            group_id = str(item.get("source_group_id") or "")
            if group_id:
                draft_ref_by_group[group_id] = item
    source_docx = Path(block_stream.get("source_docx") or "")
    if not source_docx.exists():
        raise FileNotFoundError(f"source DOCX does not exist: {source_docx}")
    block_by_id = {str(block.get("block_id")): block for block in block_stream.get("blocks") or []}

    page_info = export_docx_pages(source_docx, doc_out_dir / "original_pages", force=force_render)
    asset_rel = copy_assets(run_dir, doc_out_dir)
    cards: list[dict[str, Any]] = []
    for idx, packet in enumerate(packets_payload.get("packets") or [], start=1):
        refs = packet_block_ids(packet, draft_ref_by_group)
        page_pick = choose_pages(refs, block_by_id, page_info["paragraph_pages"])
        draft_ref = draft_ref_by_group.get(str(packet.get("source_group_id") or ""))
        markdown = replace_asset_urls(markdown_for_packet(packet, draft_ref), asset_rel)
        cards.append(
            {
                "ordinal": idx,
                "source_group_id": packet.get("source_group_id"),
                "source_draft_id": packet.get("source_draft_id"),
                "refine_status": packet.get("refine_status"),
                "question_type": packet.get("question_type") or (packet.get("standard_question") or {}).get("question_type"),
                "primary_page": page_pick["primary_page"],
                "source_pages": page_pick["source_pages"],
                "context_pages": page_pick["context_pages"],
                "block_order_min": page_pick["block_order_min"],
                "block_order_max": page_pick["block_order_max"],
                "markdown": markdown,
            }
        )
    doc_manifest = {
        "doc_id": doc_id,
        "doc_slug": doc_slug,
        "run_dir": str(run_dir),
        "source_docx": str(source_docx),
        "block_stream": str(block_stream_path),
        "page_count": page_info["page_count"],
        "packet_count": len(cards),
        "cards": cards,
    }
    write_json(doc_out_dir / "side_by_side_doc_manifest.json", doc_manifest)
    return doc_manifest


def relpath(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace("\\", "/")


def render_index(out_dir: Path, manifests: list[dict[str, Any]]) -> None:
    nav = []
    cards_html = []
    for doc in manifests:
        doc_slug = str(doc.get("doc_slug") or slugify(doc["doc_id"]))
        nav.append(f'<a href="#{html.escape(doc_slug)}">{html.escape(doc["doc_id"])} ({doc["packet_count"]})</a>')
        cards_html.append(
            f'<section class="doc" id="{html.escape(doc_slug)}"><h1>{html.escape(doc["doc_id"])}</h1>'
            f'<div class="doc-meta">source: <code>{html.escape(doc["source_docx"])}</code> · '
            f'pages={doc["page_count"]} · packets={doc["packet_count"]}</div>'
        )
        for card in doc["cards"]:
            pages = [p for p in card["source_pages"] if isinstance(p, int)]
            primary = card["primary_page"] if isinstance(card["primary_page"], int) else (pages[0] if pages else 1)
            page_buttons = "".join(
                f'<button type="button" data-img="{html.escape(page_image_rel(doc_slug, p, out_dir))}">p{p}</button>'
                for p in pages
            )
            left_src = html.escape(page_image_rel(doc_slug, primary, out_dir))
            card_markdown = str(card.get("markdown") or "")
            card_markdown = re.sub(r"(!\[[^\]]*\]\()assets/", rf"\1docs/{doc_slug}/assets/", card_markdown)
            rendered_html = markdown_to_static_html(card_markdown)
            cards_html.append(
                f"""
<article class="pair">
  <div class="left">
    <div class="pair-head">
      <b>{html.escape(str(card["source_group_id"]))}</b>
      <span>primary page={html.escape(str(card["primary_page"]))} · pages={html.escape(",".join(map(str, pages)) or "unknown")} · blocks={html.escape(str(card["block_order_min"]))}-{html.escape(str(card["block_order_max"]))}</span>
    </div>
    <div class="thumbs">{page_buttons}</div>
    <img class="page-img" src="{left_src}" alt="original page {html.escape(str(primary))}">
  </div>
  <div class="right">
    <div class="pair-head">
      <b>拆出题目 #{card["ordinal"]}</b>
      <span>draft={html.escape(str(card["source_draft_id"]))} · status={html.escape(str(card["refine_status"]))} · type={html.escape(str(card["question_type"]))}</span>
    </div>
    <div class="render">{rendered_html}</div>
  </div>
</article>
"""
            )
        cards_html.append("</section>")

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>DOCX math side-by-side review</title>
<script>
window.MathJax={{tex:{{inlineMath:[["$","$"],["\\\\(","\\\\)"]],displayMath:[["$$","$$"],["\\\\[","\\\\]"]]}},svg:{{fontCache:"global"}}}};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>
body{{margin:0;background:#e9eef5;color:#111827;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
.top{{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #cbd5e1;padding:12px 18px}}
.top a{{margin-right:14px;color:#2563eb;text-decoration:none}}
.doc{{max-width:1780px;margin:0 auto;padding:20px}}
.doc h1{{font-size:22px;margin:10px 0 4px}}
.doc-meta,.pair-head span{{color:#52627a;font-size:13px}}
.pair{{display:grid;grid-template-columns:minmax(520px,48%) minmax(520px,52%);gap:14px;margin:18px 0;align-items:start}}
.left,.right{{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:12px;min-width:0}}
.left{{position:sticky;top:58px;max-height:calc(100vh - 78px);overflow:auto}}
.pair-head{{display:flex;justify-content:space-between;gap:12px;align-items:baseline;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-bottom:10px}}
.thumbs{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}}
.thumbs button{{border:1px solid #94a3b8;background:#f8fafc;border-radius:5px;padding:2px 8px;cursor:pointer}}
.page-img{{width:100%;height:auto;border:1px solid #d1d5db;background:white}}
.render{{font-size:18px;line-height:1.85}}
.render img{{max-width:760px;height:auto;border:1px solid #cbd5e1;display:block;margin:10px 0}}
.missing-asset{{display:inline-block;border:1px dashed #dc2626;background:#fff1f2;color:#991b1b;border-radius:4px;padding:2px 6px;margin:2px 0}}
.empty-render{{color:#991b1b;background:#fff1f2;border:1px solid #fecaca;border-radius:4px;padding:8px}}
code{{background:#f1f5f9;padding:2px 5px;border-radius:4px}}
@media (max-width:1100px){{.pair{{grid-template-columns:1fr}}.left{{position:static;max-height:none}}}}
</style>
</head>
<body>
<div class="top"><b>DOCX math side-by-side review</b> {' '.join(nav)}</div>
{''.join(cards_html)}
<script>
for (const article of document.querySelectorAll('.pair')) {{
  for (const btn of article.querySelectorAll('.thumbs button')) {{
    btn.addEventListener('click', () => {{
      article.querySelector('.page-img').src = btn.dataset.img;
    }});
  }}
}}
if (window.MathJax) MathJax.typesetPromise();
</script>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_root) / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests = []
    for idx, run_dir in enumerate(args.run_dirs, start=1):
        manifests.append(
            build_doc_review(
                Path(run_dir),
                out_dir,
                Path(args.block_stream_root),
                doc_index=idx,
                force_render=args.force_render,
            )
        )
    render_index(out_dir, manifests)
    summary = {
        "schema": "docx_math_side_by_side_review_v0.1",
        "run_id": args.run_id,
        "output_dir": str(out_dir),
        "index_html": str(out_dir / "index.html"),
        "doc_count": len(manifests),
        "packet_count": sum(doc["packet_count"] for doc in manifests),
        "docs": [
            {
                "doc_id": doc["doc_id"],
                "doc_slug": doc.get("doc_slug"),
                "source_docx": doc["source_docx"],
                "page_count": doc["page_count"],
                "packet_count": doc["packet_count"],
            }
            for doc in manifests
        ],
    }
    write_json(out_dir / "review_package_summary.json", summary)
    if args.zip:
        archive = shutil.make_archive(str(out_dir), "zip", root_dir=out_dir)
        summary["zip_path"] = archive
        write_json(out_dir / "review_package_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a source-page vs refined-question review package.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dirs", nargs="+", required=True)
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--block-stream-root", default=str(DEFAULT_BLOCK_STREAM_ROOT))
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--zip", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
