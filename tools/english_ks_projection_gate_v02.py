from __future__ import annotations

from typing import Any


def knowledge_role_for(obj: dict[str, Any]) -> str:
    facts = obj.get("projection_facts", {}) if isinstance(obj.get("projection_facts"), dict) else {}
    claim = facts.get("knowledge_projection_role_claim")
    if isinstance(claim, dict):
        role = str(claim.get("role", "") or "")
        status = str(claim.get("status", "") or "")
        provenance = str(claim.get("provenance", "") or "")
        if status in {"ACCEPTED", "VERIFIED"} and provenance and role in {
            "ANCHOR_NODE",
            "STRUCTURE_NODE",
            "PRESERVE_AS_CHILD_ACTIVITY",
            "PRESERVE_AS_REFERENCE",
            "LINKED_PRACTICE",
            "NOT_APPLICABLE",
        }:
            return role
    return "NOT_APPLICABLE"


def explicit_capability(obj: dict[str, Any], target: str) -> str:
    facts = obj.get("projection_facts", {}) if isinstance(obj.get("projection_facts"), dict) else {}
    capabilities = facts.get("target_capability_claims", [])
    if not isinstance(capabilities, list):
        return "UNREVIEWED"
    for claim in capabilities:
        if not isinstance(claim, dict):
            continue
        if claim.get("target") != target:
            continue
        status = str(claim.get("status", "") or "")
        provenance = str(claim.get("provenance", "") or "")
        if provenance and status in {"ELIGIBLE", "INELIGIBLE", "REQUIRES_REVIEW", "PRESERVABLE_AS_PARTIAL"}:
            return status
    return "UNREVIEWED"


def completeness_for(
    obj: dict[str, Any],
    *,
    has_region_group: bool,
    has_complete_region_group: bool = False,
    has_partial_region_group: bool = False,
    has_complete_asset_group: bool = False,
) -> dict[str, str]:
    old_structure = obj.get("structure", {}) or {}
    existing_completeness = obj.get("completeness", {}) or {}
    old_status = str(old_structure.get("representation_status", "") or old_structure.get("legacy_representation_status", "") or "")
    if existing_completeness.get("semantic_capture") == "PARTIAL" and not old_status:
        old_status = "partial"
    if old_status == "partial":
        semantic_capture = "PARTIAL"
        structured = "PARTIAL_STRUCTURED"
    elif old_structure.get("cells"):
        semantic_capture = "COMPLETE"
        structured = "COMPLETE_STRUCTURED"
    elif old_structure.get("rows") or old_structure.get("columns"):
        semantic_capture = "COMPLETE"
        structured = "SOURCE_REGION_ONLY"
    else:
        semantic_capture = "COMPLETE"
        structured = "NONE"
    asset_grounding = "COMPLETE" if has_complete_asset_group else "NOT_CREATED"
    if has_complete_region_group:
        source_region_grounding = "COMPLETE"
    elif has_partial_region_group:
        source_region_grounding = "PARTIAL"
    elif has_region_group:
        source_region_grounding = "UNVERIFIED"
    else:
        source_region_grounding = "MISSING"
    return {
        "requested_source_coverage": "COMPLETE",
        "semantic_capture": semantic_capture,
        "source_region_grounding": source_region_grounding,
        "asset_grounding": asset_grounding,
        "structured_extraction": structured,
    }


