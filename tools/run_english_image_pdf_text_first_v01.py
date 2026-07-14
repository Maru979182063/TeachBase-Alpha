from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import time
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.english_image_pdf_text_first_probe_v01 import (  # noqa: E402
    OcrLine,
    VisualObject,
    detect_visual_objects,
    draw_ocr_overlays,
    parse_pages,
    render_pages,
    run_ocr,
    write_json,
    write_page_text,
)


PIPELINE_SCHEMA = "english_image_pdf_text_first_pipeline_v0.1"
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_ARK_TEXT_ASSEMBLER_MODEL = "doubao-seed-2.0-mini"
DEFAULT_CONFIG_PATH = "config/english_image_pdf_text_first_v01.yaml"


def portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_scalar(value: str) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw[0:1] in {"'", '"'} and raw[-1:] == raw[0]:
        return raw[1:-1]
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Load the small config subset used by this isolated pipeline.

    This intentionally avoids adding PyYAML as a dependency. It supports nested
    dictionaries with two-space indentation and scalar string/bool/int values.
    """
    if not path.exists():
        return {}
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        stripped = line_without_comment.strip()
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if raw_value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)
    return root


def nested_get(config: dict[str, Any], path: str, default: Any = None) -> Any:
    cursor: Any = config
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def apply_config(args: argparse.Namespace) -> argparse.Namespace:
    config_path = Path(str(args.config or DEFAULT_CONFIG_PATH)).expanduser()
    if not config_path.is_absolute():
        config_path = WORKSPACE_ROOT / config_path
    config = load_simple_yaml(config_path)
    args.loaded_config_path = str(config_path) if config_path.exists() else ""
    args.loaded_config = config
    if not args.pdf:
        args.pdf = str(nested_get(config, "input.default_pdf", ""))
    if not args.pages:
        args.pages = str(nested_get(config, "input.default_pages", "1-6"))
    if not args.out:
        output_root = str(nested_get(config, "output.root", "outputs/english_text_first_pipeline_v01"))
        run_name = str(nested_get(config, "output.default_run_name", "english_text_first_configured_run"))
        args.out = str(WORKSPACE_ROOT / output_root / run_name)
    if args.dpi is None:
        args.dpi = int(nested_get(config, "ocr.dpi", 180) or 180)
    if not args.assembler_provider:
        args.assembler_provider = str(nested_get(config, "assembler.provider", "none"))
    if not args.assembler_model:
        args.assembler_model = str(nested_get(config, "assembler.model", DEFAULT_ARK_TEXT_ASSEMBLER_MODEL))
    if not args.assembler_timeout:
        args.assembler_timeout = int(nested_get(config, "assembler.timeout_seconds", 120) or 120)
    if not args.api_key:
        api_key_env = str(nested_get(config, "assembler.api_key_env", "ARK_API_KEY") or "ARK_API_KEY")
        args.api_key = os.environ.get(api_key_env, "")
        args.api_key_env = api_key_env
    else:
        args.api_key_env = "cli_arg"
    return args


def extract_json_block(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_not_found")
    return json.loads(clean[start : end + 1])


def line_index(lines: list[OcrLine]) -> dict[str, OcrLine]:
    return {line.line_id: line for line in lines}


def union_box(boxes: list[list[int]]) -> list[int]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def evidence_from_refs(refs: list[str], lines_by_id: dict[str, OcrLine]) -> dict[str, Any]:
    found = [lines_by_id[ref] for ref in refs if ref in lines_by_id]
    by_page: dict[str, list[list[int]]] = {}
    for line in found:
        by_page.setdefault(str(line.page), []).append(line.bbox_px)
    return {
        "line_refs": refs,
        "missing_line_refs": [ref for ref in refs if ref not in lines_by_id],
        "pages": sorted({line.page for line in found}),
        "bbox_px_by_page": {page: union_box(boxes) for page, boxes in by_page.items()},
    }


def text_from_refs(refs: list[str], lines_by_id: dict[str, OcrLine]) -> str:
    return "\n".join(lines_by_id[ref].text for ref in refs if ref in lines_by_id)


def build_model_input_bundle(
    *,
    pdf_path: Path,
    pages: list[int],
    lines: list[OcrLine],
    visual_objects: list[VisualObject],
    evidence_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    by_page: dict[int, list[OcrLine]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    page_payload = []
    for page in pages:
        page_lines = by_page.get(page, [])
        page_payload.append(
            {
                "page": page,
                "image_path": str(evidence_dir / "page_images" / f"p{page:03d}.png"),
                "ocr_line_count": len(page_lines),
                "ocr_lines": [asdict(line) for line in page_lines],
                "visual_objects": [asdict(obj) for obj in visual_objects if obj.page == page],
            }
        )

    return {
        "schema": "english_text_semantic_assembler_input_v0.1",
        "source_pdf": str(pdf_path),
        "pages": pages,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "pipeline_entry": "tools/run_english_image_pdf_text_first_v01.py",
        "evidence_artifacts": {
            "ocr_lines": str(evidence_dir / "ocr_lines.json"),
            "ocr_page_text": str(evidence_dir / "ocr_page_text.md"),
            "page_images_dir": str(evidence_dir / "page_images"),
            "visual_objects": str(evidence_dir / "visual_objects.json"),
            "ocr_overlays_dir": str(evidence_dir / "ocr_overlays"),
        },
        "assembler_contract": {
            "truthfulness": "Return only structures supported by OCR line refs, page refs, bbox evidence, and visual object refs. Do not turn raw OCR blocks into final questions without semantic grouping.",
            "required_outputs": ["semantic_nodes", "question_packets"],
            "semantic_requirements": [
                "Separate knowledge blocks from question packets.",
                "Represent shared reading passages once and attach multiple questions to that passage.",
                "Attach answer, analysis, translation, and vocabulary support back to the owning question.",
                "Attach tables, charts, diagrams, and images as visual_refs to their owning knowledge node or question.",
                "Mark incomplete page-range fragments as TRUNCATED_NEEDS_MORE_PAGES.",
                "Mark uncertain structures as NEEDS_QA rather than inventing fields.",
            ],
            "fallback_labels": [
                "OCR_FAILED",
                "VISUAL_OBJECT_COMPLEX_NEEDS_VLM",
                "TEXT_ORDER_UNCERTAIN",
                "CROSS_PAGE_EVIDENCE_INSUFFICIENT",
                "EXTERNAL_SOURCE_STRUCTURE_ABNORMAL",
            ],
        },
        "pages_payload": page_payload,
        "model_response_expected_schema": {
            "schema": "english_image_pdf_text_first_model_assembly_probe_v0.x",
            "nodes": [
                {
                    "node_id": "stable id",
                    "node_type": "knowledge_block | shared_passage | question_packet | guided_task_group | shared_passage_fragment",
                    "title": "short title",
                    "review_status": "MODEL_ASSEMBLED | MODEL_ASSEMBLED_NEEDS_QA | TRUNCATED_NEEDS_MORE_PAGES",
                    "evidence": {"line_refs": ["p001_l001"], "pages": [1], "bbox_px_by_page": {"1": [0, 0, 10, 10]}},
                    "fields": {},
                    "relations": {},
                    "visual_refs": [],
                }
            ],
            "question_packets": [],
        },
        "output_dir": str(out_dir),
    }


def build_text_assembler_prompt(model_input: dict[str, Any]) -> tuple[str, str]:
    system_prompt = """You are TeachBase English image-PDF text-first semantic assembler.

