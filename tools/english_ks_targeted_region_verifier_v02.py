from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import english_ks_contract_v02 as contract
from english_ks_reference_validator_v02 import validate_all
from english_ks_review_renderer_v02 import render_review


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
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


def image_to_data_url(path: Path) -> str:
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def parse_json(text: str) -> tuple[dict[str, Any] | None, str]:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        clean = clean[start : end + 1]
    try:
        return json.loads(clean), ""
    except json.JSONDecodeError as exc:
        return None, str(exc)


def verifier_prompt() -> str:
    return """You are a targeted Source Region Coverage Verifier.

You verify only source-region coverage for already identified knowledge-structure objects.
You must not create QuestionPackets.
You must not create asset files or claim asset_group coverage.
You may propose source page regions only from the supplied page images.

Task:
For each target object, inspect the supplied page images and return the minimal ordered source regions that cover the object as it appears in the requested pages.

Important:
- A source_region_group may reference original page regions.
- An asset_group requires real derived files; do not output asset_group.
- If you cannot determine complete coverage, set coverage_status=UNVERIFIED or PARTIAL and explain.
- Use bbox_norm1000 coordinates [x1,y1,x2,y2] with 0..1000 page-normalized coordinates.
- Output JSON only."""


def call_verifier(api_key: str, model: str, timeout: int, payload: dict[str, Any], image_paths: list[Path]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]
    for image_path in image_paths:
        content.append({"type": "text", "text": image_path.name})
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": verifier_prompt()},
            {"role": "user", "content": content},
        ],
    }
    started = time.time()
    response = requests.post(
        ARK_API_URL,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    raw = response.json()
    text = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = parse_json(text)
    return {
        "call_id": f"targeted_region_verifier:{payload.get('document_id', 'document')}",
        "model": model,
        "called": True,
        "parsed": parsed is not None,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
        "usage": raw.get("usage", {}),
        "raw_response": raw,
        "result": parsed or {},
        "prompt_snapshot": verifier_prompt(),
        "input_manifest_sha256": contract.sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        "image_manifest": [
            {"path": rel_workspace(path), "sha256": contract.sha256_file(path)}
            for path in image_paths
        ],
    }


def validate_verifier_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    groups = result.get("source_region_groups")
    if not isinstance(groups, list):
        return ["source_region_groups_missing"]
    for g_index, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"group_{g_index}_not_object")
            continue
        if not group.get("object_id"):
            errors.append(f"group_{g_index}_object_id_missing")
        if group.get("coverage_status") not in {"COMPLETE", "PARTIAL", "UNVERIFIED"}:
            errors.append(f"group_{g_index}_coverage_status_invalid")
        members = group.get("members")
        if not isinstance(members, list) or not members:
            errors.append(f"group_{g_index}_members_missing")
            continue
        for m_index, member in enumerate(members):
            bbox = member.get("bbox_norm1000")
            if not isinstance(bbox, list) or len(bbox) != 4:
                errors.append(f"group_{g_index}_member_{m_index}_bbox_invalid")
                continue
            try:
                x1, y1, x2, y2 = [float(v) for v in bbox]
            except (TypeError, ValueError):
                errors.append(f"group_{g_index}_member_{m_index}_bbox_not_numeric")
                continue
            if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
                errors.append(f"group_{g_index}_member_{m_index}_bbox_out_of_range")
            if int(member.get("page_number", 0) or 0) <= 0:
                errors.append(f"group_{g_index}_member_{m_index}_page_invalid")
    return errors


