from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import fitz

from tools.split_pipeline_v03 import build_legacy_bridge, run_split_v03_for_doc, summarize_nodes, write_json


def parse_pages(spec: str, page_count: int) -> list[int]:
    spec = (spec or "").strip()
    if not spec:
        return list(range(1, min(page_count, 5) + 1))
    pages: set[int] = set()
    for part in spec.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start, end = int(left), int(right)
            if end < start:
                start, end = end, start
            pages.update(range(max(1, start), min(page_count, end) + 1))
        else:
            page = int(part)
            if 1 <= page <= page_count:
                pages.add(page)
    return sorted(pages)


def write_quick_review_html(out_dir: Path, doc_key: str, result: dict, bridge: dict) -> None:
    overlay_dir = out_dir / "debug" / "blocks_overlay" / doc_key
    overlays = sorted(overlay_dir.glob("*.png"))
    node_rows = []
    for node in result["nodes"]:
        roles = sorted({fragment["role"] for fragment in node.get("fragments", [])})
        node_rows.append(
            "<tr>"
            f"<td>{node['node_id']}</td>"
            f"<td>{node['node_type']}</td>"
            f"<td>{node['review_status']}</td>"
            f"<td>{len(node.get('fragments', []))}</td>"
            f"<td>{', '.join(roles)}</td>"
            f"<td><pre>{node.get('text_stub', '')[:800]}</pre></td>"
            "</tr>"
        )
    overlay_imgs = "\n".join(
        f"<figure><img src='{p.relative_to(out_dir).as_posix()}' loading='lazy'><figcaption>{p.name}</figcaption></figure>"
        for p in overlays
    )
    summary = summarize_nodes(result["nodes"])
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>split_v03 quick debug - {doc_key}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f6f7fb;color:#172033;margin:24px}}
.summary,.panel{{background:#fff;border:1px solid #d9e1ef;border-radius:12px;padding:16px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}}
figure{{background:white;border:1px solid #e1e7f0;border-radius:10px;padding:8px;margin:0}}
img{{max-width:100%;display:block;margin:auto}}
figcaption{{font-size:12px;color:#5c6778;margin-top:6px}}
table{{border-collapse:collapse;width:100%;background:white}}
th,td{{border-bottom:1px solid #e5eaf2;padding:8px;text-align:left;vertical-align:top;font-size:13px}}
th{{background:#edf4ff}} pre{{white-space:pre-wrap;margin:0;max-height:180px;overflow:auto}}
</style>
<section class="summary">
<h1>split_v03 quick debug - {doc_key}</h1>
<p>只测试切块/节点，不做题目转录；provider={result.get('provider', 'mock')}，VLM 调用={result.get('actual_vlm_calls', 0)}。</p>
<p>pages: {', '.join(map(str, result['page_numbers']))} | raw_blocks: {len(result['blocks'])} | reading_blocks: {len(result.get('reading_blocks', []))} | nodes: {len(result['nodes'])} | bridge_ready: {len(bridge['questions'])}</p>
<pre>{json.dumps(summary, ensure_ascii=False, indent=2)}</pre>
</section>
<section class="panel"><h2>Block Overlay</h2><div class="grid">{overlay_imgs}</div></section>
<section class="panel"><h2>Semantic Nodes</h2>
<table><thead><tr><th>node_id</th><th>type</th><th>status</th><th>fragments</th><th>roles</th><th>text_stub</th></tr></thead>
<tbody>{''.join(node_rows)}</tbody></table></section>
"""
    (out_dir / "quick_debug_review.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--doc-key", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", default="mock", choices=["mock", "visual"])
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--max-vlm-calls", type=int, default=0)
    args = parser.parse_args()
    if args.provider == "mock" and args.max_vlm_calls != 0:
        raise SystemExit("quick debug must run with --max-vlm-calls 0")
    if args.provider == "visual" and args.max_vlm_calls < 1:
        raise SystemExit("visual quick debug requires --max-vlm-calls >= page count")
    page_count = fitz.open(args.pdf).page_count
    pages = parse_pages(args.pages, page_count)
    if args.provider == "visual" and args.max_vlm_calls < len(pages):
        raise SystemExit(f"visual quick debug needs at least {len(pages)} VLM calls for {len(pages)} pages")
    api_key = os.environ.get("ARK_API_KEY", "").strip()
    if args.provider == "visual" and not api_key:
        raise SystemExit("visual quick debug requires ARK_API_KEY")
    out_dir = Path(args.out)
    result = run_split_v03_for_doc(
        args.pdf,
        args.doc_key,
        pages,
        out_dir,
        provider=args.provider,
        api_key=api_key,
        model=args.model,
        max_vlm_calls=args.max_vlm_calls,
    )
    result["page_numbers"] = pages
    result["provider"] = args.provider
    actual_vlm_calls = 0
    if args.provider == "visual":
        actual_vlm_calls = len(list((out_dir / "debug" / "blocks_overlay" / "visual_provider_raw").glob("*/*.meta.json")))
    result["actual_vlm_calls"] = actual_vlm_calls
    bridge = build_legacy_bridge(result["nodes"], result["crop_records"])
    write_json(out_dir / "quick_debug_result.json", {
        "schema": "split_v03_quick_debug",
        "paid_vlm_used": args.provider == "visual",
        "actual_vlm_calls": actual_vlm_calls,
        "doc_key": args.doc_key,
        "pdf": args.pdf,
        "page_count": page_count,
        "page_numbers": pages,
        "node_summary": summarize_nodes(result["nodes"]),
        "block_count": len(result["blocks"]),
        "reading_block_count": len(result.get("reading_blocks", [])),
        "node_count": len(result["nodes"]),
        "legacy_bridge_ready_count": len(bridge["questions"]),
        "artifacts": [
            str(out_dir / "quick_debug_review.html"),
            str(out_dir / "debug" / "blocks_overlay" / args.doc_key),
            str(out_dir / "docs" / args.doc_key / "semantic_nodes.json"),
            str(out_dir / "docs" / args.doc_key / "blocks.json"),
            str(out_dir / "docs" / args.doc_key / "reading_blocks.json"),
        ],
    })
    write_json(out_dir / "legacy_bridge_questions.json", bridge)
    write_quick_review_html(out_dir, args.doc_key, result, bridge)
    print(json.dumps({
        "out": str(out_dir),
        "review": str(out_dir / "quick_debug_review.html"),
        "doc_key": args.doc_key,
        "pages": pages,
        "blocks": len(result["blocks"]),
        "reading_blocks": len(result.get("reading_blocks", [])),
        "nodes": len(result["nodes"]),
        "ready": len(bridge["questions"]),
        "paid_vlm_used": args.provider == "visual",
        "actual_vlm_calls": actual_vlm_calls,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
