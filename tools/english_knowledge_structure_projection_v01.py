from __future__ import annotations

import argparse
import base64
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
SCHEMA_VERSION = "english_text_first_knowledge_structure_projection_v01"
CORE_PREDICATES = {"contains", "depends_on", "answers", "uses_asset", "continues_on", "other"}
PRODUCTION_ELIGIBLE = False
FIXTURE_SPECIFIC = True


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


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def parse_json(text: str) -> tuple[dict[str, Any] | None, str]:
    clean = str(text or "").strip()
    try:
        return json.loads(clean), ""
    except json.JSONDecodeError as exc:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(clean[start : end + 1]), ""
            except json.JSONDecodeError as nested:
                return None, str(nested)
        return None, str(exc)


def model_call(
    *,
    api_key: str,
    model: str,
    timeout: int,
    system_prompt: str,
    payload: dict[str, Any],
    image_paths: list[Path],
    call_id: str,
    max_retries: int,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    validation_errors: list[str] = []
    for attempt in range(max_retries + 1):
        user_payload = dict(payload)
        if validation_errors:
            user_payload["previous_validation_errors"] = validation_errors
            user_payload["retry_instruction"] = "Repair only the JSON contract. Do not change semantic claims unless required by the schema."
        content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(user_payload, ensure_ascii=False, indent=2)}]
        for image_path in image_paths:
            if image_path.exists():
                content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 12000,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
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
        raw: dict[str, Any]
        try:
            response.raise_for_status()
            raw = response.json()
            content_text = str(raw["choices"][0]["message"]["content"])
            parsed, parse_error = parse_json(content_text)
        except Exception as exc:  # noqa: BLE001 - persisted as call evidence
            raw = {"http_status": response.status_code, "text": response.text[:2000]}
            parsed = None
            parse_error = f"{type(exc).__name__}: {exc}"
            content_text = ""
        repaired = repair_model_payload(parsed)
        errors = validate_model_payload(repaired["payload"])
        attempts.append(
            {
                "attempt": attempt + 1,
                "latency_seconds": round(time.time() - started, 3),
                "image_count": len([path for path in image_paths if path.exists()]),
                "parsed": parsed is not None,
                "parse_error": parse_error,
                "schema_errors": errors,
                "structural_repair_notes": repaired["notes"],
                "usage": raw.get("usage", {}),
                "raw_response": raw,
                "raw_content_on_failure": "" if parsed else content_text,
                "result": repaired["payload"] or {},
            }
        )
        if repaired["payload"] is not None and not errors:
            return {
                "call_id": call_id,
                "called": True,
                "parsed": True,
                "schema_valid": True,
                "attempts": attempts,
                "result": repaired["payload"],
            }
        validation_errors = errors or [parse_error or "json_parse_failed"]
    return {
        "call_id": call_id,
        "called": True,
        "parsed": bool(attempts and attempts[-1].get("parsed")),
        "schema_valid": False,
        "attempts": attempts,
        "result": attempts[-1].get("result", {}) if attempts else {},
    }


