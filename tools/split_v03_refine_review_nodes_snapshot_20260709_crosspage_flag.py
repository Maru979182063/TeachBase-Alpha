from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from PIL import Image

import vision_prompt_store
from tools.crop_executor_v03 import execute_crops_v03
from tools.cross_page_node_accumulator_v03 import NodeFragmentV03, SemanticNodeV03, write_nodes
from tools.page_render_adapter_v03 import PageManifestV03
from tools.question_slice_auditor_v03 import audit_nodes_v03, write_audit_report
from tools.split_pipeline_v03 import build_legacy_bridge, build_review_repair_pool, write_json


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
TARGET_REASONS = {"page_bottom_may_continue", "short_question_without_solution_evidence", "swallows_next_section"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _extract_json_block(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_object_not_found")
    return json.loads(clean[start : end + 1])


def _pil_image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _call_model(api_key: str, model: str, image: Image.Image, prompt: str, system_prompt: str) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _nodes_from_json(payload: dict[str, Any]) -> list[SemanticNodeV03]:
    nodes: list[SemanticNodeV03] = []
    for item in payload.get("nodes", []) or []:
        fragments = [
            NodeFragmentV03(
                int(fragment.get("page", 0) or 0),
                [int(v) for v in fragment.get("bbox_px", [])[:4]],
                str(fragment.get("role", "") or "fragment"),
                [str(v) for v in fragment.get("block_ids", []) or []],
                [str(v) for v in fragment.get("flags", []) or []],
            )
            for fragment in item.get("fragments", []) or []
            if len(fragment.get("bbox_px", []) or []) >= 4
        ]
        nodes.append(
            SemanticNodeV03(
                node_id=str(item.get("node_id", "") or ""),
                node_type=str(item.get("node_type", "") or ""),
                source=str(item.get("source", "") or "semantic_v03"),
                fragments=fragments,
                review_status=str(item.get("review_status", "") or "NEEDS_REVIEW"),
                text_stub=str(item.get("text_stub", "") or ""),
            )
        )
    return nodes


def _manifests_from_json(payload: dict[str, Any]) -> list[PageManifestV03]:
    pages = payload.get("pages", []) if isinstance(payload.get("pages"), list) else []
    return [PageManifestV03(**page) for page in pages]


def _audit_reason_map(payload: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for record in payload.get("records", []) or []:
        node_id = str(record.get("node_id", "") or "")
        if node_id:
            result[node_id] = [str(r) for r in record.get("reasons", []) or []]
    return result


def _union_bbox(fragments: list[NodeFragmentV03], page: int) -> list[int] | None:
    boxes = [f.bbox_px for f in fragments if f.page == page and len(f.bbox_px) >= 4]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _select_target_fragment(node: SemanticNodeV03, reasons: list[str]) -> tuple[int, NodeFragmentV03] | None:
    if not node.fragments:
        return None
    # Most split failures are at the tail: page-bottom continuation, next section swallowed,
    # or a short question whose evidence should extend downward from the current tail.
    indexed = list(enumerate(node.fragments))
    indexed.sort(key=lambda item: (item[1].page, item[1].bbox_px[1], item[1].bbox_px[0]))
    return indexed[-1]


def _band_for_fragment(fragment: NodeFragmentV03, manifest: PageManifestV03, reasons: list[str]) -> tuple[list[int], list[int]]:
    box = [int(v) for v in fragment.bbox_px[:4]]
    if len(box) < 4:
        return [0, 0, manifest.width_px, manifest.height_px], [0, 0, manifest.width_px, manifest.height_px]
    x0, y0, x1, y1 = box
    pad_x = int(manifest.width_px * 0.06)
    top_pad = int(manifest.height_px * 0.035)
    bottom_ratio = 0.10
    if "page_bottom_may_continue" in reasons:
        bottom_ratio = 0.18
    if "short_question_without_solution_evidence" in reasons:
        bottom_ratio = 0.24
    if "swallows_next_section" in reasons:
        bottom_ratio = max(bottom_ratio, 0.12)
    bottom_pad = int(manifest.height_px * bottom_ratio)
    band = [
        max(0, x0 - pad_x),
        max(0, y0 - top_pad),
        min(manifest.width_px, x1 + pad_x),
        min(manifest.height_px, y1 + bottom_pad),
    ]
    # Keep enough right/left margin for English answer/analysis labels and math diagrams.
    if band[2] - band[0] < manifest.width_px * 0.55:
        center = (band[0] + band[2]) // 2
        half = int(manifest.width_px * 0.32)
        band[0] = max(0, center - half)
        band[2] = min(manifest.width_px, center + half)
    return box, band


def _norm_bbox_in_band(box: list[int], band: list[int]) -> dict[str, int]:
    bw = max(1, band[2] - band[0])
    bh = max(1, band[3] - band[1])
    return {
        "x": int(round((box[0] - band[0]) * 1000 / bw)),
        "y": int(round((box[1] - band[1]) * 1000 / bh)),
        "w": int(round((box[2] - box[0]) * 1000 / bw)),
        "h": int(round((box[3] - box[1]) * 1000 / bh)),
    }


def _denorm_bbox_from_band(raw: dict[str, Any], band: list[int]) -> list[int] | None:
    try:
        x = float(raw.get("x", 0) or 0)
        y = float(raw.get("y", 0) or 0)
        w = float(raw.get("w", 0) or 0)
        h = float(raw.get("h", 0) or 0)
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    bw = max(1, band[2] - band[0])
    bh = max(1, band[3] - band[1])
    x0 = int(round(band[0] + x * bw / 1000))
    y0 = int(round(band[1] + y * bh / 1000))
    x1 = int(round(x0 + w * bw / 1000))
    y1 = int(round(y0 + h * bh / 1000))
    return [max(band[0], x0), max(band[1], y0), min(band[2], x1), min(band[3], y1)]


def _replace_fragment(
    node: SemanticNodeV03,
    fragment_index: int,
    bbox: list[int],
    manifest: PageManifestV03,
    extra_flags: list[str] | None = None,
) -> None:
    if fragment_index < 0 or fragment_index >= len(node.fragments):
        return
    old = node.fragments[fragment_index]
    flags = set([*old.flags, "split_node_refined_by_model", *(extra_flags or [])])
    # The original near-bottom flag is a candidate feature, not a permanent
    # truth. Once the model trims the fragment away from page bottom, clear it
    # so the auditor does not keep failing a repaired bbox on stale metadata.
    if len(bbox) >= 4 and int(bbox[3]) < int(manifest.height_px * 0.93):
        flags.discard("near_page_bottom")
    node.fragments[fragment_index] = NodeFragmentV03(
        page=old.page,
        bbox_px=bbox,
        role=old.role or "question_body",
        block_ids=old.block_ids,
        flags=sorted(flags),
    )
    node.fragments.sort(key=lambda f: (f.page, f.bbox_px[1], f.bbox_px[0]))
    node.source = f"{node.source}+split_node_refine"


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def refine_nodes(
    *,
    doc_dir: Path,
    semantic_nodes_path: Path,
    audit_path: Path,
    out_dir: Path,
    api_key: str,
    model: str,
    max_nodes: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = _nodes_from_json(read_json(semantic_nodes_path))
    manifests = _manifests_from_json(read_json(doc_dir / "page_manifests.json"))
    manifest_by_page = {m.page: m for m in manifests}
    reasons_by_node = _audit_reason_map(read_json(audit_path))
    bundle = vision_prompt_store.get_split_node_refine_prompt_bundle()

    actions: list[dict[str, Any]] = []
    calls = 0
    for node in nodes:
        if node.node_type != "question":
            continue
        reasons = reasons_by_node.get(node.node_id, [])
        if not TARGET_REASONS.intersection(reasons):
            continue
        if calls >= max_nodes:
            actions.append({"node_id": node.node_id, "action": "skipped_max_nodes", "reasons": reasons})
            continue
        target = _select_target_fragment(node, reasons)
        if target is None:
            actions.append({"node_id": node.node_id, "action": "missing_fragment", "reasons": reasons})
            continue
        fragment_index, target_fragment = target
        page = target_fragment.page
        manifest = manifest_by_page.get(page)
        if manifest is None:
            actions.append({"node_id": node.node_id, "action": "missing_manifest", "reasons": reasons})
            continue
        candidate_box, band = _band_for_fragment(target_fragment, manifest, reasons)
        with Image.open(manifest.page_image_master) as img:
            band_img = img.convert("RGB").crop(tuple(band))
        candidate_norm = _norm_bbox_in_band(candidate_box, band)
        prompt = vision_prompt_store.render_template(
            bundle["user_template"],
            {
                "NODE_ID": node.node_id,
                "DOC_KEY": manifest.doc_key,
                "PAGE": str(page),
                "FAILURE_REASONS": ", ".join(reasons),
                "CANDIDATE_BBOX_NORM": json.dumps(candidate_norm, ensure_ascii=False),
            },
        )
        debug_dir = out_dir / "debug_refine_inputs" / node.node_id
        debug_dir.mkdir(parents=True, exist_ok=True)
        input_path = debug_dir / f"{node.node_id}_f{fragment_index + 1:02d}_p{page:03d}_band.png"
        band_img.save(input_path)
        try:
            payload = _call_model(api_key, model, band_img, prompt, bundle["system_prompt"])
            calls += 1
        except Exception as exc:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "model_failed",
                    "reasons": reasons,
                    "error": str(exc)[:240],
                    "input_image": _portable(input_path, out_dir),
                }
            )
            continue
        refined = _denorm_bbox_from_band(payload.get("bbox", {}) if isinstance(payload.get("bbox"), dict) else {}, band)
        if not bool(payload.get("is_repaired", False)) or refined is None:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "needs_manual_review",
                    "reasons": reasons,
                    "model_payload": payload,
                    "input_image": _portable(input_path, out_dir),
                }
            )
            continue
        extra_flags = []
        if "page_bottom_may_continue" in reasons and not payload.get("review_flags"):
            extra_flags.append("cross_page_checked_no_continuation")
        _replace_fragment(node, fragment_index, refined, manifest, extra_flags)
        actions.append(
            {
                "node_id": node.node_id,
                "action": "refined_node_bbox",
                "reasons": reasons,
                "target_fragment_index": fragment_index,
                "target_fragment_role": target_fragment.role,
                "page": page,
                "old_bbox": candidate_box,
                "new_bbox": refined,
                "band_bbox": band,
                "model_payload": payload,
                "input_image": _portable(input_path, out_dir),
            }
        )

    crop_records = execute_crops_v03(nodes, manifests, out_dir / "docs" / "refined")
    audit_records = audit_nodes_v03(nodes)
    bridge = build_legacy_bridge([asdict(node) for node in nodes], crop_records)
    repair_pool = build_review_repair_pool([asdict(node) for node in nodes], crop_records, [asdict(record) for record in audit_records])
    write_nodes(out_dir / "semantic_nodes_refined.json", nodes)
    write_audit_report(out_dir / "audit_report_refined.json", audit_records)
    write_json(out_dir / "legacy_bridge_questions_refined.json", bridge)
    write_json(out_dir / "review_repair_pool_refined.json", repair_pool)
    write_json(out_dir / "split_node_refine_actions.json", actions)
    report = {
        "schema": "split_node_refine_report_v0.1",
        "doc_dir": str(doc_dir),
        "semantic_nodes_input": str(semantic_nodes_path),
        "audit_input": str(audit_path),
        "model": model,
        "actual_vlm_calls": calls,
        "action_counts": {action: sum(1 for item in actions if item.get("action") == action) for action in sorted({str(item.get("action")) for item in actions})},
        "ready_count": len(bridge["questions"]),
        "review_repair_pool_count": len(repair_pool["items"]),
        "artifacts": [
            str(out_dir / "semantic_nodes_refined.json"),
            str(out_dir / "audit_report_refined.json"),
            str(out_dir / "legacy_bridge_questions_refined.json"),
            str(out_dir / "review_repair_pool_refined.json"),
            str(out_dir / "split_node_refine_actions.json"),
            str(out_dir / "docs" / "refined" / "crop_manifest.json"),
        ],
    }
    write_json(out_dir / "split_node_refine_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Refine failed split_v03 semantic question nodes one candidate at a time.")
    parser.add_argument("--doc-dir", required=True)
    parser.add_argument("--semantic-nodes", required=True)
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--max-nodes", type=int, default=12)
    args = parser.parse_args()
    if not str(args.api_key or "").strip():
        raise SystemExit("missing_api_key")
    report = refine_nodes(
        doc_dir=Path(args.doc_dir).resolve(),
        semantic_nodes_path=Path(args.semantic_nodes).resolve(),
        audit_path=Path(args.audit_report).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        api_key=str(args.api_key or ""),
        model=str(args.model or ""),
        max_nodes=args.max_nodes,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
