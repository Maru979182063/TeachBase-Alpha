from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "english_text_first_knowledge_structure_decontaminated_contract_v02"


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_raw_json(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    return raw, json.loads(raw.decode("utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def valid_bbox(bbox: Any) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return False
    return 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000


def valid_region_id(region_id: Any) -> bool:
    if not isinstance(region_id, str):
        return False
    return bool(
        re.fullmatch(r"verified:[A-Za-z0-9_.:-]+:p\d{3}:\d{3}", region_id)
        or re.fullmatch(r"[A-Za-z0-9_.:-]+:p\d{3}:\d{4}", region_id)
    )


def collect_ids(doc: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "objects": {str(obj.get("object_id", "")) for obj in doc.get("semantic_objects", []) or []},
        "regions": {str(region.get("evidence_id", "")) for region in doc.get("source_regions", []) or []},
        "region_groups": {str(group.get("source_region_group_id", "")) for group in doc.get("source_region_groups", []) or []},
        "assets": {str(group.get("asset_group_id", "")) for group in doc.get("asset_groups", []) or []},
        "pages": {str(page.get("page_id", "")) for page in doc.get("source_page_images", []) or []},
    }


def add_finding(findings: list[dict[str, Any]], *, code: str, severity: str, path: str, evidence: dict[str, Any]) -> None:
    findings.append(
        {
            "code": code,
            "severity": severity,
            "path": path,
            "evidence": evidence,
            "status": "REQUIRES_REVIEW" if severity in {"warning", "error"} else "PASS",
        }
    )


def contract_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for d_index, doc in enumerate(payload.get("documents", []) or []):
        ids = collect_ids(doc)
        for r_index, region in enumerate(doc.get("source_regions", []) or []):
            path = f"documents[{d_index}].source_regions[{r_index}]"
            if not valid_bbox(region.get("bbox_norm1000")):
                add_finding(findings, code="BBOX_INVALID", severity="error", path=path, evidence={"bbox": region.get("bbox_norm1000")})
            if region.get("page_id") and str(region.get("page_id")) not in ids["pages"]:
                add_finding(findings, code="PAGE_REF_DANGLING", severity="error", path=path, evidence={"page_id": region.get("page_id")})
            if not valid_region_id(region.get("region_id")):
                add_finding(
                    findings,
                    code="SOURCE_REGION_ID_UNPARSEABLE",
                    severity="warning",
                    path=path,
                    evidence={"source_region_id_raw": region.get("region_id"), "raw_id_unchanged": True},
                )
            if region.get("verification_status") == "VERIFIED" and not region.get("verified_by_call_id") and not region.get("verification_provenance"):
                add_finding(findings, code="VERIFIED_WITHOUT_PROVENANCE", severity="error", path=path, evidence={"evidence_id": region.get("evidence_id")})
        for g_index, group in enumerate(doc.get("source_region_groups", []) or []):
            for m_index, member in enumerate(group.get("members", []) or []):
                if str(member.get("evidence_id", "")) not in ids["regions"]:
                    add_finding(
                        findings,
                        code="REGION_GROUP_MEMBER_DANGLING",
                        severity="error",
                        path=f"documents[{d_index}].source_region_groups[{g_index}].members[{m_index}]",
                        evidence={"evidence_id": member.get("evidence_id")},
                    )
        for a_index, group in enumerate(doc.get("asset_groups", []) or []):
            for m_index, member in enumerate(group.get("members", []) or []):
                asset_path = workspace_path(str(member.get("path", "")))
                if not member.get("path") or not asset_path.exists():
                    add_finding(
                        findings,
                        code="ASSET_FILE_MISSING",
                        severity="error",
                        path=f"documents[{d_index}].asset_groups[{a_index}].members[{m_index}]",
                        evidence={"path": member.get("path")},
                    )
        for o_index, obj in enumerate(doc.get("semantic_objects", []) or []):
            for ref in obj.get("typed_evidence_refs", []) or []:
                if str(ref) not in ids["regions"]:
                    add_finding(
                        findings,
                        code="OBJECT_EVIDENCE_REF_DANGLING",
                        severity="error",
                        path=f"documents[{d_index}].semantic_objects[{o_index}]",
                        evidence={"ref": ref},
                    )
            for ref in obj.get("source_region_group_refs", []) or []:
                if str(ref) not in ids["region_groups"]:
                    add_finding(
                        findings,
                        code="OBJECT_SOURCE_REGION_GROUP_REF_DANGLING",
                        severity="error",
                        path=f"documents[{d_index}].semantic_objects[{o_index}]",
                        evidence={"ref": ref},
                    )
        for rel_index, rel in enumerate(doc.get("relations", []) or []):
            subject = str(rel.get("subject", ""))
            target = str(rel.get("object", ""))
            predicate = str(rel.get("predicate", ""))
            if subject not in ids["objects"]:
                add_finding(findings, code="RELATION_SUBJECT_DANGLING", severity="error", path=f"documents[{d_index}].relations[{rel_index}]", evidence={"subject": subject})
            if predicate == "uses_asset" and target not in ids["assets"]:
                add_finding(
                    findings,
                    code="RELATION_TARGET_TYPE_CONFLICT",
                    severity="warning",
                    path=f"documents[{d_index}].relations[{rel_index}]",
                    evidence={"raw_predicate": predicate, "object": target, "raw_predicate_unchanged": True},
                )
    return findings


def source_region_status(doc: dict[str, Any], obj: dict[str, Any]) -> str:
    groups = {str(group.get("source_region_group_id")): group for group in doc.get("source_region_groups", []) or []}
    statuses = [str(groups.get(str(ref), {}).get("coverage_status", "")) for ref in obj.get("source_region_group_refs", []) or []]
    if "COMPLETE" in statuses:
        return "COMPLETE"
    if "PARTIAL" in statuses:
        return "PARTIAL"
    if statuses:
        return "UNVERIFIED"
    return "MISSING"


def explicit_capability(obj: dict[str, Any], target: str) -> str:
    facts = obj.get("projection_facts", {}) if isinstance(obj.get("projection_facts"), dict) else {}
    claims = facts.get("target_capability_claims", [])
    if not isinstance(claims, list):
        return "UNREVIEWED"
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("target") != target:
            continue
        if claim.get("provenance") and claim.get("status") in {"ELIGIBLE", "INELIGIBLE", "REQUIRES_REVIEW", "PRESERVABLE_AS_PARTIAL"}:
            return str(claim["status"])
    return "UNREVIEWED"


def projection_eligibility(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for doc in payload.get("documents", []) or []:
        for obj in doc.get("semantic_objects", []) or []:
            grounding = source_region_status(doc, obj)
            semantic_capture = str((obj.get("completeness") or {}).get("semantic_capture", "UNKNOWN"))
            qbank_claim = explicit_capability(obj, "qbank_as_is")
            knowledge_claim = explicit_capability(obj, "knowledge_structure")
            if semantic_capture == "PARTIAL":
                qbank = "INELIGIBLE"
                knowledge = "REQUIRES_REVIEW"
                faithful = "PRESERVABLE_AS_PARTIAL"
            else:
                qbank = qbank_claim if qbank_claim != "UNREVIEWED" else "REQUIRES_REVIEW"
                knowledge = knowledge_claim if knowledge_claim != "UNREVIEWED" else "REQUIRES_REVIEW"
                faithful = "ELIGIBLE" if grounding == "COMPLETE" else "REQUIRES_REVIEW"
            rows.append(
                {
                    "doc_id": doc.get("doc_id"),
                    "object_id": obj.get("object_id"),
                    "source_region_grounding": grounding,
                    "qbank_as_is": qbank,
                    "knowledge_structure": knowledge,
                    "faithful_material": faithful,
                    "raw_projection_claim_unchanged": True,
                }
            )
    return {"schema": f"{SCHEMA}.projection_eligibility", "rows": rows}


def raw_claim_snapshot(source_path: Path, raw: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA}.raw_model_claims",
        "source_path": rel_workspace(source_path),
        "source_sha256": sha256_bytes(raw),
        "raw_payload": payload,
        "raw_payload_unchanged": True,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_path = workspace_path(args.input)
    out_dir = workspace_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, payload = read_raw_json(source_path)
    raw_before = sha256_bytes(raw)
    raw_claims = raw_claim_snapshot(source_path, raw, payload)
    findings = contract_findings(payload)
    eligibility = projection_eligibility(payload)
    raw_after = sha256_bytes(source_path.read_bytes())

    write_json(out_dir / "raw_model_claims.json", raw_claims)
    write_json(out_dir / "contract_findings.json", {"schema": f"{SCHEMA}.contract_findings", "findings": findings})
    write_json(out_dir / "semantic_review_decisions.json", {"schema": f"{SCHEMA}.semantic_review_decisions", "status": "NOT_REVIEWED", "decisions": []})
    write_json(out_dir / "projection_eligibility.json", eligibility)
    write_json(out_dir / "review_manifest.json", {"schema": f"{SCHEMA}.review_manifest", "source": rel_workspace(source_path), "human_review_status": "NOT_REVIEWED"})
    write_json(
        out_dir / "raw_artifact_immutability_report.json",
        {"schema": f"{SCHEMA}.raw_artifact_immutability", "raw_before_sha256": raw_before, "raw_after_sha256": raw_after, "unchanged": raw_before == raw_after},
    )
    summary = {
        "schema": f"{SCHEMA}.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_input": rel_workspace(source_path),
        "out_dir": rel_workspace(out_dir),
        "new_model_calls": 0,
        "runtime_import_enabled": False,
        "contract_finding_count": len(findings),
        "raw_artifact_unchanged": raw_before == raw_after,
        "final_label": "DECONTAMINATED_WITH_WARNINGS" if findings else "SEMANTIC_HEURISTIC_FREE_CONTRACT_READY_FOR_OPEN_WORLD_PROBE",
    }
    write_json(out_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate decontaminated English KS contract artifacts without semantic heuristics.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