You receive OCR lines with page coordinates and visual-object candidates. Build a structure-preserving JSON assembly for an English teacher handout.

Hard rules:
- Use only evidence from OCR line refs, page refs, bbox evidence, and visual object refs.
- Do not turn raw OCR blocks into final questions without semantic grouping.
- Separate knowledge blocks, guided drills, shared reading passages, question packets, answer, analysis, translation, and visual assets.
- Reading passages may be shared by multiple questions. Represent the passage once and attach questions to it.
- Red teacher-version answer/analysis/translation text must be attached back to the owning question.
- Tables, tree diagrams, figures, and images should be visual_refs attached to their owning knowledge node or question. Do not hallucinate their content.
- If evidence is incomplete, output TRUNCATED_NEEDS_MORE_PAGES or MODEL_ASSEMBLED_NEEDS_QA.
- Return strict JSON only. No markdown.
"""
    expected = {
        "schema": "english_image_pdf_text_first_model_assembly_v0.1",
        "nodes": [
            {
                "node_id": "stable_id",
                "node_type": "lesson_header | knowledge_block | guided_task_group | shared_passage | question_packet | shared_passage_fragment | review_unit",
                "title": "short title",
                "role_in_handout": "semantic role",
                "model_summary": "brief judgment",
                "review_status": "MODEL_ASSEMBLED | MODEL_ASSEMBLED_NEEDS_QA | MODEL_ASSEMBLED_NEEDS_TEXT_QA | TRUNCATED_NEEDS_MORE_PAGES",
                "source_text": "optional reconstructed text",
                "evidence": {"line_refs": ["p001_l001"]},
                "fields": {},
                "relations": {},
                "visual_refs": [{"object_id": "p003_vo001", "semantic_role": "BTEC_method_table"}],
            }
        ],
        "question_packets": [
            {
                "packet_id": "stable_packet_id",
                "source_node_id": "question node id",
                "question_type": "english_reading_main_idea | english_reading_detail | english_grammar | english_writing | english_unknown",
                "shared_passage_id": "shared passage node id if any",
                "stem": "question stem",
                "options": {"A": "", "B": "", "C": "", "D": ""},
                "answer": "",
                "analysis": "",
                "translation": "",
                "vocabulary_support": "",
                "evidence": {"line_refs": ["p001_l001"]},
                "review_status": "MODEL_ASSEMBLED_NEEDS_QA",
            }
        ],
    }
    compact_pages = []
    for page in model_input.get("pages_payload", []):
        compact_pages.append(
            {
                "page": page.get("page"),
                "ocr_lines": [
                    {
                        "line_id": line.get("line_id"),
                        "text": line.get("text"),
                        "confidence": line.get("confidence"),
                        "bbox_px": line.get("bbox_px"),
                    }
                    for line in page.get("ocr_lines", [])
                ],
                "visual_objects": page.get("visual_objects", []),
            }
        )
    user_payload = {
        "task": "Assemble English handout structure from OCR evidence.",
        "source_pdf": model_input.get("source_pdf"),
        "pages": model_input.get("pages"),
        "expected_output_schema": expected,
        "pages_payload": compact_pages,
    }
    return system_prompt, json.dumps(user_payload, ensure_ascii=False)


def call_ark_text_assembler(
    *,
    model_input: dict[str, Any],
    api_key: str,
    model: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system_prompt, user_prompt = build_text_assembler_prompt(model_input)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        ARK_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    parsed = extract_json_block(content)
    meta = {
        "provider": "ark",
        "model": model,
        "endpoint": ARK_API_URL,
        "latency_seconds": round(time.time() - started, 3),
        "usage": payload.get("usage", {}),
        "raw_content": content,
    }
    return parsed, meta


def normalize_visual_objects(visual_objects: list[VisualObject], out_dir: Path, evidence_dir: Path) -> dict[str, Any]:
    assets = []
    for obj in visual_objects:
        source_crop = Path(obj.crop_path)
        asset_path = evidence_dir / "visual_objects" / source_crop.name
        if source_crop.exists() and source_crop.resolve() != asset_path.resolve():
            shutil.copy2(source_crop, asset_path)
        assets.append(
            {
                "asset_id": obj.object_id,
                "asset_type": obj.object_type,
                "page": obj.page,
                "bbox_px": obj.bbox_px,
                "bbox_norm": obj.bbox_norm,
                "confidence": obj.confidence,
                "path": str(asset_path),
                "source": "cv_visual_object_probe",
                "review_status": "NEEDS_QA",
            }
        )
    return {
        "schema": "asset_manifest_v0.1",
        "source": "english_image_pdf_text_first_pipeline_v0.1",
        "assets": assets,
        "counts": {"assets": len(assets)},
    }


def normalize_model_output(
    *,
    model_output: dict[str, Any],
    lines: list[OcrLine],
    visual_objects: list[VisualObject],
    assembly_source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    lines_by_id = line_index(lines)
    warnings: list[str] = []
    visual_ids = {obj.object_id for obj in visual_objects}

    semantic_nodes: list[dict[str, Any]] = []
    for raw in model_output.get("nodes", []):
        if not isinstance(raw, dict):
            warnings.append("skipped_non_object_node")
            continue
        raw_evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        refs = list(raw_evidence.get("line_refs") or raw.get("ocr_line_refs") or [])
        evidence = evidence_from_refs(refs, lines_by_id)
        if evidence["missing_line_refs"]:
            warnings.append(f"{raw.get('node_id', 'unknown')}:missing_line_refs:{len(evidence['missing_line_refs'])}")
        visual_refs = []
        for item in raw.get("visual_refs") or []:
            if isinstance(item, dict):
                object_id = str(item.get("object_id") or "")
                visual_refs.append(item)
            else:
                object_id = str(item)
                visual_refs.append({"object_id": object_id})
            if object_id and object_id not in visual_ids:
                warnings.append(f"{raw.get('node_id', 'unknown')}:missing_visual_ref:{object_id}")
        semantic_nodes.append(
            {
                "node_id": str(raw.get("node_id") or f"node_{len(semantic_nodes)+1:04d}"),
                "node_type": str(raw.get("node_type") or "review_unit"),
                "title": str(raw.get("title") or ""),
                "role_in_handout": str(raw.get("role_in_handout") or ""),
                "review_status": str(raw.get("review_status") or "NEEDS_QA"),
                "source": assembly_source,
                "model_summary": str(raw.get("model_summary") or ""),
                "source_text": raw.get("source_text") if isinstance(raw.get("source_text"), str) else text_from_refs(refs, lines_by_id),
                "evidence": evidence,
                "fields": raw.get("fields") if isinstance(raw.get("fields"), dict) else {},
                "relations": raw.get("relations") if isinstance(raw.get("relations"), dict) else {},
                "visual_refs": visual_refs,
            }
        )

    question_packets: list[dict[str, Any]] = []
    node_ids = {node["node_id"] for node in semantic_nodes}
    passage_ids = {node["node_id"] for node in semantic_nodes if node["node_type"] == "shared_passage"}
    for raw in model_output.get("question_packets", []):
        if not isinstance(raw, dict):
            warnings.append("skipped_non_object_question_packet")
            continue
        refs = list((raw.get("evidence") or {}).get("line_refs") or [])
        evidence = evidence_from_refs(refs, lines_by_id)
        source_node_id = str(raw.get("source_node_id") or "")
        shared_passage_id = str(raw.get("shared_passage_id") or "")
        if source_node_id and source_node_id not in node_ids:
            warnings.append(f"{raw.get('packet_id', 'unknown')}:missing_source_node:{source_node_id}")
        if shared_passage_id and shared_passage_id not in passage_ids:
            warnings.append(f"{raw.get('packet_id', 'unknown')}:missing_shared_passage:{shared_passage_id}")
        question_packets.append(
            {
                "packet_id": str(raw.get("packet_id") or f"qp_{len(question_packets)+1:04d}"),
                "source_node_id": source_node_id,
                "question_type": str(raw.get("question_type") or "english_unknown"),
                "shared_passage_id": shared_passage_id,
                "stem": str(raw.get("stem") or ""),
                "options": raw.get("options") if isinstance(raw.get("options"), dict) else {},
                "answer": str(raw.get("answer") or ""),
                "analysis": str(raw.get("analysis") or ""),
                "translation": str(raw.get("translation") or ""),
                "vocabulary_support": str(raw.get("vocabulary_support") or ""),
                "evidence": evidence,
                "review_status": str(raw.get("review_status") or "NEEDS_QA"),
                "source": assembly_source,
            }
        )
    return semantic_nodes, question_packets, warnings


def build_release_decision(
    *,
    semantic_nodes: list[dict[str, Any]],
    question_packets: list[dict[str, Any]],
    warnings: list[str],
    model_output_supplied: bool,
    ocr_line_count: int,
    assembly_source: str,
) -> dict[str, Any]:
    blocking: list[str] = []
    if not model_output_supplied:
        blocking.append("TEXT_SEMANTIC_ASSEMBLER_OUTPUT_MISSING")
    if ocr_line_count == 0:
        blocking.append("OCR_FAILED")
    if warnings:
        blocking.append("EVIDENCE_VALIDATION_WARNINGS")
    if not question_packets and model_output_supplied:
        blocking.append("NO_QUESTION_PACKETS")
    review_required_statuses = {
        "NEEDS_QA",
        "MODEL_ASSEMBLED_NEEDS_QA",
        "MODEL_ASSEMBLED_NEEDS_TEXT_QA",
        "TRUNCATED_NEEDS_MORE_PAGES",
    }
    review_required_nodes = [
        node
        for node in semantic_nodes
        if str(node.get("review_status", "")) in review_required_statuses
        or str(node.get("review_status", "")).endswith("NEEDS_QA")
    ]
    review_required_packets = [
        packet
        for packet in question_packets
        if str(packet.get("review_status", "")) in review_required_statuses
        or str(packet.get("review_status", "")).endswith("NEEDS_QA")
    ]
    if review_required_nodes or review_required_packets:
        blocking.append("STRUCTURE_REQUIRES_QA")
    if assembly_source.startswith("agent_manual_"):
        blocking.append("MANUAL_MODEL_PROBE_NOT_RUNTIME_MODEL_OUTPUT")
    ready_packets = [
        packet
        for packet in question_packets
        if packet not in review_required_packets
    ]
    return {
        "schema": "release_decision_v0.1",
        "source": "english_image_pdf_text_first_pipeline_v0.1",
        "decision": "HOLD_FOR_QA" if blocking else "CANDIDATE_FOR_RUNTIME_IMPORT",
        "blocking_reasons": blocking,
        "counts": {
            "semantic_nodes": len(semantic_nodes),
            "question_packets": len(question_packets),
            "ready_like_question_packets": len(ready_packets),
            "nodes_requiring_qa": len(review_required_nodes),
            "question_packets_requiring_qa": len(review_required_packets),
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "truthfulness_note": "This release decision is for the isolated English text-first probe. It is not a production release gate.",
    }


def write_review_html(
    path: Path,
    *,
    semantic_nodes: list[dict[str, Any]],
    question_packets: list[dict[str, Any]],
    asset_manifest: dict[str, Any],
    release_decision: dict[str, Any],
) -> None:
    node_cards = []
    for node in semantic_nodes:
        evidence = node.get("evidence", {})
        node_cards.append(
            "<article>"
            f"<h3>{html.escape(node['node_id'])} | {html.escape(node['node_type'])} | {html.escape(node['review_status'])}</h3>"
            f"<div class='meta'>pages {html.escape(str(evidence.get('pages', [])))} | source {html.escape(node.get('source', ''))}</div>"
            f"<p>{html.escape(node.get('model_summary', ''))}</p>"
            f"<pre>{html.escape(str(node.get('source_text', ''))[:2400])}</pre>"
            "</article>"
        )
    qp_cards = []
    for packet in question_packets:
        qp_cards.append(
            "<article>"
            f"<h3>{html.escape(packet['packet_id'])} | {html.escape(packet['review_status'])}</h3>"
            f"<div class='meta'>shared passage: {html.escape(packet.get('shared_passage_id', ''))}</div>"
            f"<p><b>{html.escape(packet.get('stem', ''))}</b></p>"
            f"<pre>{html.escape(json.dumps(packet.get('options', {}), ensure_ascii=False, indent=2))}</pre>"
            f"<div class='answer'>answer: {html.escape(packet.get('answer', ''))}</div>"
            "</article>"
        )
    asset_cards = []
    for asset in asset_manifest.get("assets", []):
        asset_cards.append(
            "<article>"
            f"<h3>{html.escape(asset['asset_id'])} | {html.escape(asset['asset_type'])}</h3>"
            f"<div class='meta'>page {asset['page']} | bbox {html.escape(str(asset['bbox_px']))}</div>"
            f"<img src='{html.escape(asset['path'])}'>"
            "</article>"
        )
    path.write_text(
        f"""<!doctype html>
