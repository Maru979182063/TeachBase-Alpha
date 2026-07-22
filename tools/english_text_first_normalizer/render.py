from __future__ import annotations

import html
import json
from typing import Any


FIELD_LABELS = [
    ("stem_refs", "stem（题干/任务）"),
    ("option_refs", "options（选项）"),
    ("passage_refs", "passage（文章/阅读材料）"),
    ("answer_refs", "answer（答案）"),
    ("analysis_refs", "analysis（解析）"),
    ("translation_refs", "translation（翻译）"),
    ("context_refs", "context（上下文/知识背景）"),
    ("instruction_refs", "instruction（操作指令）"),
    ("example_refs", "example（例题/示例）"),
    ("visual_refs", "visual（必须保留的视觉结构）"),
    ("writing_surface_refs", "writing_surface（作答区/作文纸）"),
    ("rubric_refs", "rubric（评分标准）"),
    ("other_evidence_refs", "other（其他证据）"),
]


def render_review(summary: dict[str, Any], records: list[dict[str, Any]], block_index: dict[str, dict[str, Any]]) -> str:
    rows = []
    for record in records:
        normalized = record["normalized_record"]
        field_refs = normalized.get("field_refs", {})
        ref_bits = []
        for key, label in FIELD_LABELS:
            refs = field_refs.get(key) or []
            if refs:
                samples = []
                for ref in refs[:3]:
                    text = str(block_index.get(ref, {}).get("text", "")).replace("\n", " ")[:140]
                    samples.append(f"<li><code>{html.escape(ref)}</code>: {html.escape(text)}</li>")
                ref_bits.append(f"<div><b>{label}</b><ul>{''.join(samples)}</ul></div>")
        rows.append(
            "<tr>"
            f"<td>{html.escape(record['document_group_id'])}</td>"
            f"<td>{html.escape(normalized.get('record_kind', ''))}</td>"
            f"<td>fallback={html.escape(str(record.get('used_fallback', False)))}<br>protocol_repair={html.escape(str(record.get('used_protocol_repair', False)))}</td>"
            f"<td><pre>{html.escape(json.dumps(normalized.get('field_status', {}), ensure_ascii=False, indent=2))}</pre></td>"
            f"<td>{''.join(ref_bits)}</td>"
            f"<td><pre>{html.escape(json.dumps(record.get('validation', {}), ensure_ascii=False, indent=2))}</pre></td>"
            "</tr>"
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>English Group Normalizer Review</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.5}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;vertical-align:top}"
        "th{background:#f4f4f4}code{background:#eee;padding:1px 4px;border-radius:3px}"
        "pre{white-space:pre-wrap;max-width:420px}</style>"
        "<h1>English Group Normalizer Review</h1>"
        f"<p>attempted={summary['groups_attempted']}, parsed={summary['groups_parsed']}, "
        f"valid={summary['groups_valid']}, fallback={summary['groups_fallback']}</p>"
        "<p>Normalizer only classifies block refs into fields. It does not create QuestionPacket or decide release.</p>"
        "<table><thead><tr><th>group</th><th>record_kind（开放类型）</th><th>repair/fallback</th>"
        "<th>field_status（字段状态）</th><th>field_refs（字段引用）</th><th>validation</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
