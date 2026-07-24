from __future__ import annotations

import argparse
import html
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text
from english_text_first_normalizer.evidence_text import (
    blank_run_count,
    line_supported_by_source,
    meaningful_content_lines,
    normalize_evidence_text,
    unsupported_lines,
)


USER_FIELDS = [
    "passage",
    "stem",
    "options",
    "answer",
    "analysis",
    "translation",
    "context",
    "examples",
    "rubric",
]


def field_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                label = str(item.get("label") or "").strip()
                text = str(item.get("text") or "").strip()
                parts.append(f"{label}. {text}".strip(". "))
            else:
                parts.append(str(item or ""))
        return "\n".join(part for part in parts if part.strip())
    if isinstance(value, dict):
        return "\n".join(str(item or "") for item in value.values())
    return str(value or "")


def packet_source_text(packet: dict[str, Any]) -> str:
    parts: list[str] = []
    for value in (packet.get("content") or {}).values():
        if isinstance(value, dict):
            parts.append(str(value.get("text") or ""))
        else:
            parts.append(str(value or ""))
    parts.append(str(packet.get("final_markdown") or ""))
    return "\n".join(part for part in parts if part.strip())


def refined_field_texts(refined: dict[str, Any]) -> dict[str, str]:
    question = refined.get("standard_question") or {}
    fields = {field: field_to_text(question.get(field)) for field in USER_FIELDS}
    fields["final_markdown"] = str(refined.get("final_markdown") or "")
    return fields


def line_status(line: str, source_norm: str) -> str:
    norm = normalize_evidence_text(line)
    if not norm:
        return "empty"
    if line_supported_by_source(source_norm, line):
        return "source_supported"
    probes = [norm]
    if len(norm) > 100:
        probes = [norm[:80], norm[-80:]]
    if any(probe and probe in source_norm for probe in probes):
        return "partially_source_supported"
    return "not_in_5b_input"


