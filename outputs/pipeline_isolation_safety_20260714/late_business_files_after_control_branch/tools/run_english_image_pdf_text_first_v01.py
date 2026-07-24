from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "tools" / "vendor"
if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

from english_text_first_evidence import (
    detect_visual_objects,
    draw_ocr_overlays,
    extract_text_layer,
    line_dicts,
    parse_pages,
    render_pages,
    run_ocr,
    visual_dicts,
    write_json,
    write_page_text,
)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def nested_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def page_chunks(pages: list[int], window: int, overlap: int) -> list[list[int]]:
    if window <= 0:
        return [pages]
    chunks: list[list[int]] = []
    step = max(1, window - max(0, overlap))
    index = 0
    while index < len(pages):
        chunk = pages[index : index + window]
        if chunk:
            chunks.append(chunk)
        if index + window >= len(pages):
            break
        index += step
    return chunks


def build_pages_payload(pages: list[int], ocr_lines: list[dict[str, Any]], rendered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered_by_page = {int(page["page"]): page for page in rendered}
    by_page: dict[int, list[dict[str, Any]]] = {}
    for line in ocr_lines:
        by_page.setdefault(int(line["page"]), []).append(line)
    payload: list[dict[str, Any]] = []
    for page_no in pages:
        page_lines = sorted(by_page.get(page_no, []), key=lambda item: (item["bbox_px"][1], item["bbox_px"][0]))
        payload.append(
            {
                "page": page_no,
                "image_path": rendered_by_page.get(page_no, {}).get("image_path"),
                "width_px": rendered_by_page.get(page_no, {}).get("width_px"),
                "height_px": rendered_by_page.get(page_no, {}).get("height_px"),
                "ocr_lines": [
                    {
                        "line_id": line["line_id"],
                        "text": line["text"],
                        "bbox_px": line["bbox_px"],
                        "score": line.get("score"),
                    }
                    for line in page_lines
                ],
            }
        )
    return payload


SYSTEM_PROMPT = """You are an English handout semantic assembler.
Your job is to transform OCR evidence from image-PDF pages into compact teaching metadata.
Use OCR line ids and page coordinates as evidence. Do not invent content not supported by line ids.
Do not copy long passages into output; keep passage bodies and explanations concise and refer to line_refs.
Separate knowledge blocks, examples, exercises, reading passages, question groups, answers, analysis, translation and visual assets.
If a table/tree/chart/image is important, create a semantic node that references visual_refs instead of trying to redraw it.
Return one valid JSON object only."""


def user_prompt(bundle: dict[str, Any], chunk_pages: list[int], chunk_id: int) -> str:
    compact = {
        "schema": "english_text_first_assembler_input_v0.1",
        "chunk_id": f"c{chunk_id:03d}",
        "pages": [page for page in bundle["pages"] if page["page"] in set(chunk_pages)],
        "visual_objects": [obj for obj in bundle["visual_objects"] if int(obj["page"]) in set(chunk_pages)],
        "required_output": {
            "semantic_nodes": [
                {
                    "node_id": "c001_n001",
                    "node_type": "lesson_header|knowledge_block|example|exercise_group|reading_passage|question_group|question_packet|answer_key|analysis|translation|visual_asset",
                    "title": "short title",
                    "role_in_handout": "short role",
                    "model_summary": "short summary",
                    "source_text": "short excerpt only, not full long passage",
                    "evidence": {"line_refs": ["p001_l001"], "pages": [1]},
                    "relations": {"belongs_to": [], "answers": [], "explains": [], "uses_passage": []},
                    "visual_refs": [],
                    "fields": {},
                }
            ],
            "question_packets": [
                {
                    "packet_id": "c001_q001",
                    "source_node_id": "c001_n001",
                    "question_type": "reading_mcq|grammar|writing|other",
                    "stem": "short stem",
                    "options": [],
                    "answer": "",
                    "analysis": "",
                    "translation": "",
                    "passage_node_id": "",
                    "evidence": {"line_refs": ["p001_l001"], "pages": [1]},
                    "review_status": "MODEL_ASSEMBLED",
                }
            ],
            "release_decision": {
                "decision": "PASS_TO_QA|HOLD_FOR_QA",
                "reasons": [],
                "fallback_recommended": False,
            },
        },
    }
    return json.dumps(compact, ensure_ascii=False)


def call_ark(
    endpoint: str,
    api_key: str,
    model: str,
    bundle: dict[str, Any],
    chunk_pages: list[int],
    chunk_id: int,
    timeout: int,
    max_tokens: int,
    out_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.time()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(bundle, chunk_pages, chunk_id)},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    meta: dict[str, Any] = {
        "attempted": True,
        "called": False,
        "parsed": False,
        "chunk_id": f"c{chunk_id:03d}",
        "pages": chunk_pages,
        "model": model,
        "max_tokens": max_tokens,
    }
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_payload = json.loads(response.read().decode("utf-8"))
        meta["called"] = True
        meta["latency_seconds"] = round(time.time() - started, 3)
        meta["usage"] = raw_payload.get("usage")
        choice = (raw_payload.get("choices") or [{}])[0]
        meta["finish_reason"] = choice.get("finish_reason")
        content = (choice.get("message") or {}).get("content") or ""
        (out_dir / f"chunk_{chunk_id:03d}_raw.txt").write_text(content, encoding="utf-8")
        write_json(out_dir / f"chunk_{chunk_id:03d}_raw_payload.json", raw_payload)
        try:
            parsed = json.loads(content)
            meta["parsed"] = True
            write_json(out_dir / f"chunk_{chunk_id:03d}.json", parsed)
            return parsed, meta
        except json.JSONDecodeError as exc:
            meta["error"] = f"JSONDecodeError: {exc}"
            return None, meta
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        meta["error"] = f"HTTPError {exc.code}: {body[:1000]}"
        meta["latency_seconds"] = round(time.time() - started, 3)
        return None, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        meta["latency_seconds"] = round(time.time() - started, 3)
        return None, meta


def evidence_for_refs(line_refs: list[str], line_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pages: list[int] = []
    boxes: dict[str, list[int]] = {}
    missing: list[str] = []
    for ref in line_refs:
        line = line_index.get(ref)
        if not line:
            missing.append(ref)
            continue
        page = int(line["page"])
        if page not in pages:
            pages.append(page)
        key = str(page)
        bbox = line["bbox_px"]
        if key not in boxes:
            boxes[key] = list(bbox)
        else:
            current = boxes[key]
            boxes[key] = [
                min(current[0], bbox[0]),
                min(current[1], bbox[1]),
                max(current[2], bbox[2]),
                max(current[3], bbox[3]),
            ]
    return {"line_refs": line_refs, "missing_line_refs": missing, "pages": sorted(pages), "bbox_px_by_page": boxes}


def normalize_model_outputs(
    outputs: list[dict[str, Any]],
    source: str,
    ocr_lines: list[dict[str, Any]],
    visual_objects: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    line_index = {line["line_id"]: line for line in ocr_lines}
    nodes: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    warnings: list[str] = []
    for out_i, output in enumerate(outputs, start=1):
        for node_i, node in enumerate(output.get("semantic_nodes") or [], start=1):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or f"c{out_i:03d}_n{node_i:03d}")
            if node_id in seen_ids:
                node_id = f"c{out_i:03d}_{node_id}"
            seen_ids.add(node_id)
            refs = ((node.get("evidence") or {}).get("line_refs") or []) if isinstance(node.get("evidence"), dict) else []
            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": node.get("node_type") or "semantic_node",
                    "title": node.get("title") or "",
                    "role_in_handout": node.get("role_in_handout") or "",
                    "review_status": node.get("review_status") or "MODEL_ASSEMBLED",
                    "source": source,
                    "model_summary": node.get("model_summary") or "",
                    "source_text": node.get("source_text") or "",
                    "evidence": evidence_for_refs([str(ref) for ref in refs], line_index),
                    "fields": node.get("fields") or {},
                    "relations": node.get("relations") or {},
                    "visual_refs": node.get("visual_refs") or [],
                }
            )
        for packet_i, packet in enumerate(output.get("question_packets") or [], start=1):
            if not isinstance(packet, dict):
                continue
            refs = ((packet.get("evidence") or {}).get("line_refs") or []) if isinstance(packet.get("evidence"), dict) else []
            packets.append(
                {
                    "packet_id": packet.get("packet_id") or f"c{out_i:03d}_q{packet_i:03d}",
                    "source_node_id": packet.get("source_node_id") or "",
                    "question_type": packet.get("question_type") or "other",
                    "stem": packet.get("stem") or "",
                    "options": packet.get("options") or [],
                    "answer": packet.get("answer") or "",
                    "analysis": packet.get("analysis") or "",
                    "translation": packet.get("translation") or "",
                    "passage_node_id": packet.get("passage_node_id") or "",
                    "evidence": evidence_for_refs([str(ref) for ref in refs], line_index),
                    "review_status": packet.get("review_status") or "MODEL_ASSEMBLED",
                    "source": source,
                }
            )
    decisions = [out.get("release_decision") or {} for out in outputs]
    hold_reasons = []
    for decision in decisions:
        if decision.get("decision") != "PASS_TO_QA":
            hold_reasons.extend(decision.get("reasons") or ["chunk requires QA"])
    if not outputs:
        hold_reasons.append("no parsed model output")
    if any(node["evidence"]["missing_line_refs"] for node in nodes):
        warnings.append("some model line_refs were not found in OCR evidence")
    release = {
        "schema": "release_decision_v0.1",
        "decision": "HOLD_FOR_QA" if hold_reasons or warnings else "PASS_TO_QA",
        "reasons": hold_reasons + warnings,
        "fallback_recommended": bool(hold_reasons),
    }
    semantic_nodes = {"schema": "semantic_nodes_v0.1", "nodes": nodes}
    question_packets = {"schema": "question_packets_v0.1", "packets": packets}
    asset_manifest = {
        "schema": "asset_manifest_v0.1",
        "visual_objects": visual_objects,
    }
    runtime_import = {
        "schema": "english_runtime_import_candidate_v0.1",
        "semantic_nodes_path": "normalized/semantic_nodes.json",
        "question_packets_path": "normalized/question_packets.json",
        "asset_manifest_path": "normalized/asset_manifest.json",
        "release_decision_path": "normalized/release_decision.json",
        "runtime_import_enabled": False,
    }
    return semantic_nodes, question_packets, asset_manifest, release, runtime_import


