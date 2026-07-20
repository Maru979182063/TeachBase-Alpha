from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import english_ks_contract_v02 as contract
from english_ks_projection_gate_v02 import completeness_for, project_v02
from english_ks_reference_validator_v02 import validate_all
from english_ks_review_renderer_v02 import render_review


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ELIGIBLE = False
FIXTURE_SPECIFIC = True


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value)).strip("_")


def parse_region_text(text: str) -> tuple[int, list[float]] | None:
    match = re.search(r"page\s+(\d+)\s+bbox(?:_norm1000)?\s*\[([^\]]+)\]", str(text))
    if not match:
        return None
    values = [float(item.strip()) for item in match.group(2).split(",")]
    if len(values) != 4:
        return None
    if values[2] <= values[0] or values[3] <= values[1]:
        return None
    return int(match.group(1)), values


def source_page_images(doc: dict[str, Any]) -> list[dict[str, Any]]:
    images = []
    for image_ref in doc.get("source_page_images", []) or []:
        path = workspace_path(str(image_ref))
        page_match = re.search(r"page_(\d+)", path.name)
        page_no = int(page_match.group(1)) if page_match else len(images) + 1
        images.append(
            {
                "page_id": f"{doc['doc_id']}:page_{page_no:03d}",
                "page_number": page_no,
                "path": rel_workspace(path),
                "exists": path.exists(),
                "sha256": contract.sha256_file(path) if path.exists() else "",
            }
        )
    return images


