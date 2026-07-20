#!/usr/bin/env python3
"""Audit candidate block filtering for English text-first pipeline.

This is a deterministic audit layer over existing Node1b tags. It does not
call a model and does not inspect source text with regexes.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


MAIN_CONTENT_ROLES = {
    "student_task",
    "solution_reference",
    "analysis_explanation",
    "translation",
    "reading_passage",
    "response_surface",
    "visual_structure",
}

CONTEXT_CONTENT_ROLES = {
    "activity_instruction",
    "example",
}

NOISE_CONTENT_ROLES = {
    "navigation",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_run_arg(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError(f"Expected doc_id=run_path, got: {raw}")
    doc_id, path = raw.split("=", 1)
    return doc_id, Path(path)


def merged_blocks_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    tags = {
        item["block_id"]: item
        for item in record.get("parsed_output", {}).get("tags", [])
    }
    merged = []
    for idx, block in enumerate(record.get("input_blocks", [])):
        tag = tags.get(block.get("block_id"), {})
        merged.append(
            {
                "block_ref": f"{record['doc_id']}_p{record['page_number']:03d}_{block.get('block_id')}",
                "doc_id": record["doc_id"],
                "page": record["page_number"],
                "page_local_index": idx + 1,
                "block_id": block.get("block_id", ""),
                "node1a_label": block.get("label", ""),
                "text": block.get("text", ""),
                "bbox_hint": block.get("bbox_hint", ""),
                "is_complete": block.get("is_complete", None),
                "visual_form": tag.get("visual_form", ""),
                "content_role": tag.get("content_role", ""),
                "relation_hint": tag.get("relation_hint", ""),
                "requires_visual_preservation": bool(tag.get("requires_visual_preservation", False)),
                "preservation_reason": tag.get("preservation_reason", ""),
                "tag_confidence": tag.get("confidence", ""),
            }
        )
    return merged


def classify_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    main_indexes = set()
    for i, block in enumerate(blocks):
        role = block["content_role"]
        if role in MAIN_CONTENT_ROLES or block["requires_visual_preservation"]:
            main_indexes.add(i)

    enriched: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        role = block["content_role"]
        reasons: list[str] = []
        tier = "excluded_from_main"

        if role in NOISE_CONTENT_ROLES:
            reasons.append("navigation_or_page_chrome")
        elif i in main_indexes:
            tier = "main_candidate"
            reasons.append("core_question_or_solution_or_visual_role")
        elif role in CONTEXT_CONTENT_ROLES:
            tier = "context_candidate"
            reasons.append("activity_or_example_context")
        elif role == "knowledge_explanation":
            near_main = any(abs(i - j) <= 2 for j in main_indexes)
            introduces_main = (
                block["relation_hint"] == "introduces_following"
                and any(j > i and j - i <= 3 for j in main_indexes)
            )
            if near_main or introduces_main:
                tier = "context_candidate"
                reasons.append("near_core_candidate")
            else:
                reasons.append("knowledge_not_adjacent_to_core_candidate")
        else:
            reasons.append("role_not_selected_for_main_prompt")

        item = dict(block)
        item["composition_candidate_tier"] = tier
        item["candidate_for_composition"] = tier in {"main_candidate", "context_candidate"}
        item["candidate_reason"] = reasons
        enriched.append(item)
    return enriched


def render_html(summary: dict[str, Any], pages: list[dict[str, Any]]) -> str:
    css = """
    body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f7f8fa;color:#1f2937}
    h1{font-size:22px;margin:0 0 12px}
    h2{font-size:18px;margin-top:28px;border-top:1px solid #d7dce2;padding-top:16px}
    .meta,.summary{background:#fff;border:1px solid #d7dce2;border-radius:8px;padding:12px;margin:12px 0}
    table{border-collapse:collapse;width:100%;background:#fff;margin:12px 0}
    th,td{border:1px solid #d7dce2;padding:6px 8px;vertical-align:top;font-size:13px}
    th{background:#eef2f7;text-align:left}
    .main_candidate{background:#e8f7ee}
    .context_candidate{background:#fff8df}
    .excluded_from_main{background:#f5f6f8;color:#4b5563}
    .text{white-space:pre-wrap;max-width:620px}
    code{background:#eef2f7;padding:1px 4px;border-radius:4px}
    """
    out = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Candidate Filter Audit</title>",
        f"<style>{css}</style></head><body>",
        "<h1>Candidate Filter Audit（候选过滤审计）</h1>",
        "<div class='meta'>",
        f"<div>Generated: <code>{html.escape(summary['generated_at'])}</code></div>",
        "<div>说明：本报告只基于 Node1b 已有标签做确定性过滤；不调用模型，不做正文正则，不按样例 ID 特判。未进入主通道的块仍作为证据保留。</div>",
        "</div>",
        "<div class='summary'><pre>",
        html.escape(json.dumps(summary["counts"], ensure_ascii=False, indent=2)),
        "</pre></div>",
    ]

    for page in pages:
        out.append(
            f"<h2>{html.escape(page['doc_id'])} page {page['page']:03d} "
            f"candidate {page['candidate_blocks']}/{page['total_blocks']}</h2>"
        )
        out.append("<table><thead><tr>")
        for head in [
            "ref",
            "tier（候选层级）",
            "label",
            "role（内容角色）",
            "visual（视觉形态）",
            "visual_keep",
            "reason（原因）",
            "text",
        ]:
            out.append(f"<th>{html.escape(head)}</th>")
        out.append("</tr></thead><tbody>")
        for block in page["blocks"]:
            tier = block["composition_candidate_tier"]
            out.append(f"<tr class='{html.escape(tier)}'>")
            cells = [
                block["block_ref"],
                tier,
                block["node1a_label"],
                block["content_role"],
                block["visual_form"],
                str(block["requires_visual_preservation"]),
                ", ".join(block["candidate_reason"]),
                block["text"],
            ]
            for idx, cell in enumerate(cells):
                klass = " class='text'" if idx == len(cells) - 1 else ""
                out.append(f"<td{klass}>{html.escape(str(cell))}</td>")
            out.append("</tr>")
        out.append("</tbody></table>")
    out.append("</body></html>")
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1b-run", action="append", required=True, help="doc_id=run_path")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    out_dir = (
        Path("outputs")
        / "english_text_first_pipeline_v02_spec_20260715"
        / "controlled_runs"
        / args.run_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    counts = Counter()
    role_by_tier: dict[str, Counter] = defaultdict(Counter)
    visual_by_tier: dict[str, Counter] = defaultdict(Counter)

    for raw in args.node1b_run:
        expected_doc_id, run_path = parse_run_arg(raw)
        summary = load_json(run_path / "run_summary.json")
        for record in summary.get("records", []):
            if record.get("doc_id") != expected_doc_id:
                continue
            blocks = classify_blocks(merged_blocks_from_record(record))
            page_counts = Counter(block["composition_candidate_tier"] for block in blocks)
            for block in blocks:
                tier = block["composition_candidate_tier"]
                counts[tier] += 1
                counts["total_blocks"] += 1
                if block["candidate_for_composition"]:
                    counts["candidate_blocks"] += 1
                role_by_tier[tier][block["content_role"]] += 1
                visual_by_tier[tier][block["visual_form"]] += 1

            page_record = {
                "doc_id": expected_doc_id,
                "page": record["page_number"],
                "total_blocks": len(blocks),
                "candidate_blocks": sum(1 for b in blocks if b["candidate_for_composition"]),
                "tier_counts": dict(page_counts),
                "blocks": blocks,
            }
            pages.append(page_record)

    pages.sort(key=lambda item: (item["doc_id"], item["page"]))
    summary_out = {
        "schema": "english_candidate_filter_audit_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": args.run_id,
        "counts": {
            **dict(counts),
            "candidate_ratio": round(
                counts["candidate_blocks"] / counts["total_blocks"], 4
            )
            if counts["total_blocks"]
            else 0,
            "role_by_tier": {k: dict(v) for k, v in role_by_tier.items()},
            "visual_by_tier": {k: dict(v) for k, v in visual_by_tier.items()},
        },
        "filter_contract": {
            "main_candidate": sorted(MAIN_CONTENT_ROLES),
            "context_candidate": sorted(CONTEXT_CONTENT_ROLES),
            "knowledge_explanation": "included only when adjacent to a main candidate by existing block order/relation tags",
            "noise": sorted(NOISE_CONTENT_ROLES),
            "no_text_regex": True,
            "no_sample_id_special_cases": True,
        },
    }

    (out_dir / "candidate_filter_summary.json").write_text(
        json.dumps(summary_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "candidate_filter_pages.json").write_text(
        json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "candidate_filter_review.html").write_text(
        render_html(summary_out, pages), encoding="utf-8"
    )

    print(json.dumps(summary_out, ensure_ascii=False, indent=2))
    print(f"review_html={out_dir / 'candidate_filter_review.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
