from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CORE_PREDICATES = {"contains", "depends_on", "continues_on", "answers", "shares_context", "uses_asset", "other"}
MAPPING_VERSION = "english_text_first_sidecar_v01.normalized_hint_mapping"
SCHEMA_VERSION = "english_text_first_sidecar_v01"
MOJIBAKE_MARKERS = ("�", "Ã", "Â", "妯″", "闂ㄩ", "绛旀", "鍥界", "蹇冩", "瑙ｆ")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def parse_page_number(ref: str) -> int | None:
    if not ref.startswith("p") or ":" not in ref:
        return None
    token = ref.split(":", 1)[0][1:]
    return int(token) if token.isdigit() else None


def refs_pages(refs: list[str]) -> list[int]:
    pages: list[int] = []
    for ref in refs:
        page = parse_page_number(str(ref))
        if page is not None and page not in pages:
            pages.append(page)
    return sorted(pages)


def has_mojibake(value: str) -> bool:
    return any(marker in value for marker in MOJIBAKE_MARKERS)


def join_block_text(blocks: list[dict[str, Any]], refs: list[str]) -> str:
    block_by_ref = {str(block.get("line_ref", "")): block for block in blocks}
    lines: list[str] = []
    for ref in refs:
        text = str(block_by_ref.get(str(ref), {}).get("text", "") or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def object_id(doc_id: str, unit_id: str) -> str:
    return f"{doc_id}:{unit_id}"


def page_id(doc_id: str, page_no: int) -> str:
    return f"{doc_id}:page_{page_no:03d}"


def region_id(doc_id: str, line_ref: str) -> str:
    return f"{doc_id}:{line_ref}"


def asset_object_id(doc_id: str, asset_id: str) -> str:
    return f"{doc_id}:asset:{asset_id}"


@dataclass
class DocInputs:
    doc_id: str
    units: list[dict[str, Any]]
    evidence_bundle: dict[str, Any]
    vlm_doc_dir: Path
    base_doc_dir: Path
    model_gate_doc_dir: Path

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return list(self.evidence_bundle.get("flat_blocks", []))


def load_doc_inputs(args: argparse.Namespace, doc_id: str) -> DocInputs:
    unit_root = workspace_path(args.unit_root)
    vlm_root = workspace_path(args.vlm_root)
    base_root = workspace_path(args.base_root)
    model_gate_root = workspace_path(args.model_gate_root)
    unit_doc = unit_root / doc_id
    return DocInputs(
        doc_id=doc_id,
        units=list(read_json(unit_doc / "unit_bundle.json").get("units", [])),
        evidence_bundle=read_json(unit_doc / "evidence_bundle.json"),
        vlm_doc_dir=vlm_root / doc_id,
        base_doc_dir=base_root / doc_id,
        model_gate_doc_dir=model_gate_root / doc_id,
    )


def load_asset_manifest(doc: DocInputs) -> dict[str, Any]:
    path = doc.base_doc_dir / "asset_manifest.json"
    return read_json(path) if path.exists() else {"assets": []}


def load_packet_candidates(doc: DocInputs) -> dict[str, Any]:
    path = doc.model_gate_doc_dir / "model_gated_question_packet_candidates.json"
    if path.exists():
        return read_json(path)
    fallback = doc.base_doc_dir / "question_packet_candidates.json"
    return read_json(fallback) if fallback.exists() else {"packets": []}


def load_human_review(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"packets": []}
    return read_json(path)


def page_image_meta(doc: DocInputs, page_no: int) -> dict[str, Any]:
    meta_path = doc.vlm_doc_dir / f"page_{page_no:03d}" / "meta.json"
    meta = read_json(meta_path) if meta_path.exists() else {}
    image_value = str(meta.get("image_path", "") or "")
    image_path = workspace_path(image_value) if image_value else Path()
    width = height = None
    image_exists = bool(image_path and image_path.exists())
    if image_exists:
        with Image.open(image_path) as image:
            width, height = image.size
    return {
        "page_id": page_id(doc.doc_id, page_no),
        "doc_id": doc.doc_id,
        "page_number": page_no,
        "image_path": rel_workspace(image_path) if image_value else "",
        "image_exists": image_exists,
        "width_px": width,
        "height_px": height,
        "adjacent_page_ids": [
            page_id(doc.doc_id, page)
            for page in (page_no - 1, page_no + 1)
            if 1 <= page <= len(doc.evidence_bundle.get("pages", []))
        ],
        "vlm_model": meta.get("model", ""),
        "vlm_meta_path": rel_workspace(meta_path),
        "prompt_or_model_version": {
            "source": "existing_vlm_transcriber_meta",
            "model": meta.get("model", ""),
            "finish_reason": meta.get("finish_reason", ""),
        },
    }


def build_source_evidence(doc: DocInputs, assets: dict[str, Any]) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []
    blocks_by_page: dict[int, list[dict[str, Any]]] = {}
    for page in doc.evidence_bundle.get("pages", []):
        page_no = int(page.get("page", 0) or 0)
        blocks = list(page.get("blocks", []))
        blocks_by_page[page_no] = blocks
        page_meta = page_image_meta(doc, page_no)
        page_text = "\n".join(str(block.get("text", "") or "") for block in blocks)
        page_meta["transcription"] = {
            "block_count": len(blocks),
            "text_sha1": sha1_text(page_text),
            "has_mojibake": has_mojibake(page_text),
        }
        pages.append(page_meta)
        for order, block in enumerate(blocks, start=1):
            line_ref = str(block.get("line_ref", "") or "")
            regions.append(
                {
                    "region_id": region_id(doc.doc_id, line_ref),
                    "doc_id": doc.doc_id,
                    "page_id": page_id(doc.doc_id, page_no),
                    "page_number": page_no,
                    "line_ref": line_ref,
                    "block_id": block.get("block_id", ""),
                    "label": block.get("label", ""),
                    "order_index": order,
                    "text": block.get("text", ""),
                    "text_sha1": sha1_text(str(block.get("text", "") or "")),
                    "bbox": None,
                    "polygon": None,
                    "coordinate_status": "NO_NUMERIC_COORDINATE",
                    "coordinate_system": "page_px_unknown_bbox",
                    "has_mojibake": has_mojibake(str(block.get("text", "") or "")),
                }
            )
    asset_refs: list[dict[str, Any]] = []
    for asset in assets.get("assets", []):
        asset_path_value = str(asset.get("asset_path", "") or "")
        asset_path = doc.base_doc_dir.parent / asset_path_value if asset_path_value else Path()
        source_page = int(asset.get("source_page", 0) or 0)
        source_image = workspace_path(str(asset.get("source_image", "") or "")) if asset.get("source_image") else Path()
        asset_refs.append(
            {
                "asset_ref_id": asset_object_id(doc.doc_id, str(asset.get("asset_id", ""))),
                "asset_id": asset.get("asset_id", ""),
                "doc_id": doc.doc_id,
                "unit_id": asset.get("unit_id", ""),
                "asset_path": rel_workspace(asset_path) if asset_path_value else "",
                "asset_exists": bool(asset_path_value and asset_path.exists()),
                "source_image": rel_workspace(source_image) if str(source_image) else "",
                "source_image_exists": bool(source_image and source_image.exists()),
                "source_page_id": page_id(doc.doc_id, source_page) if source_page else "",
                "source_refs": asset.get("source_refs", []),
                "crop_box_px": asset.get("crop_box_px"),
                "crop_method": asset.get("crop_method", ""),
                "crop_precision": "ROUGH_DERIVED_VIEW" if asset.get("needs_precise_bbox") else "DECLARED_PRECISE",
                "fallback_source_page_ref": page_id(doc.doc_id, source_page) if source_page else "",
                "is_original_fact_source": False,
                "source_page_is_fact_source": True,
            }
        )
    return {"pages": pages, "regions": regions, "assets": asset_refs}


def normalized_hints_for(unit: dict[str, Any]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    unit_type = str(unit.get("unit_type", "") or "")
    if unit_type:
        hints.append(
            {
                "hint": unit_type,
                "confidence": 0.99,
                "mapping_version": MAPPING_VERSION,
                "source": "v05_unit_bundle.unit_type",
                "not_semantic_fact": True,
                "not_gate_input": True,
            }
        )
    for tag in unit.get("role_tags", []) or []:
        hints.append(
            {
                "hint": str(tag),
                "confidence": 0.72,
                "mapping_version": MAPPING_VERSION,
                "source": "v05_unit_bundle.role_tags",
                "not_semantic_fact": True,
                "not_gate_input": True,
            }
        )
    return hints


def semantic_status_for(unit: dict[str, Any]) -> str:
    completeness = str(unit.get("completeness", "") or "")
    if completeness in {"open_tail", "fragment"}:
        return "INCOMPLETE_SOURCE"
    if not unit.get("source_refs"):
        return "AMBIGUOUS"
    return "COMPLETE"


def evidence_status_for(text: str, refs: list[str], pages: list[int], source_evidence: dict[str, Any]) -> str:
    if has_mojibake(text):
        return "ENCODING_ERROR"
    page_by_number = {int(page.get("page_number", 0) or 0): page for page in source_evidence["pages"]}
    if not refs:
        return "INCOMPLETE_SOURCE"
    if any(not page_by_number.get(page, {}).get("image_exists") for page in pages):
        return "PARTIAL_ASSET"
    return "COMPLETE"


def object_kind_open_text(unit: dict[str, Any]) -> str:
    title = str(unit.get("title", "") or "").strip()
    unit_type = str(unit.get("unit_type", "") or "").strip()
    if title and unit_type:
        return f"{title} ({unit_type} observation)"
    return title or unit_type or "untyped source object"


def build_semantic_objects(doc: DocInputs, source_evidence: dict[str, Any], assets: dict[str, Any]) -> list[dict[str, Any]]:
    all_blocks = doc.blocks
    asset_by_unit: dict[str, list[dict[str, Any]]] = {}
    for asset in source_evidence["assets"]:
        asset_by_unit.setdefault(str(asset.get("unit_id", "") or ""), []).append(asset)
    objects: list[dict[str, Any]] = []
    for unit in doc.units:
        unit_id = str(unit.get("unit_id", "") or "")
        refs = [str(ref) for ref in unit.get("source_refs", []) or []]
        pages = refs_pages(refs)
        text = join_block_text(all_blocks, refs)
        evidence_refs = [region_id(doc.doc_id, ref) for ref in refs]
        related_assets = asset_by_unit.get(unit_id, [])
        obj = {
            "id": object_id(doc.doc_id, unit_id),
            "doc_id": doc.doc_id,
            "source_unit_id": unit_id,
            "kind": {
                "open_text": object_kind_open_text(unit),
                "model_description": str(unit.get("title", "") or ""),
                "kind_is_open_world": True,
            },
            "observations": [
                {
                    "label": str(unit.get("unit_type", "") or "unknown_unit"),
                    "confidence": 0.99,
                    "source": "v05_unit_bundle",
                    "observation_version": "v05",
                }
            ],
            "normalized_hints": normalized_hints_for(unit),
            "title": unit.get("title", ""),
            "source_text": text,
            "source_text_sha1": sha1_text(text),
            "evidence_refs": evidence_refs,
            "line_refs": refs,
            "page_ids": [page_id(doc.doc_id, page) for page in pages],
            "pages": pages,
            "visual_refs": unit.get("visual_refs", []),
            "asset_refs": [asset["asset_ref_id"] for asset in related_assets],
            "raw_unit": unit,
            "semantic_status": semantic_status_for(unit),
            "evidence_status": evidence_status_for(text, refs, pages, source_evidence),
            "uncertainty": {
                "confidence": 0.78 if str(unit.get("completeness", "") or "") == "complete" else 0.52,
                "unknowns": [] if str(unit.get("completeness", "") or "") == "complete" else ["source_continuation_or_fragment_unresolved"],
            },
            "model_prompt_schema_version": {
                "composer": SCHEMA_VERSION,
                "upstream_unit_source": "existing_v05_unit_bundle",
                "new_model_call": False,
            },
        }
        objects.append(obj)
    for asset in source_evidence["assets"]:
        objects.append(
            {
                "id": asset["asset_ref_id"],
                "doc_id": doc.doc_id,
                "source_unit_id": asset.get("unit_id", ""),
                "kind": {
                    "open_text": "derived visual crop with source page fallback",
                    "model_description": "Existing rough crop retained as derivative view; original page remains fact source.",
                    "kind_is_open_world": True,
                },
                "observations": [
                    {
                        "label": "visual_asset_observation",
                        "confidence": 0.99,
                        "source": "v05_asset_manifest",
                        "observation_version": "v05",
                    }
                ],
                "normalized_hints": [
                    {
                        "hint": "visual_asset",
                        "confidence": 0.9,
                        "mapping_version": MAPPING_VERSION,
                        "source": "v05_asset_manifest",
                        "not_semantic_fact": True,
                        "not_gate_input": True,
                    }
                ],
                "title": asset.get("asset_id", ""),
                "source_text": "",
                "source_text_sha1": sha1_text(""),
                "evidence_refs": list(asset.get("source_refs", [])),
                "line_refs": list(asset.get("source_refs", [])),
                "page_ids": [asset.get("source_page_id", "")] if asset.get("source_page_id") else [],
                "pages": [parse_page_number(str(ref)) for ref in asset.get("source_refs", []) if parse_page_number(str(ref))],
                "visual_refs": [asset.get("asset_ref_id", "")],
                "asset_refs": [asset.get("asset_ref_id", "")],
                "raw_asset_ref": asset,
                "semantic_status": "COMPLETE",
                "evidence_status": "COMPLETE" if asset.get("source_image_exists") else "PARTIAL_ASSET",
                "uncertainty": {
                    "confidence": 0.7,
                    "unknowns": ["crop_is_derivative_rough_view"] if asset.get("crop_precision") == "ROUGH_DERIVED_VIEW" else [],
                },
                "model_prompt_schema_version": {
                    "composer": SCHEMA_VERSION,
                    "upstream_asset_source": "existing_v05_asset_manifest",
                    "new_model_call": False,
                },
            }
        )
    return objects


def add_claim(
    claims: list[dict[str, Any]],
    *,
    doc_id: str,
    subject: str,
    predicate: str,
    obj: str,
    reason: str,
    evidence_refs: list[str],
    confidence: float,
    open_text: str = "",
    source: str = "sidecar_graph_composer",
) -> None:
    if predicate not in CORE_PREDICATES:
        predicate = "other"
    claims.append(
        {
            "id": f"{doc_id}:claim_{len(claims) + 1:04d}",
            "doc_id": doc_id,
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "predicate_open_text": open_text or predicate,
            "reason": reason,
            "evidence_refs": evidence_refs,
            "confidence": confidence,
            "source": source,
            "schema_version": SCHEMA_VERSION,
        }
    )


def previous_context_unit(units: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    current_pages = refs_pages([str(ref) for ref in units[index].get("source_refs", []) or []])
    current_first_page = current_pages[0] if current_pages else None
    candidates: list[dict[str, Any]] = []
    for prior in reversed(units[:index]):
        if prior.get("unit_type") != "content_unit":
            continue
        prior_pages = refs_pages([str(ref) for ref in prior.get("source_refs", []) or []])
        if current_first_page is None or not prior_pages or prior_pages[-1] <= current_first_page:
            candidates.append(prior)
        if len(candidates) >= 3:
            break
    if not candidates:
        return None
    for candidate in candidates:
        tags = set(candidate.get("role_tags", []) or [])
        if {"grammar_knowledge", "methodology", "knowledge_background", "course_intro"} & tags:
            return candidate
    return candidates[0]


def latest_passage_like_context(units: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    for prior in reversed(units[:index]):
        tags = set(prior.get("role_tags", []) or [])
        relation = str(prior.get("relation_to_parent", "") or "")
        if "passage_companion" in tags or relation == "passage_companion":
            return prior
    return None


def previous_question_observation(units: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    for prior in reversed(units[:index]):
        if str(prior.get("unit_type", "") or "") == "question_like_unit":
            return prior
    return None


def build_semantic_claims(doc: DocInputs, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    unit_by_id = {str(unit.get("unit_id", "") or ""): unit for unit in doc.units}
    object_ids = {obj["id"] for obj in objects}
    for index, unit in enumerate(doc.units):
        unit_id = str(unit.get("unit_id", "") or "")
        subject = object_id(doc.doc_id, unit_id)
        refs = [region_id(doc.doc_id, str(ref)) for ref in unit.get("source_refs", []) or []]
        parent_hint = str(unit.get("parent_hint", "") or "")
        relation = str(unit.get("relation_to_parent", "") or "")
        resolved_parent_hint = parent_hint if parent_hint in unit_by_id else ""
        if relation == "solution_for" and not resolved_parent_hint:
            previous_question = previous_question_observation(doc.units, index)
            if previous_question:
                resolved_parent_hint = str(previous_question.get("unit_id", "") or "")
        if resolved_parent_hint:
            parent_obj = object_id(doc.doc_id, resolved_parent_hint)
            if relation == "solution_for":
                add_claim(
                    claims,
                    doc_id=doc.doc_id,
                    subject=subject,
                    predicate="answers",
                    obj=parent_obj,
                    reason="Upstream unit declares a solution/reference answer; when parent_hint is not a stable unit id, the composer uses nearest prior question observation in source order.",
                    evidence_refs=refs,
                    confidence=0.93 if parent_hint in unit_by_id else 0.81,
                    open_text=relation,
                    source="v05_unit_relation",
                )
            elif relation == "part_of_question":
                add_claim(
                    claims,
                    doc_id=doc.doc_id,
                    subject=parent_obj,
                    predicate="uses_asset",
                    obj=subject,
                    reason="Upstream unit declares this visual/surface object as part of the target activity.",
                    evidence_refs=refs,
                    confidence=0.9,
                    open_text=relation,
                    source="v05_unit_relation",
                )
            elif relation == "companion_for":
                add_claim(
                    claims,
                    doc_id=doc.doc_id,
                    subject=parent_obj,
                    predicate="contains",
                    obj=subject,
                    reason="Upstream unit declares this object as companion material for the target object.",
                    evidence_refs=refs,
                    confidence=0.84,
                    open_text=relation,
                    source="v05_unit_relation",
                )
            else:
                add_claim(
                    claims,
                    doc_id=doc.doc_id,
                    subject=subject,
                    predicate="other",
                    obj=parent_obj,
                    reason="Upstream unit declares an open relation to a parent hint.",
                    evidence_refs=refs,
                    confidence=0.74,
                    open_text=relation or "parent_hint",
                    source="v05_unit_relation",
                )
        if str(unit.get("unit_type", "") or "") == "visual_unit":
            for obj in objects:
                if obj.get("source_unit_id") == unit_id and obj["id"].startswith(f"{doc.doc_id}:asset:"):
                    add_claim(
                        claims,
                        doc_id=doc.doc_id,
                        subject=subject,
                        predicate="uses_asset",
                        obj=obj["id"],
                        reason="Visual object has a derived asset view and a source page fallback.",
                        evidence_refs=refs,
                        confidence=0.88,
                        open_text="has_derivative_asset_view",
                        source="v05_asset_manifest",
                    )
        if str(unit.get("unit_type", "") or "") == "question_like_unit":
            passage = latest_passage_like_context(doc.units, index)
            if passage:
                add_claim(
                    claims,
                    doc_id=doc.doc_id,
                    subject=subject,
                    predicate="shares_context",
                    obj=object_id(doc.doc_id, str(passage.get("unit_id", ""))),
                    reason="Question-like observation follows the latest passage/context object in page order.",
                    evidence_refs=refs + [region_id(doc.doc_id, str(ref)) for ref in passage.get("source_refs", []) or []],
                    confidence=0.78,
                    open_text="shares_prior_context",
                )
            if "stem_companion" in set(unit.get("facets", []) or []):
                context = previous_context_unit(doc.units, index)
                if context:
                    add_claim(
                        claims,
                        doc_id=doc.doc_id,
                        subject=subject,
                        predicate="depends_on",
                        obj=object_id(doc.doc_id, str(context.get("unit_id", ""))),
                        reason="The unit is observed as a stem companion and is not reliably standalone without nearby instructional context.",
                        evidence_refs=refs + [region_id(doc.doc_id, str(ref)) for ref in context.get("source_refs", []) or []],
                        confidence=0.82,
                        open_text="requires_parent_context",
                    )
            elif {"grammar_question", "example_exercise"} & set(unit.get("role_tags", []) or []):
                context = previous_context_unit(doc.units, index)
                if context:
                    add_claim(
                        claims,
                        doc_id=doc.doc_id,
                        subject=subject,
                        predicate="depends_on",
                        obj=object_id(doc.doc_id, str(context.get("unit_id", ""))),
                        reason="The exercise is adjacent to an instructional/method object and should preserve that context before packet projection.",
                        evidence_refs=refs + [region_id(doc.doc_id, str(ref)) for ref in context.get("source_refs", []) or []],
                        confidence=0.72,
                        open_text="context_recommended_or_required",
                    )
        pages = refs_pages([str(ref) for ref in unit.get("source_refs", []) or []])
        if len(pages) > 1:
            add_claim(
                claims,
                doc_id=doc.doc_id,
                subject=subject,
                predicate="continues_on",
                obj=page_id(doc.doc_id, pages[-1]),
                reason="Object evidence spans multiple source pages.",
                evidence_refs=refs,
                confidence=0.86,
                open_text="cross_page_object",
            )
        if unit.get("completeness") in {"open_tail", "fragment"}:
            add_claim(
                claims,
                doc_id=doc.doc_id,
                subject=subject,
                predicate="continues_on",
                obj="UNRESOLVED_CONTINUATION",
                reason="Upstream completeness marks this object as open tail or fragment.",
                evidence_refs=refs,
                confidence=0.94,
                open_text="unresolved_continuation",
            )
    for claim in claims:
        if claim["object"] != "UNRESOLVED_CONTINUATION" and claim["object"] not in object_ids and ":page_" not in claim["object"]:
            claim["target_resolution_status"] = "DANGLING"
        else:
            claim["target_resolution_status"] = "RESOLVED"
    return claims


def graph_for_doc(doc: DocInputs) -> dict[str, Any]:
    assets = load_asset_manifest(doc)
    packets = load_packet_candidates(doc)
    source_evidence = build_source_evidence(doc, assets)
    objects = build_semantic_objects(doc, source_evidence, assets)
    claims = build_semantic_claims(doc, objects)
    return {
        "doc_id": doc.doc_id,
        "source_evidence": source_evidence,
        "semantic_objects": objects,
        "semantic_claims": claims,
        "legacy_packet_candidates": {
            "source": rel_workspace(doc.model_gate_doc_dir / "model_gated_question_packet_candidates.json"),
            "packet_count": len(packets.get("packets", [])),
            "packet_ids": [packet.get("packet_id") for packet in packets.get("packets", [])],
        },
    }


def claim_lookup(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_subject: dict[str, list[dict[str, Any]]] = {}
    by_object: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        by_subject.setdefault(str(claim.get("subject", "")), []).append(claim)
        by_object.setdefault(str(claim.get("object", "")), []).append(claim)
    return {"subject": by_subject, "object": by_object}


def projection_for_object(obj: dict[str, Any], claims_by: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    obj_id = obj["id"]
    subject_claims = claims_by["subject"].get(obj_id, [])
    object_claims = claims_by["object"].get(obj_id, [])
    normalized_hint_values = {hint["hint"] for hint in obj.get("normalized_hints", [])}
    observations = {item.get("label") for item in obj.get("observations", [])}
    is_question_observation = "question_like_unit" in observations or "question_like_unit" in normalized_hint_values
    has_answer = any(claim.get("predicate") == "answers" for claim in object_claims)
    has_context_dependency = any(claim.get("predicate") == "depends_on" for claim in subject_claims)
    has_surface_or_asset = any(claim.get("predicate") == "uses_asset" for claim in subject_claims)
    has_unresolved = any(
        claim.get("predicate") == "continues_on" and claim.get("object") == "UNRESOLVED_CONTINUATION"
        for claim in subject_claims
    )
    reasons: list[str] = []
    status = "UNSUPPORTED"
    runtime_payload: dict[str, Any] | None = None
    if not is_question_observation:
        status = "UNSUPPORTED"
        reasons.append("current_runtime_projector_only_targets_question_observations")
    elif obj.get("semantic_status") == "INCOMPLETE_SOURCE" or has_unresolved:
        status = "BLOCKED"
        reasons.append("source_incomplete_or_unresolved_continuation")
    elif obj.get("evidence_status") == "ENCODING_ERROR":
        status = "BLOCKED"
        reasons.append("encoding_error_in_source_evidence")
    elif not has_answer:
        status = "BLOCKED"
        reasons.append("no_answer_claim_in_semantic_graph")
    elif has_context_dependency:
        status = "NEEDS_REVIEW"
        reasons.append("parent_context_dependency_must_be_preserved_before_qbank_projection")
    elif has_surface_or_asset:
        status = "READY_WITH_LOSS"
        reasons.append("visual_or_writing_surface_preserved_in_graph_but_runtime_mapping_may_use_page_fallback")
    else:
        status = "READY"
    if status in {"READY", "READY_WITH_LOSS", "NEEDS_REVIEW"} and is_question_observation:
        answer_claims = [claim for claim in object_claims if claim.get("predicate") == "answers"]
        context_claims = [claim for claim in subject_claims if claim.get("predicate") in {"shares_context", "depends_on"}]
        runtime_payload = {
            "runtime_shape": "QuestionPacket_projection_candidate",
            "source_object_id": obj_id,
            "title": obj.get("title", ""),
            "stem_source_refs": obj.get("line_refs", []),
            "answer_object_ids": [claim.get("subject") for claim in answer_claims],
            "context_object_ids": [claim.get("object") for claim in context_claims],
            "asset_object_ids": [claim.get("object") for claim in subject_claims if claim.get("predicate") == "uses_asset"],
            "projection_policy": "map_only_existing_graph_facts_no_reinterpretation",
        }
    return {
        "object_id": obj_id,
        "doc_id": obj.get("doc_id"),
        "source_unit_id": obj.get("source_unit_id"),
        "semantic_status": obj.get("semantic_status"),
        "evidence_status": obj.get("evidence_status"),
        "projection_status": status,
        "projection_reasons": reasons,
        "target": "current_runtime_question_packet",
        "used_normalized_hint_for_gate": False,
        "normalized_hints_are_observational_only": True,
        "runtime_payload": runtime_payload,
    }


def build_projection_report(graph: dict[str, Any], human_review: dict[str, Any]) -> dict[str, Any]:
    docs: dict[str, Any] = {}
    flat_projections: dict[str, dict[str, Any]] = {}
    for doc in graph["documents"]:
        claims_by = claim_lookup(doc["semantic_claims"])
        projections = [projection_for_object(obj, claims_by) for obj in doc["semantic_objects"]]
        docs[doc["doc_id"]] = {
            "projection_count": len(projections),
            "projections": projections,
        }
        for item in projections:
            flat_projections[f"{item['doc_id']}_{item['source_unit_id']}"] = item
    alignment: list[dict[str, Any]] = []
    for human in human_review.get("packets", []):
        packet_id = str(human.get("packet_id", ""))
        projection = flat_projections.get(packet_id)
        alignment.append(
            {
                "packet_id": packet_id,
                "doc_id": human.get("doc_id"),
                "human_verdict": human.get("human_verdict"),
                "current_final_status": human.get("current_final_status"),
                "projection_status": projection.get("projection_status") if projection else "MISSING_PROJECTION",
                "semantic_status": projection.get("semantic_status") if projection else "MISSING",
                "evidence_status": projection.get("evidence_status") if projection else "MISSING",
                "projection_reasons": projection.get("projection_reasons", []) if projection else ["source_object_not_found"],
                "matches_human_direction": compare_human_projection(human.get("human_verdict"), projection),
            }
        )
    return {
        "schema": f"{SCHEMA_VERSION}.projection_report",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": "current_runtime_question_packet",
        "projector_policy": "projection_only_no_semantic_reinterpretation",
        "docs": docs,
        "human_acceptance_alignment": alignment,
        "alignment_counts": {
            "items": len(alignment),
            "matched_direction": sum(1 for item in alignment if item["matches_human_direction"] is True),
            "mismatched_direction": sum(1 for item in alignment if item["matches_human_direction"] is False),
            "not_comparable": sum(1 for item in alignment if item["matches_human_direction"] is None),
        },
    }


def compare_human_projection(human_verdict: Any, projection: dict[str, Any] | None) -> bool | None:
    if projection is None:
        return False
    human_value = str(human_verdict or "")
    status = projection.get("projection_status")
    if human_value.startswith("ACCEPT") and status in {"READY", "READY_WITH_LOSS", "NEEDS_REVIEW"}:
        return True
    if human_value.startswith("HOLD") and status in {"BLOCKED", "NEEDS_REVIEW", "READY_WITH_LOSS"}:
        return True
    return False


def build_audit_report(graph: dict[str, Any], projection: dict[str, Any], human_review: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# English Text-First Sidecar Rescue v0.1")
    lines.append("")
    lines.append(f"Date: {datetime.now().date().isoformat()}")
    lines.append("")
    lines.append("## Current v05 Information Loss Audit")
    lines.append("")
    lines.append("- `build_packet_candidates()` iterates only `question_like_unit`, so non-packet source material is not first-class in the output target.")
    lines.append("- `family_for()` maps document/unit hints to a packet family before semantic graph preservation, which makes target projection influence source interpretation.")
    lines.append("- `release_status` mixes semantic completeness, evidence integrity, visual-asset quality, and Runtime expressibility into one READY/HOLD value.")
    lines.append("- Existing crop assets are derivative rough views. The original page remains the fact source, but v05 packet gating treats crop quality as packet validity.")
    lines.append("- Parent/context relations exist partly as `parent_hint`, `relation_to_parent`, facets, and page order, but v05 does not preserve them as open semantic claims.")
    lines.append("")
    lines.append("## New Data Flow")
    lines.append("")
    lines.append("```text")
    lines.append("existing v05 VLM/page evidence + units + assets")
    lines.append("  -> sidecar source evidence")
    lines.append("  -> open semantic objects")
    lines.append("  -> minimal semantic claims")
    lines.append("  -> target-specific Runtime projection report")
    lines.append("```")
    lines.append("")
    lines.append("QuestionPacket is now a projection candidate, not the source material truth object.")
    lines.append("")
    lines.append("## Schema Summary")
    lines.append("")
    lines.append("- `source_evidence`: documents, pages, page images, VLM transcription blocks, region refs, derivative crops, source-page fallback refs.")
    lines.append("- `semantic_objects`: open `kind.open_text`, observations, optional multi-label `normalized_hints`, source refs, status, uncertainty, version metadata.")
    lines.append("- `semantic_claims`: minimal predicates only: `contains`, `depends_on`, `continues_on`, `answers`, `shares_context`, `uses_asset`, `other` plus `predicate_open_text`.")
    lines.append("- `projection_report`: separate `semantic_status`, `evidence_status`, and target `projection_status`.")
    lines.append("")
    lines.append("## Hard Constraint Checks")
    lines.append("")
    objects = [obj for doc in graph["documents"] for obj in doc["semantic_objects"]]
    claims = [claim for doc in graph["documents"] for claim in doc["semantic_claims"]]
    regions = [region for doc in graph["documents"] for region in doc["source_evidence"]["regions"]]
    mojibake_count = sum(1 for region in regions if region.get("has_mojibake"))
    lines.append(f"- semantic_objects: {len(objects)}")
    lines.append(f"- semantic_claims: {len(claims)}")
    lines.append(f"- source_regions: {len(regions)}")
    lines.append(f"- strict_mojibake_regions: {mojibake_count}")
    lines.append(f"- predicates_used: {', '.join(sorted({claim['predicate'] for claim in claims}))}")
    lines.append("- normalized_hints are stored as optional observational mappings with `not_gate_input=true`; the projector reports `used_normalized_hint_for_gate=false`.")
    lines.append("- Graph Composer used existing full page evidence, full transcriptions, source refs, adjacent page ids, and asset/page fallbacks; it did not wrap only packet candidates.")
    lines.append("- Projector reads only the graph and does not re-open source pages for semantic guessing.")
    lines.append("")
    lines.append("## 17-Item Human Replay")
    lines.append("")
    lines.append("| packet | human | projection | semantic | evidence | match |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in projection["human_acceptance_alignment"]:
        lines.append(
            "| {packet_id} | {human_verdict} | {projection_status} | {semantic_status} | {evidence_status} | {match} |".format(
                packet_id=item["packet_id"],
                human_verdict=item["human_verdict"],
                projection_status=item["projection_status"],
                semantic_status=item["semantic_status"],
                evidence_status=item["evidence_status"],
                match=item["matches_human_direction"],
            )
        )
    lines.append("")
    lines.append("## Open-World Smoke")
    lines.append("")
    open_world = graph.get("open_world_smoke", {})
    lines.append(f"- non_packet_objects_checked: {open_world.get('non_packet_objects_checked', 0)}")
    lines.append(f"- unsupported_preserved: {open_world.get('unsupported_preserved', 0)}")
    lines.append(f"- dangling_claims: {open_world.get('dangling_claims', 0)}")
    lines.append("")
    lines.append("## Not Production Ready")
    lines.append("")
    lines.append("This sidecar proves a rescue representation over existing artifacts. It does not prove production readiness, database readiness, or unseen-material readiness beyond the local open-world smoke.")
    return "\n".join(lines) + "\n"


def open_world_smoke(graph: dict[str, Any], human_review: dict[str, Any]) -> dict[str, Any]:
    reviewed_unit_ids = {f"{item.get('doc_id')}_{str(item.get('packet_id', '')).split('_u_')[-1]}" for item in human_review.get("packets", [])}
    reviewed_object_ids = {
        f"{item.get('doc_id')}:u_{str(item.get('packet_id', '')).split('_u_')[-1]}"
        for item in human_review.get("packets", [])
        if "_u_" in str(item.get("packet_id", ""))
    }
    non_packet_objects: list[dict[str, Any]] = []
    dangling = 0
    for doc in graph["documents"]:
        object_ids = {obj["id"] for obj in doc["semantic_objects"]}
        for claim in doc["semantic_claims"]:
            target = claim["object"]
            if target not in object_ids and ":page_" not in target and target != "UNRESOLVED_CONTINUATION":
                dangling += 1
        for obj in doc["semantic_objects"]:
            observations = {obs.get("label") for obs in obj.get("observations", [])}
            if "question_like_unit" not in observations and obj["id"] not in reviewed_object_ids:
                non_packet_objects.append(obj)
    return {
        "description": "Local open-world smoke over objects not included in the 17 human-reviewed packet candidates.",
        "not_a_true_unseen_pdf_eval": True,
        "reviewed_unit_id_debug": sorted(reviewed_unit_ids),
        "non_packet_objects_checked": len(non_packet_objects),
        "unsupported_preserved": len(non_packet_objects),
        "dangling_claims": dangling,
        "sample_objects": [
            {
                "id": obj["id"],
                "kind": obj["kind"],
                "semantic_status": obj["semantic_status"],
                "evidence_status": obj["evidence_status"],
                "evidence_refs": obj["evidence_refs"][:5],
            }
            for obj in non_packet_objects[:12]
        ],
    }


def write_schema(out_dir: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "english_text_first_sidecar_v01.semantic_graph.schema.json",
        "title": "English Text First Sidecar Semantic Graph v0.1",
        "type": "object",
        "required": ["schema", "documents"],
        "properties": {
            "schema": {"const": f"{SCHEMA_VERSION}.semantic_graph"},
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["doc_id", "source_evidence", "semantic_objects", "semantic_claims"],
                    "properties": {
                        "doc_id": {"type": "string"},
                        "source_evidence": {"type": "object"},
                        "semantic_objects": {"type": "array"},
                        "semantic_claims": {"type": "array"},
                    },
                },
            },
        },
        "notes": [
            "Object kind is intentionally open-world.",
            "normalized_hints are optional engineering mappings and are not semantic facts.",
            "Core predicates are minimal; use predicate=other with predicate_open_text for extensions.",
        ],
    }
    write_json(out_dir / "semantic_graph.schema.json", schema)


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = workspace_path(args.out)
    if out_dir.exists() and args.clean:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = [doc.strip() for doc in str(args.docs).split(",") if doc.strip()]
    documents = [graph_for_doc(load_doc_inputs(args, doc_id)) for doc_id in docs]
    human_review = load_human_review(workspace_path(args.human_review))
    graph = {
        "schema": f"{SCHEMA_VERSION}.semantic_graph",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "composer_policy": {
            "mode": "sidecar_adapter_over_existing_vlm_units",
            "new_model_calls": 0,
            "question_packet_is_projection_not_source_truth": True,
            "normalized_hint_policy": "optional_multi_label_confidence_versioned_observation_only",
            "core_predicates": sorted(CORE_PREDICATES),
            "projector_may_not_reinterpret_graph": True,
        },
        "input_roots": {
            "unit_root": rel_workspace(workspace_path(args.unit_root)),
            "vlm_root": rel_workspace(workspace_path(args.vlm_root)),
            "base_root": rel_workspace(workspace_path(args.base_root)),
            "model_gate_root": rel_workspace(workspace_path(args.model_gate_root)),
            "human_review": rel_workspace(workspace_path(args.human_review)),
        },
        "documents": documents,
    }
    graph["open_world_smoke"] = open_world_smoke(graph, human_review)
    projection = build_projection_report(graph, human_review)
    write_json(out_dir / "semantic_graph.json", graph)
    write_json(out_dir / "projection_report.json", projection)
    write_schema(out_dir)
    write_text(out_dir / "sidecar_rescue_report.md", build_audit_report(graph, projection, human_review))
    summary = {
        "schema": f"{SCHEMA_VERSION}.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": rel_workspace(out_dir),
        "semantic_graph": rel_workspace(out_dir / "semantic_graph.json"),
        "projection_report": rel_workspace(out_dir / "projection_report.json"),
        "human_replay_items": len(projection["human_acceptance_alignment"]),
        "alignment_counts": projection["alignment_counts"],
        "open_world_smoke": graph["open_world_smoke"],
        "model_calls_this_run": 0,
        "runtime_import_enabled": False,
    }
    write_json(out_dir / "run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an open semantic graph sidecar over English text-first v0.5 artifacts.")
    parser.add_argument("--unit-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v04c_hardened_enum_norm_full8_lite_20260715")
    parser.add_argument("--vlm-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/vlm_transcriber_full8_lite_20260715")
    parser.add_argument("--base-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/base")
    parser.add_argument("--model-gate-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/model_gate")
    parser.add_argument("--human-review", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json")
    parser.add_argument("--docs", default="reading_argumentative,grammar_clauses,writing_invitation")
    parser.add_argument("--out", default="outputs/english_text_first_pipeline_v02_spec_20260715/sidecar_rescue_v01_20260715")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