def project_v02(
    obj: dict[str, Any],
    *,
    has_region_group: bool,
    has_complete_region_group: bool = False,
    has_partial_region_group: bool = False,
    has_complete_asset_group: bool = False,
) -> dict[str, Any]:
    old_qbank = obj.get("projections", {}).get("qbank", {}) or {}
    role = knowledge_role_for(obj)
    completeness = completeness_for(
        obj,
        has_region_group=has_region_group,
        has_complete_region_group=has_complete_region_group,
        has_partial_region_group=has_partial_region_group,
        has_complete_asset_group=has_complete_asset_group,
    )
    is_partial = completeness["semantic_capture"] == "PARTIAL"
    qbank_capability = explicit_capability(obj, "qbank_as_is")
    knowledge_capability = explicit_capability(obj, "knowledge_structure")
    old_status = str(old_qbank.get("status", "") or "")
    qbank_as_is = "NEEDS_REVIEW"
    if qbank_capability == "ELIGIBLE" and completeness["asset_grounding"] == "COMPLETE":
        qbank_as_is = "READY"
    elif qbank_capability == "INELIGIBLE":
        qbank_as_is = "UNSUPPORTED_AS_IS"
    if is_partial:
        qbank_as_is = "BLOCKED"
    derivation_status = "NOT_APPLICABLE"
    if explicit_capability(obj, "future_question_derivation") == "ELIGIBLE":
        derivation_status = "CANDIDATE"
    if is_partial:
        derivation_status = "NEEDS_REVIEW"
    if is_partial:
        knowledge_status = "NEEDS_REVIEW"
    elif has_complete_asset_group:
        knowledge_status = "READY_WITH_ASSET" if knowledge_capability == "ELIGIBLE" else "NEEDS_REVIEW"
    elif has_complete_region_group:
        knowledge_status = "READY_WITH_SOURCE_REGIONS" if knowledge_capability == "ELIGIBLE" else "NEEDS_REVIEW"
    elif has_region_group:
        knowledge_status = "NEEDS_REVIEW_WITH_SOURCE_REGIONS"
    else:
        knowledge_status = "NEEDS_REVIEW"
    if is_partial:
        faithful_status = "PRESERVE_PARTIAL_FRAGMENT" if has_region_group else "NEEDS_REVIEW"
    elif has_complete_asset_group:
        faithful_status = "READY_WITH_ASSET"
    elif has_complete_region_group:
        faithful_status = "READY_WITH_SOURCE_REGIONS"
    elif has_region_group:
        faithful_status = "NEEDS_REVIEW_WITH_SOURCE_REGIONS"
    else:
        faithful_status = "NEEDS_REVIEW"
    qbank_blocking = []
    if qbank_as_is == "UNSUPPORTED_AS_IS":
        qbank_blocking = ["current_object_not_supported_as_qbank_packet"]
    elif qbank_as_is == "BLOCKED":
        qbank_blocking = ["source_region_grounding_partial_or_incomplete"]
    derivation_requires = []
    if derivation_status in {"CANDIDATE", "NEEDS_REVIEW", "READY_FOR_GENERATION"}:
        derivation_requires = ["derived_object_generation", "derived_from_relation", "human_review"]
    knowledge_blocking = []
    if knowledge_status == "BLOCKED":
        knowledge_blocking = ["source_region_grounding_partial_or_incomplete"]
    elif knowledge_status == "NEEDS_REVIEW_WITH_SOURCE_REGIONS":
        knowledge_blocking = ["source_region_coverage_unverified"]
    elif knowledge_status == "NEEDS_REVIEW":
        knowledge_blocking = ["explicit_knowledge_structure_capability_claim_missing_or_unreviewed"]
    faithful_blocking = []
    if faithful_status == "NEEDS_REVIEW_WITH_SOURCE_REGIONS":
        faithful_blocking = ["source_region_coverage_unverified"]
    elif faithful_status == "NEEDS_REVIEW":
        faithful_blocking = ["source_region_group_missing_or_unavailable"]
    return {
        "qbank_projection": {
            "target": "current_runtime_question_packet",
            "as_is_status": qbank_as_is,
            "capability_level": "AS_IS_ONLY",
            "reason": old_qbank.get("reason", "Original source object is not directly mapped to QuestionPacket."),
            "blocking_requirements": qbank_blocking,
        },
        "derivation": {
            "target": "future_question_derivation",
            "status": derivation_status,
            "requires": derivation_requires,
            "source_object_refs": [obj.get("object_id", "")],
            "derived_object_refs": [],
            "human_review_required": derivation_status != "NOT_APPLICABLE",
            "reason": "Separated from qbank as-is projection; no derived QuestionPacket was generated in v0.2 replay.",
        },
        "knowledge_structure": {
            "target": "knowledge_structure_sidecar",
            "status": knowledge_status,
            "capability_level": "SOURCE_REGION_BACKED" if has_region_group and not has_complete_asset_group else "ASSET_BACKED",
            "knowledge_projection_role": role,
            "reason": "Computed from verified contract fields; source regions and asset groups are not interchangeable.",
            "blocking_requirements": knowledge_blocking,
        },
        "faithful_material": {
            "target": "faithful_material_sidecar",
            "status": faithful_status,
            "capability_level": "SOURCE_REGION_BACKED" if has_region_group and not has_complete_asset_group else "ASSET_BACKED",
            "reason": "Original page regions are preserved as fact source; no derived asset is claimed unless a real file exists.",
            "blocking_requirements": faithful_blocking,
        },
    }
