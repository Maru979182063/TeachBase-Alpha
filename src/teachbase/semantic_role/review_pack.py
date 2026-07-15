from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json, write_text


def write_review_pack(out_dir: Path, cases: list[dict[str, Any]], predictions: list[dict[str, Any]], bad_cases: list[dict[str, Any]]) -> None:
    review_dir = out_dir / "review_pack"
    cases_dir = review_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    pred_by_id = {str(row.get("case_id")): row for row in predictions}
    bad_ids = {str(row.get("case_id")) for row in bad_cases}
    rows: list[str] = []
    for case in sorted(cases, key=lambda row: (str(row.get("case_id")) not in bad_ids, str(row.get("case_id")))):
        pred = pred_by_id.get(str(case.get("case_id")), {})
        case_html = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>"
            + html.escape(str(case.get("case_id")))
            + "</title></head><body>"
            + f"<h1>{html.escape(str(case.get('case_id')))}</h1>"
            + "<dl>"
            + f"<dt>subject</dt><dd>{html.escape(str(case.get('subject')))}</dd>"
            + f"<dt>page_range</dt><dd>{html.escape(str(case.get('page_range')))}</dd>"
            + f"<dt>current_node_type</dt><dd>{html.escape(str(case.get('current_node_type')))}</dd>"
            + f"<dt>current_review_status</dt><dd>{html.escape(str(case.get('current_review_status')))}</dd>"
            + f"<dt>source_text_stub</dt><dd>{html.escape(str(case.get('source_text_stub')))}</dd>"
            + f"<dt>gold_role</dt><dd>{html.escape(str(case.get('expected_semantic_role')))}</dd>"
            + f"<dt>predicted_role</dt><dd>{html.escape(str(pred.get('semantic_role')))}</dd>"
            + f"<dt>gold_route</dt><dd>{html.escape(str(case.get('expected_route_candidate')))}</dd>"
            + f"<dt>predicted_route</dt><dd>{html.escape(str(pred.get('route_candidate')))}</dd>"
            + f"<dt>gold_review</dt><dd>{html.escape(str(case.get('expected_needs_role_review')))}</dd>"
            + f"<dt>predicted_review</dt><dd>{html.escape(str(pred.get('needs_role_review')))}</dd>"
            + f"<dt>confidence</dt><dd>{html.escape(str(pred.get('confidence')))}</dd>"
            + f"<dt>evidence</dt><dd>{html.escape(str(pred.get('evidence')))}</dd>"
            + "<dt>manual_decision</dt><dd>pending</dd>"
            + "</dl></body></html>"
        )
        case_path = cases_dir / f"{case.get('case_id')}.html"
        write_text(case_path, case_html)
        rows.append(
            "<tr>"
            f"<td><a href=\"cases/{html.escape(case_path.name)}\">{html.escape(str(case.get('case_id')))}</a></td>"
            f"<td>{html.escape(str(case.get('gold_status')))}</td>"
            f"<td>{html.escape(str(case.get('subject')))}</td>"
            f"<td>{html.escape(str(case.get('expected_semantic_role')))}</td>"
            f"<td>{html.escape(str(pred.get('semantic_role')))}</td>"
            f"<td>{html.escape(str(pred.get('confidence')))}</td>"
            "</tr>"
        )
    index = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Semantic Role Review Pack</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif}td,th{border:1px solid #ddd;padding:6px}"
        "table{border-collapse:collapse;width:100%;font-size:12px}</style></head><body>"
        "<table><thead><tr><th>case</th><th>gold</th><th>subject</th><th>expected role</th><th>predicted role</th><th>confidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )
    write_text(review_dir / "index.html", index)
    write_json(review_dir / "review_decisions.json", {"schema_version": "semantic_role_review_decisions_v0.1", "decisions": []})
