from __future__ import annotations

import re
from typing import Any

from english_ks_contract_v02 import (
    DERIVATION_STATUSES,
    FAITHFUL_STATUSES,
    KNOWLEDGE_ROLES,
    KNOWLEDGE_STATUSES,
    PREDICATES,
    QBANK_AS_IS_STATUSES,
    minimal_json_schema_errors,
)


def validate_references(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for doc in payload.get("documents", []) or []:
        doc_id = str(doc.get("doc_id", ""))
        object_ids = {str(obj.get("object_id", "")) for obj in doc.get("semantic_objects", []) or []}
        region_ids = {str(region.get("evidence_id", "")) for region in doc.get("source_regions", []) or []}
        page_ids = {str(page.get("page_id", "")) for page in doc.get("source_page_images", []) or []}
        region_group_ids = {str(group.get("source_region_group_id", "")) for group in doc.get("source_region_groups", []) or []}
        asset_group_ids = {str(group.get("asset_group_id", "")) for group in doc.get("asset_groups", []) or []}
        asset_member_ids = {
            str(member.get("asset_id", ""))
            for group in doc.get("asset_groups", []) or []
            for member in group.get("members", []) or []
        }
        bundle_ids = {str(bundle.get("source_bundle_id", "")) for bundle in doc.get("source_bundles", []) or []}
        for obj in doc.get("semantic_objects", []) or []:
            oid = str(obj.get("object_id", ""))
            for ref in obj.get("typed_evidence_refs", []) or []:
                if str(ref) not in region_ids:
                    errors.append({"doc_id": doc_id, "path": oid, "message": f"dangling evidence ref {ref}"})
            for ref in obj.get("source_region_group_refs", []) or []:
                if str(ref) not in region_group_ids:
                    errors.append({"doc_id": doc_id, "path": oid, "message": f"dangling source region group ref {ref}"})
            for ref in obj.get("asset_group_refs", []) or []:
                if str(ref) not in asset_group_ids:
                    errors.append({"doc_id": doc_id, "path": oid, "message": f"dangling asset group ref {ref}"})
            for ref in obj.get("source_bundle_refs", []) or []:
                if str(ref) not in bundle_ids:
                    warnings.append({"doc_id": doc_id, "path": oid, "message": f"source bundle ref not found in bundle list: {ref}"})
        for region in doc.get("source_regions", []) or []:
            evidence_id = str(region.get("evidence_id", ""))
            source_bundle_id = str(region.get("source_bundle_id", ""))
            page_id = str(region.get("page_id", ""))
            page_number = int(region.get("page_number", 0) or 0)
            region_id = str(region.get("region_id", ""))
            bbox = region.get("bbox_norm1000")
            if region.get("verification_status") == "VERIFIED" and not source_bundle_id:
                errors.append({"doc_id": doc_id, "path": evidence_id, "message": "VERIFIED evidence requires non-empty source_bundle_id"})
            if page_id and page_id not in page_ids:
                errors.append({"doc_id": doc_id, "path": evidence_id, "message": f"evidence page_id does not resolve: {page_id}"})
            if not valid_region_id(region_id):
                errors.append({"doc_id": doc_id, "path": evidence_id, "message": f"malformed region_id {region_id}"})
            parsed_page = region_page_from_id(region_id)
            if parsed_page is not None and parsed_page != page_number:
                errors.append({"doc_id": doc_id, "path": evidence_id, "message": f"region_id page {parsed_page} != evidence page_number {page_number}"})
            if not valid_bbox(bbox):
                errors.append({"doc_id": doc_id, "path": evidence_id, "message": f"malformed bbox {bbox}"})
        for group in doc.get("source_region_groups", []) or []:
            gid = str(group.get("source_region_group_id", ""))
            prior_sequence = 0
            for member in group.get("members", []) or []:
                evidence_id = str(member.get("evidence_id", ""))
                if evidence_id not in region_ids:
                    errors.append({"doc_id": doc_id, "path": gid, "message": f"dangling group evidence ref {evidence_id}"})
                sequence = int(member.get("sequence", 0) or 0)
                if sequence <= prior_sequence:
                    errors.append({"doc_id": doc_id, "path": gid, "message": "source region group member sequence must be strictly increasing"})
                prior_sequence = sequence
        for relation in doc.get("relations", []) or []:
            subject = str(relation.get("subject", ""))
            obj_ref = str(relation.get("object", ""))
            predicate = str(relation.get("predicate", ""))
            if subject not in object_ids:
                errors.append({"doc_id": doc_id, "path": relation.get("relation_id", ""), "message": f"dangling relation subject {subject}"})
            if predicate not in PREDICATES:
                errors.append({"doc_id": doc_id, "path": relation.get("relation_id", ""), "message": f"invalid predicate {predicate}"})
            if predicate == "uses_asset":
                if obj_ref not in asset_group_ids and obj_ref not in asset_member_ids:
                    errors.append({"doc_id": doc_id, "path": relation.get("relation_id", ""), "message": f"uses_asset target must be asset/group, got {obj_ref}"})
            elif obj_ref and obj_ref not in object_ids and obj_ref not in asset_group_ids and obj_ref not in region_group_ids:
                errors.append({"doc_id": doc_id, "path": relation.get("relation_id", ""), "message": f"dangling relation object {obj_ref}"})
            for ref in relation.get("evidence_refs", []) or []:
                if str(ref) not in region_ids and str(ref) not in region_group_ids:
                    errors.append({"doc_id": doc_id, "path": relation.get("relation_id", ""), "message": f"dangling relation evidence {ref}"})
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def valid_bbox(bbox: Any) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return False
    return 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000


def valid_region_id(region_id: str) -> bool:
    return bool(
        re.fullmatch(r"verified:[A-Za-z0-9_.:-]+:p\d{3}:\d{3}", region_id)
        or re.fullmatch(r"[A-Za-z0-9_.:-]+:p\d{3}:\d{4}", region_id)
    )


def region_page_from_id(region_id: str) -> int | None:
    match = re.search(r":p(\d{3}):", region_id)
    return int(match.group(1)) if match else None


def validate_semantic_contract(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for doc in payload.get("documents", []) or []:
        doc_id = str(doc.get("doc_id", ""))
        region_groups = {str(group.get("source_region_group_id", "")): group for group in doc.get("source_region_groups", []) or []}
        asset_groups = {str(group.get("asset_group_id", "")): group for group in doc.get("asset_groups", []) or []}
        for obj in doc.get("semantic_objects", []) or []:
            oid = str(obj.get("object_id", ""))
            completeness = obj.get("completeness", {}) or {}
            structured = str(completeness.get("structured_extraction", ""))
            if structured in {"STRUCTURED_EDITABLE", "COMPLETE_STRUCTURED"}:
                structure = obj.get("structure", {}) or {}
                if not structure.get("cells"):
                    errors.append({"doc_id": doc_id, "path": oid, "message": "complete structured extraction requires non-empty cells"})
            if completeness.get("asset_grounding") == "NOT_CREATED" and structured in {"ASSET_ONLY", "STRUCTURED_EDITABLE"}:
                errors.append({"doc_id": doc_id, "path": oid, "message": "asset-less objects cannot use asset-only structured extraction states"})
            if completeness.get("structured_extraction") in {"PARTIAL_STRUCTURE", "PARTIAL_STRUCTURED"} and obj.get("projections", {}).get("knowledge_structure", {}).get("status") in {"READY", "READY_WITH_SOURCE_REGIONS", "READY_WITH_ASSET"}:
                errors.append({"doc_id": doc_id, "path": oid, "message": "partial structure cannot be knowledge READY"})
            role = obj.get("projections", {}).get("knowledge_structure", {}).get("knowledge_projection_role")
            if role not in KNOWLEDGE_ROLES:
                errors.append({"doc_id": doc_id, "path": oid, "message": f"invalid knowledge projection role {role}"})
            for group_id in obj.get("source_region_group_refs", []) or []:
                group = region_groups.get(str(group_id))
                if group and group.get("coverage_status") != "COMPLETE":
                    warnings.append({"doc_id": doc_id, "path": oid, "message": f"source region group {group_id} coverage is {group.get('coverage_status')}"})
            for group_id in obj.get("asset_group_refs", []) or []:
                group = asset_groups.get(str(group_id))
                if group and group.get("coverage_status") != "COMPLETE":
                    errors.append({"doc_id": doc_id, "path": oid, "message": f"asset group {group_id} is not COMPLETE"})
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def validate_projection_gate(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for doc in payload.get("documents", []) or []:
        doc_id = str(doc.get("doc_id", ""))
        asset_groups = {str(group.get("asset_group_id", "")): group for group in doc.get("asset_groups", []) or []}
        relations = doc.get("relations", []) or []
        derived_from_targets = {str(rel.get("subject", "")) for rel in relations if rel.get("predicate") == "derived_from"}
        object_by_id = {str(obj.get("object_id", "")): obj for obj in doc.get("semantic_objects", []) or []}
        for obj in doc.get("semantic_objects", []) or []:
            oid = str(obj.get("object_id", ""))
            projections = obj.get("projections", {}) or {}
            qbank = projections.get("qbank_projection", {}) or {}
            derivation = projections.get("derivation", {}) or {}
            knowledge = projections.get("knowledge_structure", {}) or {}
            faithful = projections.get("faithful_material", {}) or {}
            if qbank.get("as_is_status") not in QBANK_AS_IS_STATUSES:
                errors.append({"doc_id": doc_id, "path": oid, "message": f"invalid qbank as-is status {qbank.get('as_is_status')}"})
            if derivation.get("status") not in DERIVATION_STATUSES:
                errors.append({"doc_id": doc_id, "path": oid, "message": f"invalid derivation status {derivation.get('status')}"})
            if knowledge.get("status") not in KNOWLEDGE_STATUSES:
                errors.append({"doc_id": doc_id, "path": oid, "message": f"invalid knowledge status {knowledge.get('status')}"})
            if faithful.get("status") not in FAITHFUL_STATUSES:
                errors.append({"doc_id": doc_id, "path": oid, "message": f"invalid faithful status {faithful.get('status')}"})
            for target_name, target in (("knowledge", knowledge), ("faithful", faithful)):
                if target.get("status") == "READY_WITH_ASSET":
                    refs = obj.get("asset_group_refs", []) or []
                    if not refs:
                        errors.append({"doc_id": doc_id, "path": oid, "message": f"{target_name} READY_WITH_ASSET requires asset_group_refs"})
                    for group_id in refs:
                        group = asset_groups.get(str(group_id))
                        if not group or group.get("coverage_status") != "COMPLETE":
                            errors.append({"doc_id": doc_id, "path": oid, "message": f"{target_name} READY_WITH_ASSET requires COMPLETE asset group {group_id}"})
            derived_refs = derivation.get("derived_object_refs", []) or []
            if derived_refs:
                for ref in derived_refs:
                    if ref not in derived_from_targets:
                        errors.append({"doc_id": doc_id, "path": oid, "message": f"derived object {ref} missing derived_from relation"})
            if qbank.get("as_is_status") == "READY" and obj.get("completeness", {}).get("asset_grounding") != "COMPLETE":
                errors.append({"doc_id": doc_id, "path": oid, "message": "qbank READY requires complete asset grounding"})
            if derivation.get("status") == "NOT_APPLICABLE" and derivation.get("requires"):
                errors.append({"doc_id": doc_id, "path": oid, "message": "NOT_APPLICABLE derivation requires must be empty"})
            if qbank.get("as_is_status") == "BLOCKED" and not qbank.get("blocking_requirements"):
                errors.append({"doc_id": doc_id, "path": oid, "message": "BLOCKED qbank projection requires blocking_requirements"})
            for target_name, target in (("knowledge", knowledge), ("faithful", faithful)):
                status = str(target.get("status", ""))
                if status.startswith("READY") and target.get("blocking_requirements"):
                    errors.append({"doc_id": doc_id, "path": oid, "message": f"{target_name} READY status cannot carry blocking_requirements"})
                if status.startswith("NEEDS_REVIEW") and not target.get("blocking_requirements"):
                    errors.append({"doc_id": doc_id, "path": oid, "message": f"{target_name} NEEDS_REVIEW requires review/blocking requirement"})
            source_grounding = obj.get("completeness", {}).get("source_region_grounding")
            if source_grounding == "UNVERIFIED":
                for target_name, target in (("knowledge", knowledge), ("faithful", faithful)):
                    if str(target.get("status", "")).startswith("READY"):
                        errors.append({"doc_id": doc_id, "path": oid, "message": f"{target_name} cannot READY with UNVERIFIED source_region_grounding"})
            if source_grounding == "PARTIAL" and str(knowledge.get("status", "")).startswith("READY"):
                errors.append({"doc_id": doc_id, "path": oid, "message": "partial source_region_grounding cannot be knowledge READY"})
        for relation in relations:
            if relation.get("predicate") == "depends_on":
                subject_obj = object_by_id.get(str(relation.get("subject", "")), {})
                independence_claim = subject_obj.get("independence_claim", {})
                if (
                    isinstance(independence_claim, dict)
                    and independence_claim.get("value") is True
                    and independence_claim.get("provenance")
                ):
                    warnings.append({"doc_id": doc_id, "path": relation.get("relation_id", ""), "message": "EXPLICIT_CLAIM_CONFLICT: independence claim coexists with depends_on relation"})
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def validate_all(payload: dict[str, Any]) -> dict[str, Any]:
    json_errors = minimal_json_schema_errors(payload)
    reference = validate_references(payload)
    semantic = validate_semantic_contract(payload)
    projection = validate_projection_gate(payload)
    return {
        "json_schema_valid": not json_errors,
        "json_schema_errors": json_errors,
        "reference_integrity_valid": reference["valid"],
        "reference_integrity_errors": reference["errors"],
        "reference_integrity_warnings": reference["warnings"],
        "semantic_contract_valid": semantic["valid"],
        "semantic_contract_errors": semantic["errors"],
        "semantic_contract_warnings": semantic["warnings"],
        "projection_gate_valid": projection["valid"],
        "projection_gate_errors": projection["errors"],
        "projection_gate_warnings": projection["warnings"],
    }