def apply_verified_regions(payload: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(payload, ensure_ascii=False))
    doc_id = str(call.get("document_id", "") or call.get("result", {}).get("document_id", ""))
    doc = next(doc for doc in updated["documents"] if doc["doc_id"] == doc_id)
    object_by_id = {obj["object_id"]: obj for obj in doc["semantic_objects"]}
    existing_region_ids = {region["evidence_id"] for region in doc["source_regions"]}
    group_id_replacements: dict[str, str] = {}
    # Remove old source-region groups for targeted objects. Keep old regions as historical evidence.
    targeted_ids = {str(group.get("object_id")) for group in call.get("result", {}).get("source_region_groups", [])}
    doc["source_region_groups"] = [
        group
        for group in doc.get("source_region_groups", [])
        if str(group.get("owner_object_id", "") or group.get("source_region_group_id", "")).replace("srg_", "") not in targeted_ids
        and not any(str(obj_id).replace(":", "_") in str(group.get("source_region_group_id", "")) for obj_id in targeted_ids)
    ]
    for group in call.get("result", {}).get("source_region_groups", []) or []:
        object_id = str(group.get("object_id"))
        obj = object_by_id.get(object_id)
        if not obj:
            continue
        evidence_refs: list[str] = []
        members: list[dict[str, Any]] = []
        for index, member in enumerate(group.get("members", []) or []):
            page_no = int(member.get("page_number", 0) or 0)
            evidence_id = f"ev_verified_{object_id}_{index + 1:03d}"
            suffix = 1
            while evidence_id in existing_region_ids:
                suffix += 1
                evidence_id = f"ev_verified_{object_id}_{index + 1:03d}_{suffix}"
            existing_region_ids.add(evidence_id)
            region_id = f"verified:{object_id}:p{page_no:03d}:{index + 1:03d}"
            bbox = [float(v) for v in member["bbox_norm1000"]]
            doc["source_regions"].append(
                {
                    "evidence_id": evidence_id,
                    "source_bundle_id": (obj.get("source_bundle_refs") or [""])[0],
                    "page_id": f"{doc['doc_id']}:page_{page_no:03d}",
                    "page_number": page_no,
                    "region_id": region_id,
                    "bbox_norm1000": bbox,
                    "role": str(member.get("role", "verified_source_region")),
                    "source_kind": "original_page",
                    "verification_status": "VERIFIED" if group.get("coverage_status") == "COMPLETE" else "PROPOSED",
                    "verified_by_call_id": call["call_id"],
                }
            )
            evidence_refs.append(evidence_id)
            members.append(
                {
                    "evidence_id": evidence_id,
                    "page_id": f"{doc['doc_id']}:page_{page_no:03d}",
                    "region_id": region_id,
                    "sequence": int(member.get("sequence", index + 1) or index + 1),
                }
            )
        source_region_group_id = f"srg_verified_{object_id}"
        for old_group_id in obj.get("source_region_group_refs", []) or []:
            group_id_replacements[str(old_group_id)] = source_region_group_id
        doc["source_region_groups"].append(
            {
                "source_region_group_id": source_region_group_id,
                "owner_object_id": object_id,
                "purpose": str(group.get("purpose", obj.get("primary_role", {}).get("label", "source_region_grounding"))),
                "members": members,
                "coverage_status": group.get("coverage_status", "UNVERIFIED"),
                "coverage_verification": {
                    "verified": group.get("coverage_status") == "COMPLETE",
                    "method": "targeted_model_verifier",
                    "model": call.get("model"),
                    "call_id": call["call_id"],
                    "evidence_refs": evidence_refs,
                    "reason": group.get("reason", ""),
                },
                "source_region_group_only_not_asset": True,
            }
        )
        obj["typed_evidence_refs"] = evidence_refs
        obj["source_region_group_refs"] = [source_region_group_id]
        obj["asset_group_refs"] = []
        obj["completeness"]["source_region_grounding"] = "COMPLETE" if group.get("coverage_status") == "COMPLETE" else "UNVERIFIED"
        obj["completeness"]["asset_grounding"] = "UNVERIFIED"
        obj["human_review_status"] = "NOT_REVIEWED" if group.get("coverage_status") == "COMPLETE" else "REQUIRED"
        for target in ("knowledge_structure", "faithful_material"):
            obj["projections"][target]["status"] = "READY_WITH_SOURCE_REGIONS" if group.get("coverage_status") == "COMPLETE" else "NEEDS_REVIEW"
            obj["projections"][target]["capability_level"] = "SOURCE_REGION_BACKED"
            obj["projections"][target]["reason"] = "Targeted verifier confirmed source-region coverage; no asset group or derived crop is claimed."
    for relation in doc.get("relations", []) or []:
        relation["evidence_refs"] = [
            group_id_replacements.get(str(ref), ref)
            for ref in relation.get("evidence_refs", []) or []
        ]
    updated["model_calls"].append(
        {
            "call_id": call["call_id"],
            "model": call.get("model"),
            "prompt_version": "targeted_region_verifier_v02",
            "prompt_sha256": contract.sha256_text(call.get("prompt_snapshot", "")),
            "input_manifest_sha256": call.get("input_manifest_sha256", ""),
            "attempts": [
                {
                    "parsed": call.get("parsed"),
                    "parse_error": call.get("parse_error"),
                    "schema_errors": validate_verifier_result(call.get("result", {})),
                    "usage": call.get("usage", {}),
                    "latency_seconds": call.get("latency_seconds"),
                }
            ],
            "parsed": call.get("parsed"),
            "json_schema_valid_v02": not validate_verifier_result(call.get("result", {})),
            "semantic_validation": "targeted_source_region_coverage_only",
            "raw_response_ref": "targeted_region_verifier_call.json",
        }
    )
    return updated


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = str(args.api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    if not api_key and not args.reuse_call:
        raise SystemExit("missing_ark_api_key")
    input_dir = workspace_path(args.v02_dir)
    out_dir = workspace_path(args.out)
    if out_dir.exists() and args.clean:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = contract.read_json(input_dir / "knowledge_structure_projection_v02.json")
    doc = next(doc for doc in payload["documents"] if doc["doc_id"] == args.doc_id)
    target_ids = [item.strip() for item in args.object_ids.split(",") if item.strip()]
    targets = [
        {
            "object_id": obj["object_id"],
            "open_description": obj["open_description"],
            "primary_role": obj["primary_role"],
            "current_typed_evidence_refs": obj.get("typed_evidence_refs", []),
            "current_source_region_groups": [
                group
                for group in doc.get("source_region_groups", [])
                if group.get("source_region_group_id") in obj.get("source_region_group_refs", [])
            ],
            "current_completeness": obj.get("completeness", {}),
        }
        for obj in doc["semantic_objects"]
        if obj["object_id"] in target_ids
    ]
    image_paths = [
        workspace_path(image["path"])
        for image in doc.get("source_page_images", [])
        if int(image.get("page_number", 0) or 0) in {1, 2, 3}
    ]
    verifier_payload = {
        "schema_request": "english_text_first_knowledge_structure_contract_v02.targeted_region_verifier",
        "document_id": doc["doc_id"],
        "targets": targets,
        "page_images": [
            {"page_number": int(image.get("page_number", 0) or 0), "path": image.get("path"), "sha256": image.get("sha256")}
            for image in doc.get("source_page_images", [])
            if int(image.get("page_number", 0) or 0) in {1, 2, 3}
        ],
        "output_contract": {
            "source_region_groups": [
                {
                    "object_id": "target_object_id",
                    "purpose": "open text",
                    "coverage_status": "COMPLETE|PARTIAL|UNVERIFIED",
                    "members": [
                        {
                            "page_number": 1,
                            "bbox_norm1000": [0, 0, 1000, 1000],
                            "role": "table_fragment|answer_fragment|continuation_fragment",
                            "sequence": 1,
                        }
                    ],
                    "reason": "string",
                    "confidence": 0.0,
                }
            ],
            "uncertainties": [],
        },
    }
    if args.reuse_call:
        call = contract.read_json(workspace_path(args.reuse_call))
    else:
        call = call_verifier(api_key, args.model, int(args.timeout), verifier_payload, image_paths)
    call["document_id"] = doc["doc_id"]
    call["schema_errors"] = validate_verifier_result(call.get("result", {}))
    contract.write_json(out_dir / "targeted_region_verifier_call.json", call)
    if call["schema_errors"]:
        updated = payload
    else:
        updated = apply_verified_regions(payload, call)
    validation = validate_all(updated)
    updated["validation_summary"] = validation
    updated["targeted_verification_summary"] = {
        "target_object_ids": target_ids,
        "new_model_calls": 0 if args.reuse_call else 1,
        "reused_model_call": bool(args.reuse_call),
        "verifier_schema_valid": not call["schema_errors"],
        "verifier_schema_errors": call["schema_errors"],
        "source_region_groups_verified": [
            group
            for doc_item in updated.get("documents", [])
            if doc_item.get("doc_id") == doc["doc_id"]
            for group in doc_item.get("source_region_groups", [])
            if group.get("owner_object_id") in target_ids and group.get("coverage_status") == "COMPLETE"
        ],
        "asset_groups_created": 0,
    }
    contract.write_json(out_dir / "knowledge_structure_projection_v02_targeted.json", updated)
    contract.write_json(out_dir / "semantic_validation_report.json", {k: v for k, v in validation.items() if k.startswith("semantic")})
    contract.write_json(out_dir / "relation_validation_report.json", {k: v for k, v in validation.items() if k.startswith("reference")})
    contract.write_json(out_dir / "asset_grounding_report.json", {"targeted_source_region_groups": updated["targeted_verification_summary"]["source_region_groups_verified"], "asset_groups_created": 0})
    contract.write_json(out_dir / "model_calls.json", {"schema": "english_text_first_knowledge_structure_contract_v02.model_calls", "calls": updated.get("model_calls", [])})
    review = render_review(updated, out_dir, WORKSPACE_ROOT)
    target_objects = {
        obj["object_id"]: obj
        for doc_item in updated["documents"]
        if doc_item["doc_id"] == doc["doc_id"]
        for obj in doc_item["semantic_objects"]
        if obj["object_id"] in target_ids
    }
    target_region_ready = all(
        target_objects[obj_id]["source_region_group_refs"]
        and target_objects[obj_id]["completeness"].get("source_region_grounding") == "COMPLETE"
        and not target_objects[obj_id]["asset_group_refs"]
        for obj_id in target_ids
        if obj_id in target_objects
    )
    summary = {
        "schema": "english_text_first_knowledge_structure_contract_v02.targeted_region_verifier.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": rel_workspace(out_dir),
        "new_model_calls": 0 if args.reuse_call else 1,
        "reused_model_call": bool(args.reuse_call),
        "runtime_import_enabled": False,
        "target_object_ids": target_ids,
        "target_source_region_grounding_complete": target_region_ready,
        "asset_groups_created": 0,
        "json_schema_valid": validation["json_schema_valid"],
        "reference_integrity_valid": validation["reference_integrity_valid"],
        "semantic_contract_valid": validation["semantic_contract_valid"],
        "projection_gate_valid": validation["projection_gate_valid"],
        "review_html": rel_workspace(review),
        "final_label": "KNOWLEDGE_STRUCTURE_SOURCE_REGION_VERIFIED_FOR_TARGETS" if target_region_ready else "SOURCE_GROUNDING_BLOCKED",
    }
    contract.write_json(out_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Targeted source-region coverage verifier for KS contract v0.2.")
    parser.add_argument("--v02-dir", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--object-ids", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--reuse-call", default="")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
