from __future__ import annotations

import argparse
import html
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    return read_json(path)


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / path


def parse_page_number(ref: str) -> int | None:
    if not ref.startswith("p"):
        return None
    page_part = ref.split(":", 1)[0]
    digits = page_part[1:]
    if not digits.isdigit():
        return None
    return int(digits)


def block_ref_sort_key(ref: str) -> tuple[int, int, str]:
    page = parse_page_number(ref) or 0
    tail = ref.split(":", 1)[1] if ":" in ref else ""
    block_digits = ""
    for char in tail:
        if char.isdigit():
            block_digits += char
    order = int(block_digits) if block_digits else 0
    return page, order, ref


def normalize_ref(ref: str, page_blocks: dict[int, list[dict[str, Any]]]) -> str:
    if ref in {block["line_ref"] for blocks in page_blocks.values() for block in blocks}:
        return ref
    if ":" not in ref:
        return ref
    page = parse_page_number(ref)
    if page is None:
        return ref
    tail = ref.split(":", 1)[1]
    if tail.startswith("b") or tail.startswith("block_"):
        return ref
    if tail.isdigit():
        candidate = f"p{page:03d}:b{tail}"
        if any(block["line_ref"] == candidate for block in page_blocks.get(page, [])):
            return candidate
    return ref


@dataclass
class EvidenceIndex:
    doc_id: str
    evidence_bundle: dict[str, Any]
    page_blocks: dict[int, list[dict[str, Any]]]
    block_by_ref: dict[str, dict[str, Any]]
    page_images: dict[int, Path]

    @classmethod
    def load(cls, doc_dir: Path, vlm_doc_dir: Path, doc_id: str) -> "EvidenceIndex":
        evidence_bundle = read_json(doc_dir / "evidence_bundle.json")
        page_blocks: dict[int, list[dict[str, Any]]] = {}
        block_by_ref: dict[str, dict[str, Any]] = {}
        for page in evidence_bundle.get("pages", []):
            page_no = int(page.get("page", 0) or 0)
            blocks = list(page.get("blocks", []))
            page_blocks[page_no] = blocks
            for block in blocks:
                line_ref = str(block.get("line_ref", "") or "")
                if line_ref:
                    block_by_ref[line_ref] = block
        page_images: dict[int, Path] = {}
        for page_no in page_blocks:
            meta_path = vlm_doc_dir / f"page_{page_no:03d}" / "meta.json"
            if meta_path.exists():
                meta = read_json(meta_path)
                image_value = str(meta.get("image_path", "") or "")
                if image_value:
                    page_images[page_no] = workspace_path(image_value)
        return cls(
            doc_id=doc_id,
            evidence_bundle=evidence_bundle,
            page_blocks=page_blocks,
            block_by_ref=block_by_ref,
            page_images=page_images,
        )

    def source_text(self, refs: list[str]) -> tuple[str, list[str], list[str]]:
        normalized_refs: list[str] = []
        missing_refs: list[str] = []
        texts: list[str] = []
        seen: set[str] = set()
        for ref in sorted(refs, key=block_ref_sort_key):
            normalized = normalize_ref(str(ref), self.page_blocks)
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_refs.append(normalized)
            block = self.block_by_ref.get(normalized)
            if block is None:
                missing_refs.append(normalized)
                continue
            text = str(block.get("text", "") or "").strip()
            if text:
                texts.append(text)
        return "\n".join(texts).strip(), normalized_refs, missing_refs


def refs_pages(refs: list[str]) -> list[int]:
    pages: list[int] = []
    for ref in refs:
        page = parse_page_number(str(ref))
        if page is not None and page not in pages:
            pages.append(page)
    return sorted(pages)