def repair_model_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"payload": None, "notes": []}
    notes: list[str] = []
    repaired = dict(payload)
    if not isinstance(repaired.get("semantic_objects"), list):
        repaired["semantic_objects"] = []
        notes.append("semantic_objects_defaulted_to_empty_array")
    if not isinstance(repaired.get("relations"), list):
        repaired["relations"] = []
        notes.append("relations_defaulted_to_empty_array")
    if not isinstance(repaired.get("uncertainties"), list):
        repaired["uncertainties"] = []
        notes.append("uncertainties_defaulted_to_empty_array")
    normalized_relations: list[dict[str, Any]] = []
    for index, rel in enumerate(repaired.get("relations", []) or []):
        if not isinstance(rel, dict):
            notes.append(f"relations[{index}]_dropped_non_object")
            continue
        fixed = dict(rel)
        if "subject" not in fixed and "subject_id" in fixed:
            fixed["subject"] = fixed["subject_id"]
            notes.append(f"relations[{index}].subject_id_mapped_to_subject")
        if "object" not in fixed and "object_id" in fixed:
            fixed["object"] = fixed["object_id"]
            notes.append(f"relations[{index}].object_id_mapped_to_object")
        predicate = str(fixed.get("predicate", "") or "")
        if predicate not in CORE_PREDICATES:
            fixed["predicate_open_text"] = fixed.get("predicate_open_text") or predicate or "unspecified_relation"
            fixed["predicate"] = "other"
            notes.append(f"relations[{index}].predicate_mapped_to_other")
        fixed.setdefault("predicate_open_text", fixed.get("predicate", "other"))
        fixed.setdefault("reason", str(fixed.get("predicate_open_text", "")))
        fixed.setdefault("evidence_refs", [])
        fixed.setdefault("confidence", 0.0)
        normalized_relations.append(fixed)
    repaired["relations"] = normalized_relations
    for index, obj in enumerate(repaired.get("semantic_objects", []) or []):
        if not isinstance(obj, dict):
            continue
        obj.setdefault("source_bundle_refs", [])
        obj.setdefault("source_evidence_refs", [])
        obj.setdefault("source_asset_refs", [])
        obj.setdefault("secondary_roles", [])
        obj.setdefault("child_objects", [])
        obj.setdefault("uncertainties", [])
        obj.setdefault("layout_dependency", {"required": False, "reason": ""})
        obj.setdefault("states", {"student": {"description": ""}, "teacher": {"description": ""}})
        obj.setdefault("structure", {"representation_status": "asset_only", "rows": [], "columns": [], "cells": []})
        if "open_description" not in obj:
            obj["open_description"] = str(obj.get("description", "") or obj.get("object_id", ""))
            notes.append(f"semantic_objects[{index}].open_description_defaulted")
        if "primary_role" not in obj or not isinstance(obj.get("primary_role"), dict):
            obj["primary_role"] = {"label": str(obj.get("role", "unknown")), "confidence": 0.0}
            notes.append(f"semantic_objects[{index}].primary_role_defaulted")
    return {"payload": repaired, "notes": notes}


