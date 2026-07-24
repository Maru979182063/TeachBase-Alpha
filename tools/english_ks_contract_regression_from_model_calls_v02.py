from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from english_ks_decontaminated_contract_v02 import run as run_decontaminated_contract
from english_ks_reference_validator_v02 import validate_all


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "english_text_first_ks_contract_regression_from_model_calls_v02"


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
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def line_ref_to_evidence_id(doc_id: str, line_ref: str) -> str:
    if line_ref.startswith(f"{doc_id}:"):
        return line_ref
    return f"{doc_id}:{line_ref}"


def source_regions_from_sidecar(doc: dict[str, Any]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for region in doc.get("source_evidence", {}).get("regions", []) or []:
        evidence_id = str(region.get("region_id") or line_ref_to_evidence_id(str(doc.get("doc_id")), str(region.get("line_ref", ""))))
        raw_bbox = region.get("bbox")
        bbox = raw_bbox if isinstance(raw_bbox, list) and len(raw_bbox) == 4 else []
        regions.append(
            {
                "evidence_id": evidence_id,
                "source_bundle_id": f"{doc.get('doc_id')}:sidecar_source",
                "page_id": region.get("page_id", ""),
                "page_number": int(region.get("page_number", 0) or 0),
                "region_id": region.get("region_id", evidence_id),
                "bbox_norm1000": bbox,
                "role": region.get("label", "unknown"),
                "source_kind": "original_page",
                "verification_status": "PROPOSED",
                "line_ref": region.get("line_ref", ""),
                "text": region.get("text", ""),
                "coordinate_status": region.get("coordinate_status", ""),
                "raw_region_preserved": True,
            }
        )
    return regions


def source_pages_from_sidecar(doc: dict[str, Any]) -> list[dict[str, Any]]:
    pages = []
    for page in doc.get("source_evidence", {}).get("pages", []) or []:
        pages.append(
            {
                "page_id": page.get("page_id", ""),
                "page_number": int(page.get("page_number", 0) or 0),
                "path": page.get("image_path", ""),
                "exists": bool(page.get("image_exists")),
                "width_px": page.get("width_px"),
                "height_px": page.get("height_px"),
                "source_page_is_fact_source": True,
            }
        )
    return pages


def asset_groups_from_sidecar(doc: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for asset in doc.get("source_evidence", {}).get("assets", []) or []:
        asset_ref_id = str(asset.get("asset_ref_id") or asset.get("asset_id") or "")
        if not asset_ref_id:
            continue
        groups.append(
            {
                "asset_group_id": asset_ref_id,
                "coverage_status": "COMPLETE" if asset.get("asset_exists") else "UNVERIFIED",
                "members": [
                    {
                        "asset_id": asset.get("asset_id", asset_ref_id),
                        "path": asset.get("asset_path", ""),
                        "source_page_id": asset.get("source_page_id", ""),
                        "source_refs": [line_ref_to_evidence_id(str(doc.get("doc_id")), str(ref)) for ref in asset.get("source_refs", []) or []],
                        "crop_precision": asset.get("crop_precision", ""),
                        "source_page_is_fact_source": bool(asset.get("source_page_is_fact_source")),
                    }
                ],
            }
        )
    return groups


def object_id_for_target(doc_id: str, source_unit_id: str) -> str:
    return f"{doc_id}:{source_unit_id}"


def sidecar_object_by_unit(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_unit: dict[str, dict[str, Any]] = {}
    for obj in doc.get("semantic_objects", []) or []:
        unit = str(obj.get("source_unit_id", "") or "")
        if unit:
            by_unit[unit] = obj
    return by_unit


def make_projection_block(status: str, reason: str, blocking: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "capability_level": "UNVERIFIED_MODEL_CLAIM",
        "knowledge_projection_role": "NOT_APPLICABLE",
        "reason": reason,
        "blocking_requirements": blocking,
    }


def contract_object_from_assessment(doc: dict[str, Any], assessment: dict[str, Any], original: dict[str, Any] | None) -> dict[str, Any]:
    doc_id = str(doc.get("doc_id"))
    source_unit_id = str(assessment.get("source_unit_id") or "")
    evidence_refs = [
        line_ref_to_evidence_id(doc_id, str(ref))
        for ref in (original or {}).get("line_refs", []) or (original or {}).get("evidence_refs", []) or []
    ]
    group_id = f"{object_id_for_target(doc_id, source_unit_id)}:source_regions" if evidence_refs else ""
    model_status = str(assessment.get("projection_status", ""))
    blocking = ["model_claim_unverified_by_contract"]
    if model_status == "BLOCKED":
        blocking = [str(item) for item in assessment.get("risks", []) or []] or ["model_reported_blocked"]
    return {
        "object_id": object_id_for_target(doc_id, source_unit_id),
        "open_description": str((original or {}).get("title") or assessment.get("packet_id") or source_unit_id),
        "primary_role": {
            "label": str(((original or {}).get("observations") or [{}])[0].get("label", "observation")),
            "confidence": float(((original or {}).get("observations") or [{}])[0].get("confidence", 0.0) or 0.0),
            "not_gate_input": True,
        },
        "source_bundle_refs": [f"{doc_id}:sidecar_source"],
        "typed_evidence_refs": evidence_refs,
        "source_region_group_refs": [group_id] if group_id else [],
        "asset_group_refs": [str(ref) for ref in (original or {}).get("asset_refs", []) or []],
        "completeness": {
            "requested_source_coverage": str(assessment.get("evidence_status", "UNKNOWN")),
            "semantic_capture": str(assessment.get("semantic_status", "UNKNOWN")),
            "source_region_grounding": "UNVERIFIED",
            "asset_grounding": "UNVERIFIED" if (original or {}).get("asset_refs") else "NOT_CREATED",
            "structured_extraction": "RAW_MODEL_CLAIM_ONLY",
        },
        "projection_facts": {
            "raw_model_projection_status": model_status,
            "raw_model_projection_status_not_gate_input": True,
            "target_capability_claims": [],
        },
        "model_assessment": assessment,
        "projections": {
            "qbank_projection": {
                "as_is_status": "NEEDS_REVIEW",
                "reason": "raw model projection status is preserved but not accepted as a verified fact",
                "blocking_requirements": ["candidate_level_verifier_required"],
            },
            "derivation": {"status": "NOT_APPLICABLE", "requires": [], "derived_object_refs": []},
            "knowledge_structure": make_projection_block("NEEDS_REVIEW", "candidate requires verified semantic/evidence facts", blocking),
            "faithful_material": make_projection_block("NEEDS_REVIEW", "source regions/assets are not verified by the contract regression", blocking),
        },
        "human_review_status": "REQUIRED",
    }


def group_from_object(obj: dict[str, Any]) -> dict[str, Any] | None:
    refs = obj.get("typed_evidence_refs", []) or []
    group_refs = obj.get("source_region_group_refs", []) or []
    if not refs or not group_refs:
        return None
    return {
        "source_region_group_id": group_refs[0],
        "coverage_status": "UNVERIFIED",
        "members": [{"evidence_id": ref, "sequence": index + 1} for index, ref in enumerate(refs)],
    }


def relation_object_for_hint(doc_id: str, hint: str) -> dict[str, Any]:
    oid = f"{doc_id}:model_hint:{sha1_text(hint)}"
    return {
        "object_id": oid,
        "open_description": hint,
        "primary_role": {"label": "model_relation_target_hint", "confidence": 0.0, "not_gate_input": True},
        "source_bundle_refs": [f"{doc_id}:sidecar_source"],
        "typed_evidence_refs": [],
        "source_region_group_refs": [],
        "asset_group_refs": [],
        "completeness": {
            "requested_source_coverage": "UNKNOWN",
            "semantic_capture": "UNKNOWN",
            "source_region_grounding": "MISSING",
            "asset_grounding": "NOT_CREATED",
            "structured_extraction": "RAW_HINT_ONLY",
        },
        "projections": {
            "qbank_projection": {
                "as_is_status": "NEEDS_REVIEW",
                "reason": "relation target is a raw model hint, not a verified object",
                "blocking_requirements": ["resolve_relation_target"],
            },
            "derivation": {"status": "NOT_APPLICABLE", "requires": [], "derived_object_refs": []},
            "knowledge_structure": make_projection_block("NEEDS_REVIEW", "raw relation target hint requires review", ["resolve_relation_target"]),
            "faithful_material": make_projection_block("NEEDS_REVIEW", "raw relation target hint requires review", ["resolve_relation_target"]),
        },
        "human_review_status": "REQUIRED",
    }


def relations_from_assessment(doc_id: str, assessment: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relations: list[dict[str, Any]] = []
    hint_objects: list[dict[str, Any]] = []
    subject = object_id_for_target(doc_id, str(assessment.get("source_unit_id") or ""))
    for index, rel in enumerate(assessment.get("relations", []) or []):
        hint = str(rel.get("object_hint", "") or "")
        target = relation_object_for_hint(doc_id, hint) if hint else relation_object_for_hint(doc_id, "missing object_hint")
        hint_objects.append(target)
        predicate = str(rel.get("predicate", "other") or "other")
        relations.append(
            {
                "relation_id": f"{subject}:model_relation_{index + 1:03d}",
                "subject": subject,
                "predicate": predicate,
                "object": target["object_id"],
                "predicate_open_text": predicate,
                "evidence_refs": [line_ref_to_evidence_id(doc_id, str(ref)) for ref in rel.get("evidence_refs", []) or []],
                "confidence": float(assessment.get("confidence", 0.0) or 0.0),
                "reason": rel.get("reason", ""),
                "raw_model_relation_unchanged": True,
            }
        )
    return relations, hint_objects


def build_contract_input(sidecar_graph: dict[str, Any], model_calls: dict[str, Any]) -> dict[str, Any]:
    calls_by_doc = {str(call.get("doc_id")): call for call in model_calls.get("calls", []) or []}
    documents: list[dict[str, Any]] = []
    for sidecar_doc in sidecar_graph.get("documents", []) or []:
        doc_id = str(sidecar_doc.get("doc_id"))
        call = calls_by_doc.get(doc_id, {})
        by_unit = sidecar_object_by_unit(sidecar_doc)
        target_objects: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        hint_objects_by_id: dict[str, dict[str, Any]] = {}
        for assessment in (call.get("result", {}) or {}).get("target_assessments", []) or []:
            unit_id = str(assessment.get("source_unit_id") or "")
            target = contract_object_from_assessment(sidecar_doc, assessment, by_unit.get(unit_id))
            target_objects.append(target)
            rels, hints = relations_from_assessment(doc_id, assessment)
            relations.extend(rels)
            for hint in hints:
                hint_objects_by_id[hint["object_id"]] = hint
        groups = [group for obj in target_objects for group in [group_from_object(obj)] if group]
        documents.append(
            {
                "doc_id": doc_id,
                "requested_page_range_capture_status": "COMPLETE",
                "source_page_images": source_pages_from_sidecar(sidecar_doc),
                "source_bundles": [{"source_bundle_id": f"{doc_id}:sidecar_source", "source": "sidecar_rescue_v01"}],
                "source_regions": source_regions_from_sidecar(sidecar_doc),
                "source_region_groups": groups,
                "asset_groups": asset_groups_from_sidecar(sidecar_doc),
                "semantic_objects": target_objects + list(hint_objects_by_id.values()),
                "relations": relations,
                "uncertainties": [{"type": "model_status_not_accepted_as_verified_fact"}],
                "model_call_refs": {"source_model_call_doc_id": doc_id},
            }
        )
    return {
        "schema": "english_text_first_knowledge_structure_contract_v02.projection",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "model_graph_regression_v01.calls adapted to decontaminated contract input",
        "documents": documents,
        "model_calls": model_calls.get("calls", []),
        "validation_summary": {},
    }


def target_rows(eligibility: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{row.get('doc_id')}:{row.get('object_id')}": row for row in eligibility.get("rows", []) or []}


def compare_with_human(human_review: dict[str, Any], eligibility: dict[str, Any]) -> dict[str, Any]:
    rows_by_key = target_rows(eligibility)
    rows = []
    for human in human_review.get("packets", []) or []:
        doc_id = str(human.get("doc_id"))
        packet_id = str(human.get("packet_id"))
        unit_id = packet_id.split(f"{doc_id}_", 1)[-1] if packet_id.startswith(f"{doc_id}_") else packet_id
        object_id = object_id_for_target(doc_id, unit_id)
        gate = rows_by_key.get(f"{doc_id}:{object_id}", {})
        qbank = str(gate.get("qbank_as_is", "MISSING"))
        human_verdict = str(human.get("human_verdict", ""))
        human_blocks_release = human_verdict.startswith("HOLD")
        contract_blocks_release = qbank in {"INELIGIBLE", "REQUIRES_REVIEW", "MISSING"}
        rows.append(
            {
                "packet_id": packet_id,
                "doc_id": doc_id,
                "object_id": object_id,
                "human_verdict": human_verdict,
                "human_blocks_release": human_blocks_release,
                "contract_qbank_as_is": qbank,
                "contract_knowledge_structure": gate.get("knowledge_structure", "MISSING"),
                "contract_faithful_material": gate.get("faithful_material", "MISSING"),
                "contract_blocks_release": contract_blocks_release,
                "safety_direction_matches": human_blocks_release == contract_blocks_release,
                "acceptance_recall_matches": (not human_blocks_release) and (not contract_blocks_release),
            }
        )
    return {
        "schema": f"{SCHEMA}.human_comparison",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
        "counts": {
            "items": len(rows),
            "safety_direction_matched": sum(1 for row in rows if row["safety_direction_matches"]),
            "safety_direction_mismatched": sum(1 for row in rows if not row["safety_direction_matches"]),
            "accepted_by_human": sum(1 for row in rows if not row["human_blocks_release"]),
            "accepted_by_contract": sum(1 for row in rows if not row["contract_blocks_release"]),
        },
    }


def render_html(path: Path, summary: dict[str, Any], validation: dict[str, Any], comparison: dict[str, Any]) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>KS Contract Regression From Model Calls</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.45}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ddd;padding:8px;vertical-align:top}th{background:#f5f5f5}.ok{background:#eef9f0}.bad{background:#fff0f0}.mono{font-family:Consolas,monospace;white-space:pre-wrap}</style>",
        "<h1>KS Contract Regression From Model Calls</h1>",
        "<p>This review adapts real model graph calls into the decontaminated contract. Raw model projection status is preserved but not accepted as verified gate input.</p>",
        "<h2>Summary</h2>",
        f"<pre class='mono'>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>",
        "<h2>Validation</h2>",
        f"<pre class='mono'>{html.escape(json.dumps(validation, ensure_ascii=False, indent=2))}</pre>",
        "<h2>Human Comparison</h2>",
        f"<p>safety direction matched: {comparison['counts']['safety_direction_matched']} / {comparison['counts']['items']}; accepted by contract: {comparison['counts']['accepted_by_contract']}</p>",
        "<table><thead><tr><th>packet</th><th>human</th><th>contract projection</th><th>safety match</th></tr></thead><tbody>",
    ]
    for row in comparison["rows"]:
        css = "ok" if row["safety_direction_matches"] else "bad"
        projection = {
            "qbank_as_is": row["contract_qbank_as_is"],
            "knowledge_structure": row["contract_knowledge_structure"],
            "faithful_material": row["contract_faithful_material"],
        }
        parts.append(f"<tr class='{css}'>")
        parts.append(f"<td>{html.escape(row['packet_id'])}<br><small>{html.escape(row['object_id'])}</small></td>")
        parts.append(f"<td>{html.escape(row['human_verdict'])}</td>")
        parts.append(f"<td><pre class='mono'>{html.escape(json.dumps(projection, ensure_ascii=False, indent=2))}</pre></td>")
        parts.append(f"<td>{row['safety_direction_matches']}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    write_text(path, "\n".join(parts))


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = workspace_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar_graph = read_json(workspace_path(args.sidecar_graph))
    model_calls = read_json(workspace_path(args.model_calls))
    human_review = read_json(workspace_path(args.human_review))
    contract_input = build_contract_input(sidecar_graph, model_calls)
    contract_input_path = out_dir / "model_claims_contract_input.json"
    write_json(contract_input_path, contract_input)
    validation = validate_all(contract_input)
    write_json(out_dir / "contract_validator_report.json", validation)
    decontam_args = argparse.Namespace(input=str(contract_input_path), out=str(out_dir / "decontaminated_contract"))
    decontam_summary = run_decontaminated_contract(decontam_args)
    eligibility = read_json(out_dir / "decontaminated_contract" / "projection_eligibility.json")
    comparison = compare_with_human(human_review, eligibility)
    write_json(out_dir / "contract_vs_human_comparison.json", comparison)
    summary = {
        "schema": f"{SCHEMA}.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "new_model_calls": 0,
        "model_calls_source": rel_workspace(workspace_path(args.model_calls)),
        "contract_input": rel_workspace(contract_input_path),
        "decontaminated_contract_dir": rel_workspace(out_dir / "decontaminated_contract"),
        "json_schema_valid": validation["json_schema_valid"],
        "reference_integrity_valid": validation["reference_integrity_valid"],
        "semantic_contract_valid": validation["semantic_contract_valid"],
        "projection_gate_valid": validation["projection_gate_valid"],
        "decontaminated_final_label": decontam_summary.get("final_label"),
        "comparison_counts": comparison["counts"],
        "review_html": rel_workspace(out_dir / "contract_regression_review.html"),
    }
    write_json(out_dir / "run_summary.json", summary)
    render_html(out_dir / "contract_regression_review.html", summary, validation, comparison)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Adapt real model graph calls into the decontaminated KS contract and compare with human review.")
    parser.add_argument("--sidecar-graph", required=True)
    parser.add_argument("--model-calls", required=True)
    parser.add_argument("--human-review", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