<meta charset="utf-8">
<title>English text-first pipeline v0.1 review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f6f4;color:#202124}}
h1{{font-size:24px}} h2{{margin-top:30px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px}}
article{{background:white;border:1px solid #ddd;border-radius:6px;padding:12px}}
h3{{font-size:15px;margin:0 0 8px}} .meta{{font-size:12px;color:#666;margin:4px 0 8px}}
pre{{white-space:pre-wrap;font-size:12px;line-height:1.45;max-height:340px;overflow:auto;background:#fafafa;padding:8px}}
.answer{{color:#9b1c31;font-weight:700}} img{{max-width:100%;border:1px solid #ddd}}
</style>
<h1>English text-first pipeline v0.1 review</h1>
<p>Decision: <b>{html.escape(release_decision['decision'])}</b></p>
<pre>{html.escape(json.dumps(release_decision, ensure_ascii=False, indent=2))}</pre>
<h2>Question Packets</h2><div class="grid">{''.join(qp_cards)}</div>
<h2>Semantic Nodes</h2><div class="grid">{''.join(node_cards)}</div>
<h2>Assets</h2><div class="grid">{''.join(asset_cards)}</div>
""",
        encoding="utf-8",
    )


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    args = apply_config(args)
    if not str(args.pdf or "").strip():
        raise SystemExit("pdf_required: pass --pdf or set input.default_pdf in config")
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"pdf_not_found: {pdf_path}")
    out_dir = Path(args.out).expanduser().resolve()
    evidence_dir = out_dir / "evidence"
    normalized_dir = out_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    pages = parse_pages(args.pages)
    page_images = render_pages(pdf_path, pages, evidence_dir / "page_images", args.dpi)
    lines, ocr_meta = run_ocr(page_images)
    visual_objects = detect_visual_objects(page_images, evidence_dir / "visual_objects")
    draw_ocr_overlays(page_images, lines, visual_objects, evidence_dir / "ocr_overlays")

    write_json(evidence_dir / "ocr_lines.json", {"schema": "english_ocr_lines_v0.1", "lines": [asdict(line) for line in lines]})
    write_json(evidence_dir / "ocr_run_meta.json", ocr_meta)
    write_json(evidence_dir / "visual_objects.json", {"schema": "english_visual_objects_v0.1", "objects": [asdict(obj) for obj in visual_objects]})
    write_page_text(evidence_dir / "ocr_page_text.md", lines)

    model_input = build_model_input_bundle(
        pdf_path=pdf_path,
        pages=pages,
        lines=lines,
        visual_objects=visual_objects,
        evidence_dir=evidence_dir,
        out_dir=out_dir,
    )
    write_json(out_dir / "model_input_bundle.json", model_input)

    model_output_supplied = bool(args.model_output)
    semantic_nodes: list[dict[str, Any]] = []
    question_packets: list[dict[str, Any]] = []
    warnings: list[str] = []
    assembly_source = "missing_text_semantic_assembler_output"
    model_output_path = ""
    assembler_meta: dict[str, Any] = {
        "provider": str(args.assembler_provider or "none"),
        "model": str(args.assembler_model or ""),
        "called": False,
    }
    if args.model_output:
        model_output_path = str(Path(args.model_output).expanduser().resolve())
        model_output = read_json(Path(model_output_path))
        assembly_source = str(args.assembly_source or "external_text_semantic_assembler")
        semantic_nodes, question_packets, warnings = normalize_model_output(
            model_output=model_output,
            lines=lines,
            visual_objects=visual_objects,
            assembly_source=assembly_source,
        )
    elif args.assembler_provider == "ark":
        api_key = str(args.api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
        model = str(args.assembler_model or DEFAULT_ARK_TEXT_ASSEMBLER_MODEL).strip()
        assembler_meta["model"] = model
        if not api_key:
            warnings.append("ark_text_assembler_skipped_missing_api_key")
            assembly_source = "ark_text_semantic_assembler_missing_api_key"
        else:
            try:
                model_output, call_meta = call_ark_text_assembler(
                    model_input=model_input,
                    api_key=api_key,
                    model=model,
                    timeout_seconds=int(args.assembler_timeout or 120),
                )
                assembler_meta = {**assembler_meta, **call_meta, "called": True}
                model_output_path = str(out_dir / "model_output_ark.json")
                write_json(out_dir / "model_output_ark.json", model_output)
                write_json(out_dir / "model_output_ark_meta.json", assembler_meta)
                model_output_supplied = True
                assembly_source = f"ark_text_semantic_assembler:{model}"
                semantic_nodes, question_packets, warnings = normalize_model_output(
                    model_output=model_output,
                    lines=lines,
                    visual_objects=visual_objects,
                    assembly_source=assembly_source,
                )
            except Exception as exc:
                warnings.append(f"ark_text_assembler_failed:{type(exc).__name__}:{str(exc)[:160]}")
                write_json(
                    out_dir / "model_output_ark_error.json",
                    {
                        "schema": "ark_text_assembler_error_v0.1",
                        "provider": "ark",
                        "model": model,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                assembly_source = f"ark_text_semantic_assembler_failed:{model}"

    asset_manifest = normalize_visual_objects(visual_objects, out_dir, evidence_dir)
    release_decision = build_release_decision(
        semantic_nodes=semantic_nodes,
        question_packets=question_packets,
        warnings=warnings,
        model_output_supplied=model_output_supplied,
        ocr_line_count=len(lines),
        assembly_source=assembly_source,
    )
    runtime_import_candidate = {
        "schema": "runtime_import_candidate_v0.1",
        "source": "english_image_pdf_text_first_pipeline_v0.1",
        "truthfulness_note": "This is a review import candidate only. Runtime import was not executed.",
        "semantic_nodes_path": str(normalized_dir / "semantic_nodes.json"),
        "question_packets_path": str(normalized_dir / "question_packets.json"),
        "asset_manifest_path": str(normalized_dir / "asset_manifest.json"),
        "release_decision_path": str(normalized_dir / "release_decision.json"),
        "semantic_nodes": semantic_nodes,
        "question_packets": question_packets,
        "asset_manifest": asset_manifest,
        "release_decision": release_decision,
    }

    write_json(normalized_dir / "semantic_nodes.json", {"schema": "semantic_nodes_v0.1", "nodes": semantic_nodes})
    write_json(normalized_dir / "question_packets.json", {"schema": "question_packets_v0.1", "question_packets": question_packets})
    write_json(normalized_dir / "asset_manifest.json", asset_manifest)
    write_json(normalized_dir / "release_decision.json", release_decision)
    write_json(normalized_dir / "runtime_import_candidate.json", runtime_import_candidate)
    write_review_html(
        out_dir / "review.html",
        semantic_nodes=semantic_nodes,
        question_packets=question_packets,
        asset_manifest=asset_manifest,
        release_decision=release_decision,
    )

    summary = {
        "schema": PIPELINE_SCHEMA,
        "entry": "tools/run_english_image_pdf_text_first_v01.py",
        "config_path": str(getattr(args, "loaded_config_path", "") or ""),
        "pdf": str(pdf_path),
        "pages": pages,
        "page_count": len(page_images),
        "ocr_line_count": len(lines),
        "visual_object_count": len(visual_objects),
        "model_output_supplied": model_output_supplied,
        "model_output_path": model_output_path,
        "assembler": assembler_meta,
        "api_key_env": str(getattr(args, "api_key_env", "") or ""),
        "assembly_source": assembly_source,
        "semantic_node_count": len(semantic_nodes),
        "question_packet_count": len(question_packets),
        "release_decision": release_decision["decision"],
        "warnings": warnings,
        "artifacts": {
            "model_input_bundle": str(out_dir / "model_input_bundle.json"),
            "evidence_dir": str(evidence_dir),
            "semantic_nodes": str(normalized_dir / "semantic_nodes.json"),
            "question_packets": str(normalized_dir / "question_packets.json"),
            "asset_manifest": str(normalized_dir / "asset_manifest.json"),
            "release_decision": str(normalized_dir / "release_decision.json"),
            "runtime_import_candidate": str(normalized_dir / "runtime_import_candidate.json"),
            "review_html": str(out_dir / "review.html"),
        },
    }
    write_json(out_dir / "run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run English image-PDF text-first ingest pipeline v0.1.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--pdf", default="")
    parser.add_argument("--pages", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--model-output", default="", help="Optional text semantic assembler output JSON.")
    parser.add_argument("--assembly-source", default="", help="Truthful source label for --model-output.")
    parser.add_argument("--assembler-provider", default="", choices=["", "none", "ark"], help="Optional live text semantic assembler provider.")
    parser.add_argument("--assembler-model", default="")
    parser.add_argument("--assembler-timeout", type=int, default=0)
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    summary = run_pipeline(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