def validate_model_payload(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return ["payload_not_object"]
    errors: list[str] = []
    if not isinstance(payload.get("semantic_objects"), list):
        errors.append("semantic_objects_missing_or_not_array")
    if not isinstance(payload.get("relations"), list):
        errors.append("relations_missing_or_not_array")
    if not isinstance(payload.get("uncertainties"), list):
        errors.append("uncertainties_missing_or_not_array")
    for index, obj in enumerate(payload.get("semantic_objects", []) or []):
        if not isinstance(obj, dict):
            errors.append(f"semantic_objects[{index}]_not_object")
            continue
        for key in ("object_id", "source_bundle_refs", "open_description", "primary_role", "source_evidence_refs"):
            if key not in obj:
                errors.append(f"semantic_objects[{index}].{key}_missing")
        role = obj.get("primary_role", {})
        if not isinstance(role, dict) or "label" not in role or "confidence" not in role:
            errors.append(f"semantic_objects[{index}].primary_role_invalid")
    for index, rel in enumerate(payload.get("relations", []) or []):
        if not isinstance(rel, dict):
            errors.append(f"relations[{index}]_not_object")
            continue
        for key in ("subject", "predicate", "object", "reason", "evidence_refs", "confidence"):
            if key not in rel:
                errors.append(f"relations[{index}].{key}_missing")
    return errors


def knowledge_composer_prompt() -> str:
    return """You are the Knowledge Structure Composer for an evidence-first graph pipeline.

Task:
Identify semantic teaching objects inside source bundles. A source bundle is a preservation container, not a Runtime object.

Responsibilities:
- Decide each object's main teaching role from evidence.
- Preserve knowledge structures, fillable templates, teacher-filled states, embedded activities, examples, annotations, and standalone practices as separate semantic objects when needed.
- Express relations such as contains, depends_on, answers, uses_asset, continues_on, other.
- Treat blanks, tables, red text, and answer-like text only as observations. They are not automatic QuestionPacket evidence.

Forbidden:
- Do not output READY, BLOCKED, release, or final projection status.
- Do not classify by document family.
- Do not invent missing text.
- Do not force source bundles into QuestionPacket shape.

Return JSON only with keys: semantic_objects, relations, uncertainties."""


def knowledge_verifier_prompt() -> str:
    return """You are the Knowledge Structure Verifier.

Verify the Composer's claims. Do not create Runtime packets.

For each semantic object, verify:
- role_verification: whether the main role is supported by page evidence.
- structural_completeness: whether key rows/columns/headers/notes or visual regions are preserved.
- state_verification: whether student blank state and teacher filled/reference state are distinguishable when relevant.
- child_object_verification: whether embedded activities or standalone practices have been swallowed incorrectly.
- projection_facts: whether the original object can enter qbank as-is, is only derivable, or is better preserved as a knowledge structure/faithful material.

Rules:
- Blanks are observations, not automatic questions.
- Red or filled content may be teacher reference, annotation, completed knowledge state, explanation, or solution; verify from structure.
- If layout carries meaning, set layout_dependency.required=true.
- Do not output final READY/BLOCKED. Output facts for the deterministic projector.

Return JSON only with keys: semantic_objects, relations, uncertainties."""


def visual_probe_source_bundles(probe_dir: Path, doc_id: str) -> tuple[list[dict[str, Any]], list[Path]]:
    response = read_json(probe_dir / "visual_unit_planner_response.json")
    page_images = sorted((probe_dir / "rendered_pages_120dpi").glob("page_*.png"))
    bundles: list[dict[str, Any]] = []
    for unit in response.get("units", []):
        if not isinstance(unit, dict):
            continue
        bundle_id = f"{doc_id}:{unit.get('unit_id')}"
        bundles.append(
            {
                "source_bundle_id": bundle_id,
                "doc_id": doc_id,
                "source": "visual_unit_planner_probe",
                "semantic_role_observation": unit.get("semantic_role", ""),
                "route_observation": unit.get("route", ""),
                "pages": unit.get("pages", []),
                "fragments": unit.get("fragments", []),
                "child_assets": unit.get("child_assets", []),
                "contains_observation": unit.get("contains", []),
                "continuation": unit.get("continuation", False),
                "model_reason": unit.get("reason", ""),
                "confidence": unit.get("confidence"),
                "raw_unit": unit,
            }
        )
    return bundles, page_images


def old_grammar_source_bundles(sidecar_root: Path, human_review_path: Path) -> tuple[list[dict[str, Any]], list[Path], dict[str, Any]]:
    graph = read_json(sidecar_root / "semantic_graph.json")
    human_review = read_json(human_review_path)
    doc = next(doc for doc in graph["documents"] if doc["doc_id"] == "grammar_clauses")
    obj_by_id = {obj["id"]: obj for obj in doc["semantic_objects"]}
    claims_subject: dict[str, list[dict[str, Any]]] = {}
    claims_object: dict[str, list[dict[str, Any]]] = {}
    for claim in doc.get("semantic_claims", []):
        claims_subject.setdefault(str(claim.get("subject", "")), []).append(claim)
        claims_object.setdefault(str(claim.get("object", "")), []).append(claim)
    page_image_by_page_id = {
        str(page.get("page_id")): workspace_path(str(page.get("image_path")))
        for page in doc["source_evidence"]["pages"]
        if page.get("image_path")
    }
    rows = [
        item
        for item in human_review.get("packets", [])
        if item.get("doc_id") == "grammar_clauses" and item.get("human_verdict") == "HOLD_PARENT_RELATION"
    ]
    bundles: list[dict[str, Any]] = []
    image_paths: list[Path] = []
    for row in rows:
        source_unit_id = str(row["packet_id"]).replace("grammar_clauses_", "")
        obj = obj_by_id[f"grammar_clauses:{source_unit_id}"]
        related_ids = {
            str(claim.get("object", ""))
            for claim in claims_subject.get(obj["id"], [])
            if claim.get("predicate") in {"depends_on", "shares_context", "uses_asset"}
        }
        related_ids.update(
            str(claim.get("subject", ""))
            for claim in claims_object.get(obj["id"], [])
            if claim.get("predicate") in {"answers", "depends_on", "shares_context"}
        )
        related_objects = [obj_by_id[item] for item in sorted(related_ids) if item in obj_by_id]
        for page_id in obj.get("page_ids", []):
            path = page_image_by_page_id.get(str(page_id))
            if path and path.exists() and path not in image_paths:
                image_paths.append(path)
        bundles.append(
            {
                "source_bundle_id": obj["id"],
                "doc_id": "grammar_clauses",
                "source": "v02d_sidecar_graph_old_human_review",
                "packet_id": row["packet_id"],
                "old_human_verdict": row["human_verdict"],
                "old_human_note": row.get("note", ""),
                "object": {
                    "id": obj["id"],
                    "title": obj.get("title", ""),
                    "kind": obj.get("kind", {}),
                    "observations": obj.get("observations", []),
                    "line_refs": obj.get("line_refs", []),
                    "source_text": obj.get("source_text", ""),
                    "page_ids": obj.get("page_ids", []),
                    "asset_refs": obj.get("asset_refs", []),
                },
                "outgoing_claims": claims_subject.get(obj["id"], []),
                "incoming_claims": claims_object.get(obj["id"], []),
                "related_objects": [
                    {
                        "id": item["id"],
                        "title": item.get("title", ""),
                        "kind": item.get("kind", {}),
                        "observations": item.get("observations", []),
                        "line_refs": item.get("line_refs", []),
                        "source_text": item.get("source_text", ""),
                    }
                    for item in related_objects
                ],
            }
        )
    return bundles, image_paths, human_review


def projection_from_verified_object(obj: dict[str, Any], source_complete: bool) -> dict[str, Any]:
    facts = obj.get("projection_facts", {}) if isinstance(obj.get("projection_facts"), dict) else {}
    role = obj.get("primary_role", {}) if isinstance(obj.get("primary_role"), dict) else {}
    label = str(role.get("label", "") or "").lower()
    unresolved = bool(obj.get("unresolved_required_evidence"))
    knowledge_supported = bool(facts.get("knowledge_structure_supported"))
    qbank_as_is = bool(facts.get("qbank_as_is_supported"))
    derivable = bool(facts.get("qbank_derivable"))
    layout_required = bool(obj.get("layout_dependency", {}).get("required")) if isinstance(obj.get("layout_dependency"), dict) else False
    structure_status = str(obj.get("structure", {}).get("representation_status", "asset_only") if isinstance(obj.get("structure"), dict) else "asset_only")

    if not source_complete or unresolved:
        qbank_status = "BLOCKED"
        knowledge_status = "BLOCKED"
        faithful_status = "BLOCKED"
    elif structure_status == "partial":
        qbank_status = "BLOCKED"
        knowledge_status = "BLOCKED"
        faithful_status = "READY_WITH_ASSET"
    else:
        if qbank_as_is:
            qbank_status = "READY"
        elif derivable:
            qbank_status = "DERIVABLE"
        elif "knowledge" in label or knowledge_supported:
            qbank_status = "UNSUPPORTED_AS_IS"
        else:
            qbank_status = "NEEDS_REVIEW"

        if knowledge_supported or "knowledge" in label:
            knowledge_status = "READY_WITH_ASSET" if layout_required or structure_status == "asset_only" else "READY"
        else:
            knowledge_status = "NEEDS_REVIEW"
        faithful_status = "READY_WITH_ASSET" if layout_required or structure_status == "asset_only" else "READY"

    return {
        "qbank": {
            "status": qbank_status,
            "reason": facts.get("qbank_reason", "computed from verified qbank_as_is_supported / qbank_derivable / role facts"),
        },
        "knowledge_structure": {
            "status": knowledge_status,
            "reason": facts.get("knowledge_reason", "computed from verified role and structural completeness facts"),
        },
        "faithful_material": {
            "status": faithful_status,
            "reason": facts.get("faithful_reason", "original page/region evidence is preserved as fact source"),
        },
    }


def build_projection(
    *,
    doc_id: str,
    source_bundles: list[dict[str, Any]],
    composer_call: dict[str, Any],
    verifier_call: dict[str, Any],
    source_complete: bool,
    image_paths: list[Path],
) -> dict[str, Any]:
    composer = composer_call.get("result", {}) if composer_call.get("schema_valid") else {}
    verifier = verifier_call.get("result", {}) if verifier_call.get("schema_valid") else {}
    objects = verifier.get("semantic_objects") or composer.get("semantic_objects") or []
    relations = verifier.get("relations") or composer.get("relations") or []
    out_objects = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        projected = dict(obj)
        projected["projections"] = projection_from_verified_object(projected, source_complete)
        out_objects.append(projected)
    return {
        "doc_id": doc_id,
        "source_bundle_count": len(source_bundles),
        "source_page_images": [rel_workspace(path) for path in image_paths],
        "source_bundles": source_bundles,
        "semantic_objects": out_objects,
        "relations": relations,
        "uncertainties": verifier.get("uncertainties") or composer.get("uncertainties") or [],
        "model_calls": {
            "composer_call_id": composer_call["call_id"],
            "verifier_call_id": verifier_call["call_id"],
        },
        "source_complete": source_complete,
    }


def write_schema(out_dir: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_VERSION}.schema.json",
        "title": "Minimal Knowledge Structure Projection Sidecar",
        "type": "object",
        "required": ["schema", "documents", "model_calls"],
        "properties": {
            "schema": {"const": f"{SCHEMA_VERSION}.knowledge_structure_projection"},
            "documents": {"type": "array"},
            "model_calls": {"type": "array"},
        },
        "notes": [
            "primary_role.label is open text; knowledge_structure is a recommended role, not a closed enum.",
            "qbank projection is target-specific and does not define source-material identity.",
            "The deterministic projector may not reinterpret source pages; it uses verified facts only.",
        ],
    }
    write_json(out_dir / "knowledge_structure_projection.schema.json", schema)