def crop_for_refs(image: Image.Image, refs: list[str], page_blocks: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    width, height = image.size
    order_by_ref = {str(block.get("line_ref", "") or ""): index for index, block in enumerate(page_blocks, start=1)}
    orders = [order_by_ref[ref] for ref in refs if ref in order_by_ref]
    if not orders:
        return 0, 0, width, height
    total = max(len(page_blocks), 1)
    top_rank = max(min(orders) - 1, 1)
    bottom_rank = min(max(orders) + 1, total)
    top = int(height * ((top_rank - 0.75) / (total + 1)))
    bottom = int(height * ((bottom_rank + 0.75) / (total + 1)))
    top = max(0, min(top, height - 1))
    bottom = max(top + 40, min(bottom, height))
    return 0, top, width, bottom


def asset_id_for(doc_id: str, unit_id: str, visual_ref: str, page: int) -> str:
    safe_ref = visual_ref.replace(":", "_").replace("\\", "_").replace("/", "_")
    return f"{doc_id}_{unit_id}_p{page:03d}_{safe_ref}"


def visual_ref_for_page(visual_refs: list[str], page: int) -> str:
    page_token = f"page_{page:03d}"
    for visual_ref in visual_refs:
        if page_token in str(visual_ref):
            return str(visual_ref)
    return str(visual_refs[0]) if visual_refs else f"source_page_{page:03d}_crop_required"


def build_asset_manifest(
    *,
    doc_id: str,
    units: list[dict[str, Any]],
    evidence: EvidenceIndex,
    out_dir: Path,
) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    asset_dir = out_dir / doc_id / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for unit in units:
        if unit.get("unit_type") not in {"visual_unit", "writing_surface"}:
            continue
        source_refs = [normalize_ref(str(ref), evidence.page_blocks) for ref in unit.get("source_refs", [])]
        pages = refs_pages(source_refs)
        visual_refs = list(unit.get("visual_refs", []) or [])
        if not visual_refs:
            visual_refs = [f"{doc_id}_{unit.get('unit_id')}_visual_asset"]
        for page in pages or [0]:
            image_path = evidence.page_images.get(page)
            if not image_path or not image_path.exists():
                assets.append(
                    {
                        "asset_id": f"{doc_id}_{unit.get('unit_id')}_missing_page_{page}",
                        "doc_id": doc_id,
                        "unit_id": unit.get("unit_id"),
                        "status": "MISSING_SOURCE_IMAGE",
                        "source_refs": source_refs,
                        "visual_refs": visual_refs,
                        "release_eligible": False,
                    }
                )
                continue
            image = Image.open(image_path).convert("RGB")
            page_refs = [ref for ref in source_refs if parse_page_number(ref) == page]
            crop_box = crop_for_refs(image, page_refs, evidence.page_blocks.get(page, []))
            crop = image.crop(crop_box)
            visual_ref = visual_ref_for_page(visual_refs, page)
            asset_id = asset_id_for(doc_id, str(unit.get("unit_id", "unit")), str(visual_ref), page)
            rel_path = Path(doc_id) / "assets" / f"{asset_id}.png"
            crop.save(out_dir / rel_path)
            assets.append(
                {
                    "asset_id": asset_id,
                    "doc_id": doc_id,
                    "unit_id": unit.get("unit_id"),
                    "title": unit.get("title", ""),
                    "unit_type": unit.get("unit_type"),
                    "role_tags": unit.get("role_tags", []),
                    "relation_to_parent": unit.get("relation_to_parent", ""),
                    "parent_hint": unit.get("parent_hint", ""),
                    "source_refs": source_refs,
                    "visual_refs": visual_refs,
                    "source_page": page,
                    "source_image": str(image_path),
                    "asset_path": str(rel_path).replace("\\", "/"),
                    "crop_box_px": list(crop_box),
                    "crop_method": "rough_block_order_from_vlm_blocks",
                    "needs_precise_bbox": True,
                    "release_eligible": False,
                }
            )
    manifest = {
        "schema": "english_text_first_v05.asset_manifest",
        "doc_id": doc_id,
        "asset_count": len(assets),
        "assets": assets,
        "release_note": "Assets are real image files, but crop boxes are rough because upstream evidence has no numeric bbox.",
    }
    write_json(out_dir / doc_id / "asset_manifest.json", manifest)
    return manifest


def latest_passage_unit(units: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    for prior in reversed(units[:index]):
        tags = set(prior.get("role_tags", []) or [])
        relation = str(prior.get("relation_to_parent", "") or "")
        if "passage_companion" in tags or relation == "passage_companion":
            return prior
    return None


def solution_units_for(units: list[dict[str, Any]], question_index: int, question_unit_id: str) -> list[dict[str, Any]]:
    explicit = [
        other
        for other in units
        if other.get("unit_type") == "solution_unit"
        and str(other.get("parent_hint", "") or "") == question_unit_id
        and str(other.get("relation_to_parent", "") or "") == "solution_for"
    ]
    if explicit:
        return explicit
    fallback: list[dict[str, Any]] = []
    for other in units[question_index + 1 :]:
        unit_type = other.get("unit_type")
        if unit_type == "question_like_unit":
            break
        if unit_type == "solution_unit" and str(other.get("relation_to_parent", "") or "") == "solution_for":
            fallback.append(other)
            break
    return fallback


def family_for(doc_id: str, unit: dict[str, Any]) -> str:
    tags = set(unit.get("role_tags", []) or [])
    if doc_id.startswith("reading"):
        return "reading"
    if doc_id.startswith("grammar"):
        return "grammar"
    if "writing_prompt" in tags:
        return "writing"
    if "vocabulary" in tags or "vocabulary_drill" in tags:
        return "vocabulary"
    if doc_id.startswith("writing"):
        return "writing_or_drill"
    return "unknown"


def build_packet_candidates(
    *,
    doc_id: str,
    units: list[dict[str, Any]],
    evidence: EvidenceIndex,
    asset_manifest: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    assets_by_parent: dict[str, list[dict[str, Any]]] = {}
    for asset in asset_manifest.get("assets", []):
        parent = str(asset.get("parent_hint", "") or "")
        if parent:
            assets_by_parent.setdefault(parent, []).append(asset)

    candidates: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        if unit.get("unit_type") != "question_like_unit":
            continue
        unit_id = str(unit.get("unit_id", "") or "")
        family = family_for(doc_id, unit)
        q_text, q_refs, q_missing = evidence.source_text(list(unit.get("source_refs", []) or []))
        solution_units = solution_units_for(units, index, unit_id)
        solution_refs: list[str] = []
        for solution in solution_units:
            solution_refs.extend(list(solution.get("source_refs", []) or []))
        solution_text, normalized_solution_refs, solution_missing = evidence.source_text(solution_refs)
        passage_unit = latest_passage_unit(units, index) if family == "reading" else None
        passage_text = ""
        passage_refs: list[str] = []
        passage_missing: list[str] = []
        if passage_unit:
            passage_text, passage_refs, passage_missing = evidence.source_text(list(passage_unit.get("source_refs", []) or []))

        related_assets = assets_by_parent.get(unit_id, [])
        hold_reasons: list[str] = []
        if str(unit.get("completeness", "") or "") != "complete":
            hold_reasons.append("question_unit_not_complete")
        if not q_text:
            hold_reasons.append("missing_question_text")
        if q_missing:
            hold_reasons.append("missing_question_evidence_refs")
        if solution_missing:
            hold_reasons.append("missing_solution_evidence_refs")
        if family in {"reading", "grammar", "writing", "vocabulary"} and not solution_text:
            hold_reasons.append("missing_solution_unit")
        if family == "reading" and not passage_text:
            hold_reasons.append("missing_passage_context")
        if family == "writing" and not related_assets:
            hold_reasons.append("missing_writing_surface_asset")
        if any(asset.get("needs_precise_bbox") for asset in related_assets):
            hold_reasons.append("visual_asset_needs_precise_bbox")
        if family == "grammar" and "stem_companion" in set(unit.get("facets", []) or []):
            hold_reasons.append("embedded_knowledge_check_needs_parent_node")

        packet = {
            "packet_id": f"{doc_id}_{unit_id}",
            "doc_id": doc_id,
            "source_unit_id": unit_id,
            "packet_family": family,
            "title": unit.get("title", ""),
            "release_status": "HOLD" if hold_reasons else "READY",
            "hold_reasons": hold_reasons,
            "source_text_exact": {
                "passage": passage_text,
                "stem": q_text,
                "solution": solution_text,
            },
            "evidence": {
                "passage_refs": passage_refs,
                "question_refs": q_refs,
                "solution_refs": normalized_solution_refs,
                "missing_refs": q_missing + solution_missing + passage_missing,
                "pages": sorted(set(refs_pages(q_refs) + refs_pages(normalized_solution_refs) + refs_pages(passage_refs))),
            },
            "related_assets": [
                {
                    "asset_id": asset.get("asset_id"),
                    "asset_path": asset.get("asset_path"),
                    "relation_to_parent": asset.get("relation_to_parent"),
                    "release_eligible": asset.get("release_eligible"),
                    "needs_precise_bbox": asset.get("needs_precise_bbox"),
                }
                for asset in related_assets
            ],
            "builder_policy": "exact_source_copy_only",
        }
        candidates.append(packet)
        if hold_reasons:
            holds.append({"packet_id": packet["packet_id"], "hold_reasons": hold_reasons})

    result = {
        "schema": "english_text_first_v05.question_packet_candidates",
        "doc_id": doc_id,
        "candidate_count": len(candidates),
        "ready_count": sum(1 for item in candidates if item["release_status"] == "READY"),
        "hold_count": sum(1 for item in candidates if item["release_status"] == "HOLD"),
        "packets": candidates,
        "holds": holds,
    }
    write_json(out_dir / doc_id / "question_packet_candidates.json", result)
    return result


def build_semantic_nodes(doc_id: str, units: list[dict[str, Any]], evidence: EvidenceIndex, out_dir: Path) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for unit in units:
        text, refs, missing = evidence.source_text(list(unit.get("source_refs", []) or []))
        nodes.append(
            {
                "node_id": f"{doc_id}_{unit.get('unit_id')}",
                "doc_id": doc_id,
                "source_unit_id": unit.get("unit_id"),
                "node_type": unit.get("unit_type"),
                "title": unit.get("title", ""),
                "role_tags": unit.get("role_tags", []),
                "facets": unit.get("facets", []),
                "relation_to_parent": unit.get("relation_to_parent", ""),
                "parent_hint": unit.get("parent_hint", ""),
                "completeness": unit.get("completeness", ""),
                "source_text_exact": text,
                "evidence": {
                    "line_refs": refs,
                    "missing_refs": missing,
                    "pages": refs_pages(refs),
                },
                "visual_refs": unit.get("visual_refs", []),
            }
        )
    result = {"schema": "english_text_first_v05.semantic_nodes", "doc_id": doc_id, "semantic_nodes": nodes}
    write_json(out_dir / doc_id / "semantic_nodes.json", result)
    return result


def compare_existing_outputs(doc_id: str, v03_dir: Path, v04_dir: Path) -> dict[str, Any]:
    v03_packets = read_json(v03_dir / doc_id / "question_packets.json")
    v04_packets = read_json(v04_dir / doc_id / "question_packets.json")
    v03_items = v03_packets.get("question_packets", []) if isinstance(v03_packets, dict) else v03_packets
    v04_items = v04_packets.get("question_packets", []) if isinstance(v04_packets, dict) else v04_packets
    return {
        "doc_id": doc_id,
        "v03b": {
            "packet_count": len(v03_items),
            "failure_count": len(v03_packets.get("failures", [])) if isinstance(v03_packets, dict) else 0,
            "shape_note": "semantic grouping useful, not runtime-safe",
        },
        "v04c": {
            "packet_count": len(v04_items),
            "failure_count": len(v04_packets.get("failures", [])) if isinstance(v04_packets, dict) else 0,
            "shape_note": "schema-shaped, semantic boundary can be worse",
        },
    }


def write_review_html(out_dir: Path, doc_results: list[dict[str, Any]]) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>English Text First v0.5 Review</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.45} pre{white-space:pre-wrap;background:#f7f7f7;padding:12px;border:1px solid #ddd} img{max-width:360px;border:1px solid #ddd;margin:8px 0} .hold{color:#a40000}.ready{color:#0b6b2a}.asset{display:inline-block;vertical-align:top;margin:8px 18px 8px 0}</style>",
        "<h1>English Text First v0.5 Review</h1>",
    ]
    for result in doc_results:
        doc_id = result["doc_id"]
        packets = result["packets"]["packets"]
        assets = result["assets"]["assets"]
        parts.append(f"<h2>{html.escape(doc_id)}</h2>")
        parts.append(
            f"<p>packets: {len(packets)}; ready: {result['packets']['ready_count']}; hold: {result['packets']['hold_count']}; assets: {len(assets)}</p>"
        )
        parts.append("<h3>Assets</h3>")
        for asset in assets[:12]:
            path = str(asset.get("asset_path", ""))
            parts.append("<div class='asset'>")
            parts.append(f"<div>{html.escape(str(asset.get('asset_id', '')))}</div>")
            if path:
                parts.append(f"<img src='{html.escape(path)}'>")
            parts.append(f"<pre>{html.escape(json.dumps(asset, ensure_ascii=False, indent=2))}</pre>")
            parts.append("</div>")
        parts.append("<h3>Packets</h3>")
        for packet in packets:
            css = "ready" if packet["release_status"] == "READY" else "hold"
            parts.append(f"<h4 class='{css}'>{html.escape(packet['packet_id'])} - {packet['release_status']}</h4>")
            parts.append(f"<pre>{html.escape(json.dumps(packet, ensure_ascii=False, indent=2))}</pre>")
    (out_dir / "review.html").write_text("\n".join(parts), encoding="utf-8")


def run_pipeline(config_path: Path, out_dir_arg: str | None) -> dict[str, Any]:
    config = load_config(config_path)
    input_roots = config["input_roots"]
    vlm_root = workspace_path(input_roots["vlm_transcriber"])
    v04_root = workspace_path(input_roots["unit_and_v04c"])
    v03_root = workspace_path(input_roots["semantic_reference_v03b"])
    out_dir = workspace_path(out_dir_arg or config["owned_output_root"])
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, out_dir / "english_text_first_v05.config.snapshot.json")

    doc_results: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for doc_id in config["documents"]:
        doc_v04_dir = v04_root / doc_id
        units = read_json(doc_v04_dir / "unit_bundle.json").get("units", [])
        evidence = EvidenceIndex.load(doc_v04_dir, vlm_root / doc_id, doc_id)
        assets = build_asset_manifest(doc_id=doc_id, units=units, evidence=evidence, out_dir=out_dir)
        semantic_nodes = build_semantic_nodes(doc_id, units, evidence, out_dir)
        packets = build_packet_candidates(
            doc_id=doc_id,
            units=units,
            evidence=evidence,
            asset_manifest=assets,
            out_dir=out_dir,
        )
        comparison = compare_existing_outputs(doc_id, v03_root, v04_root)
        comparisons.append(comparison)
        doc_results.append(
            {
                "doc_id": doc_id,
                "assets": assets,
                "semantic_nodes": semantic_nodes,
                "packets": packets,
                "comparison": comparison,
            }
        )

    summary = {
        "schema": "english_text_first_v05.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": str(config_path),
        "out_dir": str(out_dir),
        "model_calls_this_run": 0,
        "runtime_import_enabled": False,
        "docs": {
            item["doc_id"]: {
                "semantic_nodes": len(item["semantic_nodes"]["semantic_nodes"]),
                "assets": item["assets"]["asset_count"],
                "packet_candidates": item["packets"]["candidate_count"],
                "ready_packets": item["packets"]["ready_count"],
                "hold_packets": item["packets"]["hold_count"],
            }
            for item in doc_results
        },
        "comparisons": comparisons,
        "global_notes": [
            "This run uses existing VLM/unit outputs and does not call a model.",
            "Question packet candidates are exact source-copy candidates, not final Runtime imports.",
            "Visual assets are real image files but use rough block-order crops because upstream evidence lacks numeric bbox.",
        ],
    }
    write_json(out_dir / "run_summary.json", summary)
    write_review_html(out_dir, doc_results)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated English image-PDF text-first v0.5 pipeline.")
    parser.add_argument("--config", default="config/english_text_first_v05.yaml")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    summary = run_pipeline(workspace_path(args.config), args.out or None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