def write_review(path: Path, summary: dict[str, Any], pages_payload: list[dict[str, Any]], release: dict[str, Any]) -> None:
    rows = []
    for page in pages_payload:
        sample = "<br>".join(
            f"<code>{line['line_id']}</code> {line['text']}" for line in page["ocr_lines"][:20]
        )
        rows.append(f"<h2>Page {page['page']}</h2><p>{len(page['ocr_lines'])} OCR lines</p><div>{sample}</div>")
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>English text-first review</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;line-height:1.45}}code{{color:#a33}}pre{{background:#f6f6f6;padding:12px;white-space:pre-wrap}}</style>
<h1>English Image-PDF Text-First Review</h1>
<h2>Run Summary</h2><pre>{json.dumps(summary, ensure_ascii=False, indent=2)}</pre>
<h2>Release</h2><pre>{json.dumps(release, ensure_ascii=False, indent=2)}</pre>
{''.join(rows)}
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_image_pdf_text_first_v01.yaml")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--assembler-provider", choices=["none", "ark"], default=None)
    parser.add_argument("--assembler-window-pages", type=int, default=None)
    parser.add_argument("--assembler-timeout", type=int, default=None)
    args = parser.parse_args()

    config = load_yaml(REPO_ROOT / args.config)
    pages = parse_pages(args.pages or nested_get(config, "input.default_pages", "1-8"))
    provider = args.assembler_provider or nested_get(config, "assembler.provider", "none")
    window_pages = args.assembler_window_pages or int(nested_get(config, "assembler.window_pages", 4))
    overlap_pages = int(nested_get(config, "assembler.window_overlap_pages", 0))
    dpi = int(nested_get(config, "ocr.dpi", 180))
    endpoint = nested_get(config, "assembler.endpoint", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    model = nested_get(config, "assembler.model", "doubao-seed-2-0-lite-260428")
    model_alias = nested_get(config, "assembler.model_alias", "doubao2.0mini")
    api_key_env = nested_get(config, "assembler.api_key_env", "ARK_API_KEY")
    timeout = args.assembler_timeout or int(nested_get(config, "assembler.timeout_seconds", 300))
    max_tokens = int(nested_get(config, "assembler.max_tokens", 9000))

    out_dir = Path(args.out).resolve()
    evidence_dir = out_dir / "evidence"
    normalized_dir = out_dir / "normalized"
    model_dir = out_dir / "model_outputs"
    for directory in [evidence_dir, normalized_dir, model_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    pdf_path = Path(args.pdf).resolve()
    text_layer = extract_text_layer(pdf_path, pages)
    rendered = render_pages(pdf_path, pages, evidence_dir / "page_images", dpi=dpi)
    ocr_lines_obj, ocr_meta = run_ocr(rendered)
    visuals_obj = detect_visual_objects(rendered, ocr_lines_obj, evidence_dir / "visual_objects")
    draw_ocr_overlays(rendered, ocr_lines_obj, evidence_dir / "ocr_overlays")
    ocr_lines = line_dicts(ocr_lines_obj)
    visual_objects = visual_dicts(visuals_obj)
    pages_payload = build_pages_payload(pages, ocr_lines, rendered)

    write_json(evidence_dir / "text_layer_probe.json", text_layer)
    write_json(evidence_dir / "ocr_lines.json", ocr_lines)
    write_json(evidence_dir / "ocr_run_meta.json", ocr_meta)
    write_json(evidence_dir / "visual_objects.json", visual_objects)
    write_page_text(evidence_dir / "ocr_page_text.md", ocr_lines_obj)

    bundle = {
        "schema": "english_text_first_model_input_bundle_v0.1",
        "pdf": str(pdf_path),
        "pages": pages_payload,
        "text_layer": text_layer,
        "visual_objects": visual_objects,
    }
    write_json(out_dir / "model_input_bundle.json", bundle)

    parsed_outputs: list[dict[str, Any]] = []
    assembler_metas: list[dict[str, Any]] = []
    if provider == "ark":
        api_key = os.environ.get(api_key_env)
        if not api_key:
            assembler_metas.append({"attempted": False, "called": False, "parsed": False, "error": f"missing env {api_key_env}"})
        else:
            for chunk_id, chunk_pages in enumerate(page_chunks(pages, window_pages, overlap_pages), start=1):
                parsed, meta = call_ark(endpoint, api_key, model, bundle, chunk_pages, chunk_id, timeout, max_tokens, model_dir)
                assembler_metas.append(meta)
                write_json(model_dir / f"chunk_{chunk_id:03d}_meta.json", meta)
                if parsed is not None:
                    parsed_outputs.append(parsed)
    else:
        assembler_metas.append({"attempted": False, "called": False, "parsed": False, "provider": provider})

    source = f"ark_text_semantic_assembler:{model}" if provider == "ark" else "ocr_evidence_only"
    semantic_nodes, question_packets, asset_manifest, release, runtime_import = normalize_model_outputs(
        parsed_outputs, source, ocr_lines, visual_objects
    )
    write_json(normalized_dir / "semantic_nodes.json", semantic_nodes)
    write_json(normalized_dir / "question_packets.json", question_packets)
    write_json(normalized_dir / "asset_manifest.json", asset_manifest)
    write_json(normalized_dir / "release_decision.json", release)
    write_json(normalized_dir / "runtime_import_candidate.json", runtime_import)

    summary = {
        "schema": "english_image_pdf_text_first_pipeline_v0.1",
        "entry": "tools/run_english_image_pdf_text_first_v01.py",
        "config_path": str((REPO_ROOT / args.config).resolve()),
        "pdf": str(pdf_path),
        "pages": pages,
        "page_count": len(pages),
        "text_layer_total_chars": text_layer["total_chars"],
        "text_layer_usable": text_layer["usable"],
        "ocr_line_count": len(ocr_lines),
        "visual_object_count": len(visual_objects),
        "assembler": {
            "provider": provider,
            "model": model,
            "model_alias": model_alias,
            "api_key_env": api_key_env,
            "window_pages": window_pages,
            "window_overlap_pages": overlap_pages,
            "chunks": assembler_metas,
        },
        "parsed_chunk_count": len(parsed_outputs),
        "semantic_node_count": len(semantic_nodes["nodes"]),
        "question_packet_count": len(question_packets["packets"]),
        "release_decision": release["decision"],
        "artifacts": {
            "model_input_bundle": str(out_dir / "model_input_bundle.json"),
            "evidence_dir": str(evidence_dir),
            "model_outputs_dir": str(model_dir),
            "semantic_nodes": str(normalized_dir / "semantic_nodes.json"),
            "question_packets": str(normalized_dir / "question_packets.json"),
            "asset_manifest": str(normalized_dir / "asset_manifest.json"),
            "release_decision": str(normalized_dir / "release_decision.json"),
            "runtime_import_candidate": str(normalized_dir / "runtime_import_candidate.json"),
            "review_html": str(out_dir / "review.html"),
        },
    }
    write_json(out_dir / "run_summary.json", summary)
    write_review(out_dir / "review.html", summary, pages_payload, release)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