def canonical_gold_for_old_grammar(human_review: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in human_review.get("packets", []):
        if item.get("doc_id") != "grammar_clauses" or item.get("human_verdict") != "HOLD_PARENT_RELATION":
            continue
        rows.append(
            {
                "packet_id": item.get("packet_id"),
                "old_human_verdict": item.get("human_verdict"),
                "qbank_projection_gold": "NEEDS_REVIEW",
                "canonical_role_gold": "embedded_activity_or_fillable_template_under_knowledge_context",
                "knowledge_projection_gold": "PRESERVE_AS_CHILD_OBJECT",
                "faithful_projection_gold": "READY_WITH_SOURCE_CONTEXT",
                "note": item.get("note", ""),
            }
        )
    return rows


def compare_old_grammar(doc_projection: dict[str, Any], gold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    objects = doc_projection.get("semantic_objects", [])
    by_bundle: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        for bundle_ref in obj.get("source_bundle_refs", []) or []:
            by_bundle.setdefault(str(bundle_ref), []).append(obj)
    rows = []
    for gold in gold_rows:
        packet_id = str(gold["packet_id"])
        unit_id = packet_id.replace("grammar_clauses_", "")
        source_bundle_id = f"grammar_clauses:{unit_id}"
        projected_objects = by_bundle.get(source_bundle_id, [])
        qbank_statuses = [obj.get("projections", {}).get("qbank", {}).get("status") for obj in projected_objects]
        role_labels = [obj.get("primary_role", {}).get("label") for obj in projected_objects]
        relation_count = len(
            [
                rel
                for rel in doc_projection.get("relations", [])
                if rel.get("subject") in {obj.get("object_id") for obj in projected_objects}
                or rel.get("object") in {obj.get("object_id") for obj in projected_objects}
            ]
        )
        rows.append(
            {
                **gold,
                "model_role_labels": role_labels,
                "model_qbank_projection_statuses": qbank_statuses,
                "related_relation_count": relation_count,
                "directionally_aligned": bool(projected_objects)
                and all(status in {"UNSUPPORTED_AS_IS", "DERIVABLE", "NEEDS_REVIEW"} for status in qbank_statuses if status),
            }
        )
    return rows


def audit_report(projection: dict[str, Any], old_comparison: list[dict[str, Any]]) -> str:
    docs = {doc["doc_id"]: doc for doc in projection["documents"]}
    lines = [
        "# Knowledge Structure Projection v0.1 Audit",
        "",
        f"Date: {datetime.now().date().isoformat()}",
        "",
        "## Current Information Loss Audit",
        "",
        "- Old `v03b` grammar units include `question_like_unit` with `release_target=QuestionPacket_candidate`; that is where fillable grammar definitions start being treated as qbank candidates.",
        "- v05/v02d sidecar preserved source evidence and relations better, but its projector still targets current `QuestionPacket` status rather than a knowledge-structure target.",
        "- New visual probe output for `grammar_tense_voice` already has all five parent units as `semantic_role=knowledge`; this is model evidence that these bundles are source containers/knowledge modules, not direct packets.",
        "",
        "## Source Bundle vs Semantic Object",
        "",
        "- Source Bundle: rough preservation container from visual planner or old sidecar graph, with page images, fragments, child assets, source refs, and model observations.",
        "- Semantic Object: model-composed teaching object inside a bundle, such as knowledge structure, fillable template, embedded activity, annotation, or standalone practice.",
        "",
        "## Run Counts",
        "",
        f"- documents: {len(projection['documents'])}",
        f"- model_calls: {len(projection['model_calls'])}",
        f"- schema_valid_calls: {sum(1 for call in projection['model_calls'] if call.get('schema_valid'))}",
        f"- grammar_tense_voice objects: {len(docs.get('grammar_tense_voice_p001_p004', {}).get('semantic_objects', []))}",
        f"- old grammar replay items: {len(old_comparison)}",
        "",
        "## Old 5 Grammar Replay",
        "",
        "| packet | gold canonical role | qbank gold | model roles | model qbank | aligned |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in old_comparison:
        lines.append(
            "| {packet} | {role} | {gold} | {model_roles} | {statuses} | {aligned} |".format(
                packet=row["packet_id"],
                role=row["canonical_role_gold"],
                gold=row["qbank_projection_gold"],
                model_roles=", ".join(str(item) for item in row["model_role_labels"]),
                statuses=", ".join(str(item) for item in row["model_qbank_projection_statuses"]),
                aligned=row["directionally_aligned"],
            )
        )
    lines.extend(
        [
            "",
            "## What This Proves",
            "",
            "- It proves a minimal sidecar can represent knowledge structures separately from qbank projection on the selected material.",
            "- It does not prove Runtime readiness, DB readiness, or full production ingestion.",
            "- It does not replace v02d; it adds a target-specific knowledge projection sidecar for review.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_review_html(out_dir: Path, projection: dict[str, Any], old_comparison: list[dict[str, Any]]) -> Path:
    cards: list[str] = []
    for doc in projection["documents"]:
        image_tiles: list[str] = []
        for image_ref in doc.get("source_page_images", []):
            image_path = workspace_path(str(image_ref))
            src = rel_workspace(image_path)
            image_tiles.append(
                f"<figure><img src='{html.escape(str(image_path.resolve()))}' loading='lazy'><figcaption>{html.escape(src)}</figcaption></figure>"
            )
        image_html = (
            "<div class='image-grid'>" + "".join(image_tiles) + "</div>"
            if image_tiles
            else "<p class='muted'>No source page image refs were written for this document.</p>"
        )
        object_rows = []
        for obj in doc.get("semantic_objects", []):
            object_rows.append(
                "<tr>"
                f"<td><b>{html.escape(str(obj.get('object_id','')))}</b><br>{html.escape(str(obj.get('open_description','')))}</td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('primary_role', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('secondary_roles', []), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('layout_dependency', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('states', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('projections', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('uncertainties', []), ensure_ascii=False, indent=2))}</pre></td>"
                "</tr>"
            )
        cards.append(
            f"<section><h2>{html.escape(doc['doc_id'])}</h2>"
            f"<p>source bundles: {len(doc.get('source_bundles', []))}; semantic objects: {len(doc.get('semantic_objects', []))}; relations: {len(doc.get('relations', []))}</p>"
            f"{image_html}"
            "<table><thead><tr><th>Object</th><th>Primary role</th><th>Secondary</th><th>Layout</th><th>States</th><th>Projections</th><th>Uncertainty</th></tr></thead>"
            f"<tbody>{''.join(object_rows)}</tbody></table></section>"
        )
    old_rows = []
    for row in old_comparison:
        css = "ok" if row["directionally_aligned"] else "bad"
        old_rows.append(
            f"<tr class='{css}'><td>{html.escape(str(row['packet_id']))}</td>"
            f"<td>{html.escape(str(row['canonical_role_gold']))}</td>"
            f"<td>{html.escape(str(row['qbank_projection_gold']))}</td>"
            f"<td><pre>{html.escape(json.dumps(row['model_role_labels'], ensure_ascii=False, indent=2))}</pre></td>"
            f"<td><pre>{html.escape(json.dumps(row['model_qbank_projection_statuses'], ensure_ascii=False, indent=2))}</pre></td>"
            f"<td>{row['directionally_aligned']}</td></tr>"
        )
    html_text = f"""<!doctype html><html><head><meta charset="utf-8"><title>Knowledge Structure Projection Review</title>
<style>
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f8fb;color:#172033}}
section{{background:white;border:1px solid #dbe4f0;border-radius:10px;padding:14px;margin-bottom:18px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{border:1px solid #d8e0ea;padding:8px;vertical-align:top}}th{{background:#eef3f8}}
pre{{white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;max-height:260px;overflow:auto}}
.ok{{background:#edf9f0}}.bad{{background:#fff0f0}}.note{{background:#fff7ed;border:1px solid #fed7aa;padding:10px;border-radius:8px}}.muted{{color:#64748b}}
.image-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:10px 0 16px}}
figure{{margin:0}}figure img{{width:100%;height:auto;border:1px solid #d8e0ea;background:white}}figcaption{{font-size:11px;color:#64748b;word-break:break-all}}
</style></head><body>
<h1>Knowledge Structure Projection Review</h1>
<div class="note">This is a non-destructive sidecar. It does not import Runtime data and does not modify v02d artifacts.</div>
<h2>Summary</h2><pre>{html.escape(json.dumps(projection.get('summary', {}), ensure_ascii=False, indent=2))}</pre>
{''.join(cards)}
<section><h2>Old 5 Grammar Replay</h2><table><thead><tr><th>packet</th><th>canonical role gold</th><th>qbank gold</th><th>model roles</th><th>model qbank</th><th>aligned</th></tr></thead><tbody>{''.join(old_rows)}</tbody></table></section>
<section><h2>Model Calls</h2><pre>{html.escape(json.dumps(projection.get('model_calls', []), ensure_ascii=False, indent=2))}</pre></section>
</body></html>"""
    path = out_dir / "knowledge_structure_review.html"
    write_text(path, html_text)
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = str(args.api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing_ark_api_key")
    out_dir = workspace_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = args.model

    visual_bundles, visual_images = visual_probe_source_bundles(workspace_path(args.grammar_probe_dir), "grammar_tense_voice_p001_p004")
    old_bundles, old_images, human_review = old_grammar_source_bundles(workspace_path(args.sidecar_root), workspace_path(args.human_review))

    model_calls: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    requested_docs = {
        "both": {"grammar_tense_voice_p001_p004", "grammar_clauses_old5"},
        "new": {"grammar_tense_voice_p001_p004"},
        "old": {"grammar_clauses_old5"},
    }[args.doc_filter]
    for doc_id, bundles, images in (
        ("grammar_tense_voice_p001_p004", visual_bundles, visual_images),
        ("grammar_clauses_old5", old_bundles, old_images),
    ):
        if doc_id not in requested_docs:
            continue
        composer_payload = {
            "schema_request": f"{SCHEMA_VERSION}.composer_output",
            "document_id": doc_id,
            "source_bundles": bundles,
            "output_contract": {
                "semantic_objects": [
                    {
                        "object_id": "string",
                        "source_bundle_refs": ["string"],
                        "open_description": "string",
                        "primary_role": {"label": "open text", "confidence": 0.0},
                        "secondary_roles": [{"label": "open text", "confidence": 0.0}],
                        "source_evidence_refs": ["string"],
                        "source_asset_refs": ["string"],
                        "layout_dependency": {"required": False, "reason": "string"},
                        "states": {"student": {"description": "string"}, "teacher": {"description": "string"}},
                        "structure": {"representation_status": "complete|partial|asset_only", "rows": [], "columns": [], "cells": []},
                        "child_objects": [],
                        "uncertainties": [],
                    }
                ],
                "relations": [
                    {"subject": "string", "predicate": "contains|depends_on|answers|uses_asset|continues_on|other", "object": "string", "predicate_open_text": "string", "reason": "string", "evidence_refs": ["string"], "confidence": 0.0}
                ],
                "uncertainties": [],
            },
            "rules": [
                "Do not decide final projection status.",
                "Do not use document family as a rule.",
                "Do not turn blanks into QuestionPacket by default.",
            ],
        }
        composer = model_call(
            api_key=api_key,
            model=model,
            timeout=int(args.timeout),
            system_prompt=knowledge_composer_prompt(),
            payload=composer_payload,
            image_paths=images,
            call_id=f"{doc_id}:composer",
            max_retries=int(args.max_retries),
        )
        model_calls.append(composer)
        verifier_payload = {
            "schema_request": f"{SCHEMA_VERSION}.verifier_output",
            "document_id": doc_id,
            "source_bundles": bundles,
            "composer_result": composer.get("result", {}),
            "output_contract": {
                "semantic_objects": [
                    {
                        "object_id": "string",
                        "source_bundle_refs": ["string"],
                        "open_description": "string",
                        "primary_role": {"label": "open text", "confidence": 0.0},
                        "secondary_roles": [{"label": "open text", "confidence": 0.0}],
                        "source_evidence_refs": ["string"],
                        "source_asset_refs": ["string"],
                        "layout_dependency": {"required": False, "reason": "string"},
                        "states": {"student": {"description": "string"}, "teacher": {"description": "string"}},
                        "structure": {"representation_status": "complete|partial|asset_only", "rows": [], "columns": [], "cells": []},
                        "child_objects": [],
                        "relations": [],
                        "projection_facts": {
                            "qbank_as_is_supported": False,
                            "qbank_derivable": False,
                            "knowledge_structure_supported": False,
                            "faithful_material_supported": True,
                            "qbank_reason": "string",
                            "knowledge_reason": "string",
                            "faithful_reason": "string",
                        },
                        "unresolved_required_evidence": False,
                        "uncertainties": [],
                    }
                ],
                "relations": [],
                "uncertainties": [],
            },
        }
        verifier = model_call(
            api_key=api_key,
            model=model,
            timeout=int(args.timeout),
            system_prompt=knowledge_verifier_prompt(),
            payload=verifier_payload,
            image_paths=images,
            call_id=f"{doc_id}:verifier",
            max_retries=int(args.max_retries),
        )
        model_calls.append(verifier)
        source_complete = all(path.exists() for path in images) and bool(images)
        documents.append(
            build_projection(
                doc_id=doc_id,
                source_bundles=bundles,
                composer_call=composer,
                verifier_call=verifier,
                source_complete=source_complete,
                image_paths=images,
            )
        )
        write_json(
            out_dir / f"partial_{doc_id}.json",
            {
                "schema": f"{SCHEMA_VERSION}.partial_document",
                "doc_id": doc_id,
                "model_calls": [composer, verifier],
                "document": documents[-1],
            },
        )

    old_gold = canonical_gold_for_old_grammar(human_review)
    old_doc = next((doc for doc in documents if doc["doc_id"] == "grammar_clauses_old5"), None)
    old_comparison = compare_old_grammar(old_doc, old_gold) if old_doc else []
    projection = {
        "schema": f"{SCHEMA_VERSION}.knowledge_structure_projection",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "runtime_import_enabled": False,
        "non_destructive_sidecar": True,
        "policy": {
            "question_packet_is_projection_not_source_truth": True,
            "projector_uses_verified_facts_only": True,
            "no_family_specific_builder": True,
            "no_runtime_ddl_change": True,
        },
        "documents": documents,
        "old_grammar_canonical_gold": old_gold,
        "old_grammar_comparison": old_comparison,
        "model_calls": model_calls,
    }
    projection["summary"] = {
        "documents": len(documents),
        "model_calls": len(model_calls),
        "schema_valid_calls": sum(1 for call in model_calls if call.get("schema_valid")),
        "old_grammar_items": len(old_comparison),
        "old_grammar_directionally_aligned": sum(1 for row in old_comparison if row["directionally_aligned"]),
        "knowledge_objects_total": sum(
            1
            for doc in documents
            for obj in doc.get("semantic_objects", [])
            if "knowledge" in str(obj.get("primary_role", {}).get("label", "")).lower()
        ),
    }
    write_json(out_dir / "knowledge_structure_projection.json", projection)
    write_json(out_dir / "model_calls.json", {"schema": f"{SCHEMA_VERSION}.model_calls", "calls": model_calls})
    write_json(out_dir / "old_grammar_multitarget_gold.json", {"schema": f"{SCHEMA_VERSION}.old_grammar_gold", "rows": old_gold})
    write_json(out_dir / "old_grammar_model_vs_human.json", {"schema": f"{SCHEMA_VERSION}.old_grammar_comparison", "rows": old_comparison})
    write_schema(out_dir)
    write_text(out_dir / "knowledge_structure_audit_report.md", audit_report(projection, old_comparison))
    review = render_review_html(out_dir, projection, old_comparison)
    run_summary = {
        "schema": f"{SCHEMA_VERSION}.run_summary",
        "generated_at": projection["generated_at"],
        "out_dir": rel_workspace(out_dir),
        "knowledge_structure_projection": rel_workspace(out_dir / "knowledge_structure_projection.json"),
        "review_html": rel_workspace(review),
        "model_calls": len(model_calls),
        "schema_valid_calls": projection["summary"]["schema_valid_calls"],
        "old_grammar_directionally_aligned": projection["summary"]["old_grammar_directionally_aligned"],
        "runtime_import_enabled": False,
    }
    write_json(out_dir / "run_summary.json", run_summary)
    print(json.dumps(run_summary, ensure_ascii=False, indent=2))
    return run_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a minimal knowledge-structure projection sidecar for English graph-first ingestion.")
    parser.add_argument("--grammar-probe-dir", default="outputs/english_text_first_pipeline_v02_spec_20260715/new_material_probe_20260716/grammar_tense_voice_p001_p004_visual_unit_probe")
    parser.add_argument("--sidecar-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/sidecar_rescue_v01_20260715")
    parser.add_argument("--human-review", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json")
    parser.add_argument("--out", default="outputs/english_text_first_pipeline_v02_spec_20260715/knowledge_structure_projection_v01_20260716")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--doc-filter", choices=["both", "new", "old"], default="both")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