def build_source_regions(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    regions: list[dict[str, Any]] = []
    refs_by_object: dict[str, list[str]] = {}
    seen: set[tuple[str, int, tuple[float, ...], str]] = set()

    def add_region(source_bundle_id: str, page_no: int, bbox: list[float], role: str, owner_id: str, status: str = "PROPOSED") -> str:
        key = (source_bundle_id, page_no, tuple(bbox), role)
        if key in seen:
            for region in regions:
                if (
                    region["source_bundle_id"] == source_bundle_id
                    and region["page_number"] == page_no
                    and region["bbox_norm1000"] == bbox
                    and region["role"] == role
                ):
                    refs_by_object.setdefault(owner_id, []).append(region["evidence_id"])
                    return region["evidence_id"]
        seen.add(key)
        evidence_id = f"ev_{safe_id(owner_id)}_{len(regions) + 1:04d}"
        region = {
            "evidence_id": evidence_id,
            "source_bundle_id": source_bundle_id,
            "page_id": f"{doc['doc_id']}:page_{page_no:03d}",
            "page_number": page_no,
            "region_id": f"{source_bundle_id}:p{page_no:03d}:{len(regions) + 1:04d}",
            "bbox_norm1000": bbox,
            "role": role,
            "source_kind": "original_page",
            "verification_status": status,
        }
        regions.append(region)
        refs_by_object.setdefault(owner_id, []).append(evidence_id)
        return evidence_id

    for obj in doc.get("semantic_objects", []) or []:
        owner_id = str(obj.get("object_id", ""))
        bundle_id = str((obj.get("source_bundle_refs") or [""])[0])
        for ref in obj.get("source_evidence_refs", []) or []:
            parsed = parse_region_text(str(ref))
            if parsed:
                page_no, bbox = parsed
                add_region(bundle_id, page_no, bbox, "model_stated_region", owner_id)
    for bundle in doc.get("source_bundles", []) or []:
        bundle_id = str(bundle.get("source_bundle_id", ""))
        for frag in bundle.get("fragments", []) or []:
            if isinstance(frag.get("bbox_norm1000"), list):
                add_region(bundle_id, int(frag.get("page", 0) or 0), [float(v) for v in frag["bbox_norm1000"]], str(frag.get("role", "bundle_fragment")), bundle_id)
        for asset in bundle.get("child_assets", []) or []:
            if isinstance(asset.get("bbox_norm1000"), list):
                add_region(bundle_id, int(asset.get("page", 0) or 0), [float(v) for v in asset["bbox_norm1000"]], str(asset.get("asset_type", "child_asset_region")), str(asset.get("asset_id", bundle_id)))
    return regions, refs_by_object


def build_region_groups(doc: dict[str, Any], refs_by_object: dict[str, list[str]], source_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = []
    region_by_id = {region["evidence_id"]: region for region in source_regions}
    for obj in doc.get("semantic_objects", []) or []:
        oid = str(obj.get("object_id", ""))
        refs = list(dict.fromkeys(refs_by_object.get(oid, [])))
        if not refs:
            continue
        verification_statuses = {region_by_id[ref]["verification_status"] for ref in refs if ref in region_by_id}
        old_status = str((obj.get("structure") or {}).get("representation_status", ""))
        coverage = "PARTIAL" if old_status == "partial" else "UNVERIFIED"
        groups.append(
            {
                "source_region_group_id": f"srg_{safe_id(oid)}",
                "purpose": str(obj.get("primary_role", {}).get("label", "source_region_grounding")),
                "members": [
                    {
                        "evidence_id": ref,
                        "page_id": region_by_id[ref]["page_id"],
                        "region_id": region_by_id[ref]["region_id"],
                        "sequence": index + 1,
                    }
                    for index, ref in enumerate(refs)
                    if ref in region_by_id
                ],
                "coverage_status": coverage,
                "coverage_verification": {
                    "verified": False,
                    "method": "deterministic_replay_from_v01_model_refs",
                    "evidence_refs": refs,
                    "reason": "Existing evidence is model-proposed source regions. No new visual fact was inferred in v0.2.",
                },
                "source_region_group_only_not_asset": True,
                "verification_statuses": sorted(verification_statuses),
            }
        )
    return groups


def build_asset_groups(doc: dict[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    # v0.2 deterministic replay intentionally does not create derived assets.
    # A valid asset group requires real files with hashes and source refs.
    _ = doc, out_dir
    return []


def build_relations_v02(doc: dict[str, Any]) -> list[dict[str, Any]]:
    relations = []
    objects = {str(obj.get("object_id")): obj for obj in doc.get("semantic_objects", [])}
    object_ids = set(objects)
    source_groups = {}
    for obj in doc.get("semantic_objects", []):
        refs = obj.get("source_region_group_refs", []) or []
        if refs:
            source_groups[str(obj.get("object_id"))] = refs[0]
    counter = 1
    for relation in doc.get("relations", []) or []:
        subject = str(relation.get("subject", ""))
        obj = str(relation.get("object", ""))
        predicate = str(relation.get("predicate", ""))
        open_text = str(relation.get("predicate_open_text", "") or predicate)
        contract_findings = []
        if predicate == "uses_asset" and obj in object_ids:
            contract_findings.append(
                {
                    "code": "RELATION_TARGET_TYPE_CONFLICT",
                    "status": "REQUIRES_SEMANTIC_REVIEW",
                    "evidence": {"subject": subject, "predicate": predicate, "object": obj},
                }
            )
        if predicate not in {"contains", "answers", "explained_by", "depends_on", "aligned_to", "practices", "uses_asset", "follows", "continues_on", "derived_from"}:
            raw_predicate = predicate
            predicate = "other"
        else:
            raw_predicate = predicate
        relations.append(
            {
                "relation_id": f"rel_{counter:04d}",
                "subject": subject,
                "predicate": predicate,
                "raw_predicate": raw_predicate,
                "object": obj,
                "object_ref_type": "semantic_object" if obj in object_ids else "unknown",
                "predicate_open_text": open_text,
                "reason": relation.get("reason", ""),
                "evidence_refs": [source_groups.get(subject, "")] if source_groups.get(subject) else [],
                "confidence": float(relation.get("confidence", 0.0) or 0.0),
                "contract_findings": contract_findings,
            }
        )
        counter += 1
    for obj in doc.get("semantic_objects", []) or []:
        oid = str(obj.get("object_id", ""))
        for asset_group_id in obj.get("asset_group_refs", []) or []:
            relations.append(
                {
                    "relation_id": f"rel_{counter:04d}",
                    "subject": oid,
                    "predicate": "uses_asset",
                    "object": asset_group_id,
                    "object_ref_type": "asset_group",
                    "predicate_open_text": "uses_asset",
                    "reason": "Object is grounded by a verified derived asset group.",
                    "evidence_refs": obj.get("typed_evidence_refs", []),
                    "confidence": 1.0,
                }
            )
            counter += 1
    return relations


def convert_doc_v02(doc: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    source_regions, refs_by_object = build_source_regions(doc)
    source_region_groups = build_region_groups(doc, refs_by_object, source_regions)
    asset_groups = build_asset_groups(doc, out_dir)
    region_group_ids = {group["source_region_group_id"] for group in source_region_groups}
    asset_group_ids = {group["asset_group_id"] for group in asset_groups}
    converted_objects = []
    for obj in doc.get("semantic_objects", []) or []:
        oid = str(obj.get("object_id", ""))
        source_region_group_refs = [f"srg_{safe_id(oid)}"] if f"srg_{safe_id(oid)}" in region_group_ids else []
        asset_group_refs = [ref for ref in obj.get("asset_group_refs", []) or [] if ref in asset_group_ids]
        has_region_group = bool(source_region_group_refs)
        has_complete_asset_group = False
        projections = project_v02(obj, has_region_group=has_region_group, has_complete_asset_group=has_complete_asset_group)
        completeness = completeness_for(obj, has_region_group=has_region_group, has_complete_asset_group=has_complete_asset_group)
        converted_objects.append(
            {
                "object_id": oid,
                "open_description": obj.get("open_description", ""),
                "primary_role": obj.get("primary_role", {}),
                "secondary_roles": obj.get("secondary_roles", []),
                "source_bundle_refs": obj.get("source_bundle_refs", []),
                "typed_evidence_refs": refs_by_object.get(oid, []),
                "source_region_group_refs": source_region_group_refs,
                "asset_group_refs": asset_group_refs,
                "completeness": completeness,
                "structure": {
                    "rows": (obj.get("structure") or {}).get("rows", []),
                    "columns": (obj.get("structure") or {}).get("columns", []),
                    "cells": (obj.get("structure") or {}).get("cells", []),
                    "legacy_representation_status": (obj.get("structure") or {}).get("representation_status", ""),
                },
                "projection_facts": obj.get("projection_facts", {}),
                "projections": projections,
                "uncertainties": obj.get("uncertainties", []),
                "human_review_status": "REQUIRED" if completeness["asset_grounding"] != "COMPLETE" else "NOT_REVIEWED",
                "v01_source_object": obj,
            }
        )
    converted = {
        "doc_id": doc["doc_id"],
        "requested_page_range_capture_status": "COMPLETE" if all(image.get("exists") for image in source_page_images(doc)) else "PARTIAL",
        "source_page_images": source_page_images(doc),
        "source_bundles": doc.get("source_bundles", []),
        "source_regions": source_regions,
        "source_region_groups": source_region_groups,
        "asset_groups": asset_groups,
        "semantic_objects": converted_objects,
        "relations": [],
        "uncertainties": doc.get("uncertainties", []),
        "model_call_refs": doc.get("model_calls", {}),
    }
    converted["relations"] = build_relations_v02({**converted, "relations": doc.get("relations", [])})
    return converted


def baseline_defects(v01: dict[str, Any]) -> dict[str, Any]:
    defects = []
    for doc in v01.get("documents", []):
        if doc.get("doc_id") != "grammar_tense_voice_p001_p004":
            continue
        by_id = {obj.get("object_id"): obj for obj in doc.get("semantic_objects", [])}
        for oid in ("obj_002", "obj_003", "obj_004", "obj_009"):
            obj = by_id.get(oid)
            if not obj:
                continue
            defects.append(
                {
                    "object_id": oid,
                    "primary_role": obj.get("primary_role"),
                    "source_evidence_refs": obj.get("source_evidence_refs", []),
                    "source_asset_refs": obj.get("source_asset_refs", []),
                    "structure": obj.get("structure", {}),
                    "projections": obj.get("projections", {}),
                    "defect_flags": [
                        flag
                        for flag, present in {
                            "ready_with_asset_without_asset_ref": any(
                                target.get("status") == "READY_WITH_ASSET"
                                for target in (obj.get("projections", {}) or {}).values()
                                if isinstance(target, dict)
                            )
                            and not obj.get("source_asset_refs"),
                            "complete_with_empty_cells": (obj.get("structure") or {}).get("representation_status") == "complete"
                            and not (obj.get("structure") or {}).get("cells"),
                            "single_region_claim_for_table": oid in {"obj_003", "obj_004"}
                            and len(obj.get("source_evidence_refs", [])) <= 1,
                            "partial_object_mixed_with_source_complete": oid == "obj_009",
                        }.items()
                        if present
                    ],
                }
            )
    return {
        "schema": "english_text_first_knowledge_structure_contract_v02.baseline_defect_reproduction",
        "source": "knowledge_structure_projection_v01_20260716_combined_v2",
        "defects": defects,
        "summary": {
            "defect_count": len(defects),
            "ready_with_asset_contract_gap": sum(1 for item in defects if "ready_with_asset_without_asset_ref" in item["defect_flags"]),
            "complete_with_empty_cells": sum(1 for item in defects if "complete_with_empty_cells" in item["defect_flags"]),
            "single_region_table_claims": sum(1 for item in defects if "single_region_claim_for_table" in item["defect_flags"]),
        },
    }


def human_template(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for doc in payload.get("documents", []) or []:
        for obj in doc.get("semantic_objects", []) or []:
            rows.append(
                {
                    "doc_id": doc["doc_id"],
                    "object_id": obj["object_id"],
                    "source_coverage_verdict": "NOT_REVIEWED",
                    "semantic_role_verdict": "NOT_REVIEWED",
                    "asset_grounding_verdict": "NOT_REVIEWED",
                    "relation_verdict": "NOT_REVIEWED",
                    "projection_verdict": "NOT_REVIEWED",
                    "accepted_corrected_rejected": "NOT_REVIEWED",
                    "corrected_values": {},
                    "reviewer_note": "",
                    "reviewed_at": "",
                }
            )
    return {
        "schema": "english_text_first_knowledge_structure_contract_v02.human_acceptance_template",
        "human_review_status": "NOT_REVIEWED",
        "rows": rows,
    }


def old_gold_v2(v01: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    old_rows = v01.get("old_grammar_comparison", [])
    rows = []
    exact = {"items": 0, "qbank_as_is_exact": 0, "derivation_exact": 0, "knowledge_role_exact": 0, "directional": 0}
    for row in old_rows:
        exact["items"] += 1
        rows.append(
            {
                "packet_id": row.get("packet_id"),
                "canonical_role_gold": row.get("canonical_role_gold"),
                "qbank_as_is_gold": "UNSUPPORTED_AS_IS",
                "derivation_gold": "CANDIDATE",
                "knowledge_projection_role_gold": "PRESERVE_AS_CHILD_ACTIVITY",
                "faithful_projection_gold": "READY_WITH_SOURCE_REGIONS",
                "parent_context_requirement_gold": "REQUIRED",
                "legacy_directionally_aligned": row.get("directionally_aligned"),
                "gold_change_requires_human_confirmation": True,
            }
        )
        if row.get("directionally_aligned"):
            exact["directional"] += 1
    return (
        {"schema": "english_text_first_knowledge_structure_contract_v02.old_grammar_gold_v2", "rows": rows},
        {"schema": "english_text_first_knowledge_structure_contract_v02.old_grammar_exact_metrics", "metrics": exact},
    )


def write_prompt_snapshots(v01: dict[str, Any], out_dir: Path) -> None:
    snap = out_dir / "prompt_snapshots"
    snap.mkdir(parents=True, exist_ok=True)
    for call in v01.get("model_calls", []):
        call_id = safe_id(str(call.get("call_id", "call")))
        contract.write_json(
            snap / f"{call_id}_prompt_snapshot.json",
            {
                "call_id": call.get("call_id"),
                "prompt_available": False,
                "reason": "v0.1 model_calls did not persist full system/user prompt snapshots; v0.2 replay records this gap.",
                "prompt_sha256": "",
            },
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    v01_path = workspace_path(args.v01_projection)
    out_dir = workspace_path(args.out)
    if out_dir.exists() and args.clean:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    v01 = contract.read_json(v01_path)
    baseline = baseline_defects(v01)
    contract.write_json(out_dir / "baseline_defect_reproduction.json", baseline)
    contract.write_text(
        out_dir / "baseline_defect_reproduction.md",
        "# Baseline Defect Reproduction\n\n"
        + "\n".join(f"- {item['object_id']}: {', '.join(item['defect_flags'])}" for item in baseline["defects"])
        + "\n",
    )
    documents = [convert_doc_v02(doc, out_dir) for doc in v01.get("documents", [])]
    model_calls = []
    for call in v01.get("model_calls", []):
        call_copy = {
            "call_id": call.get("call_id"),
            "model": v01.get("model"),
            "prompt_version": "v01_inline_prompt_not_persisted",
            "prompt_sha256": "",
            "input_manifest_sha256": "",
            "attempts": call.get("attempts", []),
            "parsed": call.get("parsed"),
            "json_schema_valid_v01": call.get("schema_valid"),
            "json_schema_valid_v02": None,
            "semantic_validation": "not_a_new_model_call",
            "raw_response_ref": "model_calls.json",
        }
        model_calls.append(call_copy)
    payload = {
        "schema": f"{contract.SCHEMA_VERSION}.projection",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_v01_projection": rel_workspace(v01_path),
        "runtime_import_enabled": False,
        "non_destructive_replay": True,
        "documents": documents,
        "model_calls": model_calls,
        "validation_summary": {},
    }
    validation = validate_all(payload)
    payload["validation_summary"] = validation
    contract.write_json(out_dir / "knowledge_structure_projection_v02.json", payload)
    contract.write_json(out_dir / "knowledge_structure_projection_v02.schema.json", contract.contract_schema())
    contract.write_json(out_dir / "semantic_validation_report.json", {k: v for k, v in validation.items() if k.startswith("semantic")})
    contract.write_json(out_dir / "asset_grounding_report.json", {"asset_groups_by_doc": [{doc["doc_id"]: doc["asset_groups"]} for doc in documents]})
    contract.write_json(out_dir / "relation_validation_report.json", {k: v for k, v in validation.items() if k.startswith("reference")})
    gold_v2, exact_metrics = old_gold_v2(v01)
    contract.write_json(out_dir / "old_grammar_multitarget_gold_v2.json", gold_v2)
    contract.write_json(out_dir / "old_grammar_exact_comparison.json", exact_metrics)
    contract.write_json(
        out_dir / "gold_change_proposal.json",
        {
            "schema": "english_text_first_knowledge_structure_contract_v02.gold_change_proposal",
            "human_confirmation_status": "REQUIRED",
            "changes": gold_v2["rows"],
        },
    )
    contract.write_text(
        out_dir / "gold_change_proposal.md",
        "# Gold Change Proposal\n\nOld HOLD_PARENT_RELATION remains preserved. v2 proposes target-specific gold and requires human confirmation.\n",
    )
    contract.write_json(out_dir / "model_calls.json", {"schema": f"{contract.SCHEMA_VERSION}.model_calls", "calls": model_calls})
    write_prompt_snapshots(v01, out_dir)
    input_manifest = {
        "schema": f"{contract.SCHEMA_VERSION}.input_manifest",
        "source_v01_projection": rel_workspace(v01_path),
        "source_v01_sha256": contract.sha256_file(v01_path),
        "model_call_count_replayed": len(v01.get("model_calls", [])),
        "new_model_calls": 0,
    }
    input_manifest["sha256"] = contract.sha256_text(json.dumps(input_manifest, ensure_ascii=False, sort_keys=True))
    contract.write_json(out_dir / "input_manifest.json", input_manifest)
    template = human_template(payload)
    contract.write_json(out_dir / "human_acceptance_template.json", template)
    contract.write_text(out_dir / "human_acceptance_review.md", "# Human Acceptance Review\n\nhuman_review_status: NOT_REVIEWED\n")
    review = render_review(payload, out_dir, WORKSPACE_ROOT)
    run_summary = {
        "schema": f"{contract.SCHEMA_VERSION}.run_summary",
        "generated_at": payload["generated_at"],
        "out_dir": rel_workspace(out_dir),
        "new_model_calls": 0,
        "runtime_import_enabled": False,
        "json_schema_valid": validation["json_schema_valid"],
        "reference_integrity_valid": validation["reference_integrity_valid"],
        "semantic_contract_valid": validation["semantic_contract_valid"],
        "projection_gate_valid": validation["projection_gate_valid"],
        "source_grounding_blocked_objects": [
            obj["object_id"]
            for doc in documents
            for obj in doc["semantic_objects"]
            if obj["completeness"]["asset_grounding"] != "COMPLETE"
        ],
        "review_html": rel_workspace(review),
        "final_label": "SOURCE_GROUNDING_BLOCKED"
        if not validation["projection_gate_valid"] or baseline["summary"]["single_region_table_claims"]
        else "KNOWLEDGE_STRUCTURE_EVIDENCE_CONTRACT_READY_FOR_HUMAN_REVIEW",
    }
    contract.write_json(out_dir / "run_summary.json", run_summary)
    print(json.dumps(run_summary, ensure_ascii=False, indent=2))
    return run_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic v0.2 evidence-contract replay for English knowledge structure sidecar.")
    parser.add_argument("--v01-projection", default="outputs/english_text_first_pipeline_v02_spec_20260715/knowledge_structure_projection_v01_20260716_combined_v2/knowledge_structure_projection.json")
    parser.add_argument("--out", default=f"outputs/english_text_first_pipeline_v02_spec_20260715/knowledge_structure_projection_v02_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