def audit_one(packet: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    source_text = packet_source_text(packet)
    source_norm = normalize_evidence_text(source_text)
    field_reports: list[dict[str, Any]] = []
    unsupported_total: list[dict[str, str]] = []
    for field, text in refined_field_texts(refined).items():
        lines = meaningful_content_lines(text, min_normalized_chars=6)
        line_reports = [{"text": line, "status": line_status(line, source_norm)} for line in lines]
        unsupported = [item for item in line_reports if item["status"] == "not_in_5b_input"]
        for item in unsupported[:5]:
            unsupported_total.append({"field": field, "text": item["text"]})
        field_reports.append(
            {
                "field": field,
                "line_count": len(line_reports),
                "unsupported_count": len(unsupported),
                "lines": line_reports,
            }
        )
    source_blank_runs = blank_run_count(source_text)
    output_text = "\n".join(refined_field_texts(refined).values())
    output_blank_runs = blank_run_count(output_text)
    unsupported_examples = unsupported_lines(source_text=source_text, output_text=output_text, max_examples=12)
    divergence_status = "PASS"
    if unsupported_total:
        divergence_status = "FAIL_UNSUPPORTED_TEXT"
    elif source_blank_runs and output_blank_runs < source_blank_runs:
        divergence_status = "WARN_SURFACE_BLANK_LOSS"
    return {
        "source_packet_id": refined.get("source_packet_id") or packet.get("packet_id"),
        "source_group_id": refined.get("source_group_id") or packet.get("source_group_id"),
        "packet_family": refined.get("packet_family") or packet.get("packet_family"),
        "refine_status": refined.get("refine_status"),
        "divergence_status": divergence_status,
        "unsupported_examples": unsupported_examples,
        "unsupported_total_count": len(unsupported_total),
        "unsupported_by_field": unsupported_total,
        "source_blank_runs": source_blank_runs,
        "output_blank_runs": output_blank_runs,
        "field_reports": field_reports,
    }


def load_packet_pairs(run_dir: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    packets_dir = run_dir / "packets"
    for packet_dir in sorted(packets_dir.glob("*")):
        input_path = packet_dir / "input_packet_candidate.json"
        refined_path = packet_dir / "refined_question_packet.json"
        if input_path.exists() and refined_path.exists():
            pairs.append((read_json(input_path), read_json(refined_path)))
    if pairs:
        return pairs

    payload_path = run_dir / "refined_question_packets.json"
    if not payload_path.exists():
        raise FileNotFoundError(f"No packets directory or refined_question_packets.json found under {run_dir}")
    raise FileNotFoundError(
        "This audit needs each packet's input_packet_candidate.json. "
        f"Found {payload_path}, but no packet input files."
    )


def render_html(report: dict[str, Any]) -> str:
    cards = []
    for item in report["records"]:
        fields = []
        for field in item["field_reports"]:
            bad_lines = [line for line in field["lines"] if line["status"] == "not_in_5b_input"]
            if not bad_lines:
                continue
            bad_html = "".join(
                f"<li><code>{html.escape(line['status'])}</code> {html.escape(line['text'])}</li>"
                for line in bad_lines[:8]
            )
            fields.append(f"<h4>{html.escape(field['field'])}</h4><ul>{bad_html}</ul>")
        fields_html = "".join(fields) or "<p class='ok'>No unsupported field lines detected.</p>"
        cards.append(
            f"""
<section class="card {html.escape(item['divergence_status'])}">
  <h2>{html.escape(str(item['source_group_id']))} / {html.escape(str(item['source_packet_id']))}</h2>
  <p><b>family</b>: {html.escape(str(item.get('packet_family') or ''))}
     <b>refine_status</b>: {html.escape(str(item.get('refine_status') or ''))}
     <b>divergence</b>: {html.escape(str(item.get('divergence_status') or ''))}</p>
  <p><b>blank runs</b>: source={item['source_blank_runs']} output={item['output_blank_runs']}</p>
  {fields_html}
</section>
"""
        )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Node5b Divergence Audit</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #172033; }}
.summary {{ padding: 12px 16px; background: #f4f7fb; border: 1px solid #d8e0eb; margin-bottom: 18px; }}
.card {{ border: 1px solid #d9e0ea; padding: 14px 16px; margin: 14px 0; border-radius: 6px; }}
.PASS {{ border-left: 6px solid #2d9d78; }}
.WARN_SURFACE_BLANK_LOSS {{ border-left: 6px solid #d59621; }}
.FAIL_UNSUPPORTED_TEXT {{ border-left: 6px solid #c93f3f; }}
code {{ background: #eef1f5; padding: 1px 4px; border-radius: 4px; }}
li {{ margin: 6px 0; }}
.ok {{ color: #2d725c; }}
</style>
</head>
<body>
<h1>Node5b Divergence Audit</h1>
<div class="summary">
  <p>generated_at={html.escape(report['generated_at'])}</p>
  <p>records={report['summary']['record_count']} pass={report['summary']['pass_count']} warn={report['summary']['warn_count']} fail={report['summary']['fail_count']}</p>
</div>
{''.join(cards)}
</body>
</html>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = workspace_path(args.node5b_run_dir)
    out_dir = workspace_path(args.out_dir) if args.out_dir else run_dir / "divergence_audit"
    records = [audit_one(packet, refined) for packet, refined in load_packet_pairs(run_dir)]
    summary = {
        "record_count": len(records),
        "pass_count": sum(1 for item in records if item["divergence_status"] == "PASS"),
        "warn_count": sum(1 for item in records if item["divergence_status"].startswith("WARN")),
        "fail_count": sum(1 for item in records if item["divergence_status"].startswith("FAIL")),
    }
    report = {
        "schema": "english_text_first_5b_divergence_audit_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node5b_run_dir": rel_workspace(run_dir),
        "summary": summary,
        "records": records,
    }
    write_json(out_dir / "5b_divergence_audit.json", report)
    write_text(out_dir / "5b_divergence_audit.html", render_html(report))
    write_json(
        out_dir / "run_summary.json",
        {
            "schema": "english_text_first_5b_divergence_audit.run_summary",
            "generated_at": report["generated_at"],
            "node5b_run_dir": rel_workspace(run_dir),
            "out_dir": rel_workspace(out_dir),
            "audit_json": rel_workspace(out_dir / "5b_divergence_audit.json"),
            "audit_html": rel_workspace(out_dir / "5b_divergence_audit.html"),
            **summary,
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node5b-run-dir", required=True)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()
    report = run(args)
    print(report["summary"])


if __name__ == "__main__":
    main()
