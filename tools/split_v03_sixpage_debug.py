from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tools.split_pipeline_v03 import build_legacy_bridge, run_split_v03_for_doc, summarize_nodes, write_json


DEFAULT_PAGES = {
    "english": [5, 6],
    "math": [4, 5],
    "biology": [17, 18],
}


def _write_review_html(out_dir: Path, results: dict[str, dict], bridges: dict[str, dict]) -> None:
    cards = []
    for doc_key, result in results.items():
        overlay_dir = out_dir / "debug" / "blocks_overlay" / doc_key
        node_overlay_dir = out_dir / "debug" / "nodes_overlay" / doc_key
        imgs = []
        for path in sorted(overlay_dir.glob("*reading_blocks_overlay.png")) + sorted(node_overlay_dir.glob("*semantic_nodes_overlay.png")):
            imgs.append(f"<figure><img src='{path.relative_to(out_dir).as_posix()}'><figcaption>{path.name}</figcaption></figure>")
        role_counts: dict[str, int] = {}
        for node in result["nodes"]:
            for fragment in node.get("fragments", []):
                role_counts[fragment["role"]] = role_counts.get(fragment["role"], 0) + 1
        cards.append(
            f"""
            <section class="panel">
              <h2>{doc_key}</h2>
              <p>pages: {', '.join(map(str, DEFAULT_PAGES[doc_key]))} |
              raw_blocks: {len(result['blocks'])} |
              reading_blocks: {len(result.get('reading_blocks', []))} |
              nodes: {len(result['nodes'])} |
              bridge_ready: {len(bridges[doc_key]['questions'])}</p>
              <pre>{json.dumps({'summary': summarize_nodes(result['nodes']), 'role_counts': role_counts}, ensure_ascii=False, indent=2)}</pre>
              <div class="grid">{''.join(imgs)}</div>
            </section>
            """
        )
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>split_v03 six-page debug</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f6f7fb;color:#172033;margin:24px}}
.panel{{background:#fff;border:1px solid #d9e1ef;border-radius:12px;padding:16px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}}
figure{{margin:0;border:1px solid #dce4f2;border-radius:10px;background:#fff;padding:8px}}
img{{max-width:100%;display:block;margin:auto}}
figcaption{{font-size:12px;color:#5c6778;margin-top:6px}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px}}
</style>
<h1>split_v03 six-page debug</h1>
<p>Only splitting/debug. No transcription. No paid VLM in mock mode.</p>
{''.join(cards)}
"""
    (out_dir / "sixpage_review.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--english-pdf", required=True)
    parser.add_argument("--math-pdf", required=True)
    parser.add_argument("--biology-pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", default="mock", choices=["mock", "visual"])
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--max-vlm-calls", type=int, default=0)
    args = parser.parse_args()
    base_calls = sum(len(pages) for pages in DEFAULT_PAGES.values()) if args.provider == "visual" else 0
    # Visual split v03 uses one full-page planner call per page. Missing coverage
    # is audited as incomplete instead of auto-splitting the page into tiles.
    max_expected_calls = base_calls if args.provider == "visual" else 0
    if args.provider == "mock" and args.max_vlm_calls != 0:
        raise SystemExit("six-page mock debug must run with max_vlm_calls=0")
    if args.provider == "visual" and args.max_vlm_calls < max_expected_calls:
        raise SystemExit(f"six-page visual debug needs max_vlm_calls >= {max_expected_calls} for coverage-gated visual mode")
    api_key = os.environ.get("ARK_API_KEY", "").strip()
    if args.provider == "visual" and not api_key:
        raise SystemExit("six-page visual debug requires ARK_API_KEY")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfs = {"english": args.english_pdf, "math": args.math_pdf, "biology": args.biology_pdf}
    results: dict[str, dict] = {}
    bridges: dict[str, dict] = {}
    all_nodes = []
    all_blocks = []
    all_reading_blocks = []
    for doc_key, pdf in pdfs.items():
        doc_max_vlm_calls = len(DEFAULT_PAGES[doc_key]) if args.provider == "visual" else 0
        result = run_split_v03_for_doc(
            pdf,
            doc_key,
            DEFAULT_PAGES[doc_key],
            out_dir,
            provider=args.provider,
            api_key=api_key,
            model=args.model,
            max_vlm_calls=doc_max_vlm_calls,
        )
        bridge = build_legacy_bridge(result["nodes"], result["crop_records"])
        results[doc_key] = result
        bridges[doc_key] = bridge
        all_nodes.extend(result["nodes"])
        all_blocks.extend(result["blocks"])
        all_reading_blocks.extend(result["reading_blocks"])
        write_json(out_dir / "docs" / doc_key / "legacy_bridge_questions.json", bridge)

    combined_bridge = {"schema": "legacy_bridge_questions_v0.3", "questions": [q for bridge in bridges.values() for q in bridge["questions"]]}
    actual_vlm_calls = 0
    if args.provider == "visual":
        actual_vlm_calls = len(list((out_dir / "debug" / "blocks_overlay" / "visual_provider_raw").glob("*/*.meta.json")))
    call_count_ok = args.provider != "visual" or actual_vlm_calls == max_expected_calls
    report = {
        "schema": "split_v03_sixpage_debug",
        "verdict": "PASS" if call_count_ok else "FAIL",
        "provider": args.provider,
        "model": args.model if args.provider == "visual" else "",
        "paid_vlm_used": args.provider == "visual",
        "actual_vlm_calls": actual_vlm_calls,
        "max_expected_vlm_calls": max_expected_calls,
        "max_vlm_calls_requested": args.max_vlm_calls,
        "pdfs": pdfs,
        "failure_reasons": [] if call_count_ok else ["actual_vlm_calls_below_expected"],
        "pages": DEFAULT_PAGES,
        "node_summary": summarize_nodes(all_nodes),
        "raw_block_count": len(all_blocks),
        "reading_block_count": len(all_reading_blocks),
        "legacy_bridge_ready_count": len(combined_bridge["questions"]),
        "artifacts": [
            str(out_dir / "sixpage_review.html"),
            str(out_dir / "debug" / "blocks_overlay"),
            str(out_dir / "debug" / "nodes_overlay"),
            str(out_dir / "docs"),
            str(out_dir / "legacy_bridge_questions.json"),
        ],
    }
    write_json(out_dir / "sixpage_report.json", report)
    write_json(out_dir / "legacy_bridge_questions.json", combined_bridge)
    _write_review_html(out_dir, results, bridges)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
