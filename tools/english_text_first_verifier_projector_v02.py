from __future__ import annotations

import argparse
import base64
import concurrent.futures
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
ALLOWED_FACT_PREDICATES = {"depends_on", "shares_context", "uses_asset", "answers", "continues_on", "other"}


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


def parse_json(text: str) -> tuple[dict[str, Any] | None, str]:
    cleaned = text.strip()
    try:
        return json.loads(cleaned), ""
    except json.JSONDecodeError as exc:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1]), ""
            except json.JSONDecodeError as nested:
                return None, str(nested)
        return None, str(exc)


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def source_unit_from_packet_id(doc_id: str, packet_id: str) -> str:
    prefix = f"{doc_id}_"
    return packet_id.split(prefix, 1)[-1] if packet_id.startswith(prefix) else packet_id


def object_id(doc_id: str, unit_id: str) -> str:
    return f"{doc_id}:{unit_id}"


def object_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {obj["id"]: obj for doc in graph["documents"] for obj in doc["semantic_objects"]}


def doc_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {doc["doc_id"]: doc for doc in graph["documents"]}


def claims_by_subject(graph_doc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for claim in graph_doc.get("semantic_claims", []):
        result.setdefault(str(claim.get("subject", "")), []).append(claim)
    return result


def claims_by_object(graph_doc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for claim in graph_doc.get("semantic_claims", []):
        result.setdefault(str(claim.get("object", "")), []).append(claim)
    return result


def page_image_for_ref(graph_doc: dict[str, Any], page_id: str) -> Path | None:
    for page in graph_doc["source_evidence"]["pages"]:
        if page.get("page_id") == page_id and page.get("image_path"):
            path = workspace_path(str(page["image_path"]))
            return path if path.exists() else None
    return None


def compact_object(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": obj["id"],
        "source_unit_id": obj.get("source_unit_id", ""),
        "kind_open_text": obj.get("kind", {}).get("open_text", ""),
        "observations": obj.get("observations", []),
        "title": obj.get("title", ""),
        "source_text": obj.get("source_text", ""),
        "line_refs": obj.get("line_refs", []),
        "page_ids": obj.get("page_ids", []),
        "semantic_status": obj.get("semantic_status"),
        "evidence_status": obj.get("evidence_status"),
    }


def target_rows(human_review: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in human_review.get("packets", []):
        doc_id = str(item.get("doc_id", ""))
        packet_id = str(item.get("packet_id", ""))
        rows.append(
            {
                "doc_id": doc_id,
                "packet_id": packet_id,
                "source_unit_id": source_unit_from_packet_id(doc_id, packet_id),
                "human_verdict": item.get("human_verdict", ""),
                "human_note": item.get("note", ""),
            }
        )
    return rows


def context_candidates(graph_doc: dict[str, Any], target_id: str, objects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for claim in claims_by_subject(graph_doc).get(target_id, []):
        if claim.get("predicate") not in {"depends_on", "shares_context"}:
            continue
        obj = objects.get(str(claim.get("object", "")))
        if not obj:
            continue
        candidates.append(
            {
                "relation_predicate": claim.get("predicate"),
                "object": compact_object(obj),
                "claim_reason": claim.get("reason", ""),
                "claim_evidence_refs": claim.get("evidence_refs", []),
            }
        )
    return candidates


def asset_candidates(graph_doc: dict[str, Any], target_id: str, objects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    subject_claims = claims_by_subject(graph_doc)
    assets: list[dict[str, Any]] = []
    for claim in subject_claims.get(target_id, []):
        if claim.get("predicate") != "uses_asset":
            continue
        visual_obj = objects.get(str(claim.get("object", "")))
        if not visual_obj:
            continue
        derivative_assets: list[dict[str, Any]] = []
        for visual_claim in subject_claims.get(visual_obj["id"], []):
            if visual_claim.get("predicate") != "uses_asset":
                continue
            asset_obj = objects.get(str(visual_claim.get("object", "")))
            if asset_obj:
                derivative_assets.append(asset_obj)
        assets.append(
            {
                "visual_object": compact_object(visual_obj),
                "claim": claim,
                "derivative_assets": [
                    {
                        "id": item["id"],
                        "title": item.get("title", ""),
                        "raw_asset_ref": item.get("raw_asset_ref", {}),
                        "page_ids": item.get("page_ids", []),
                        "line_refs": item.get("line_refs", []),
                    }
                    for item in derivative_assets
                ],
            }
        )
    return assets


def call_json_model(
    *,
    api_key: str,
    model: str,
    timeout: int,
    system_prompt: str,
    user_payload: dict[str, Any],
    image_paths: list[Path] | None = None,
) -> dict[str, Any]:
    user_content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(user_payload, ensure_ascii=False, indent=2)}]
    for image_path in image_paths or []:
        if image_path.exists():
            user_content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
    content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = parse_json(content)
    return {
        "called": True,
        "parsed": parsed is not None,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
        "image_count": len(image_paths or []),
        "result": parsed or {},
        "raw_content": "" if parsed else content,
        "usage": raw.get("usage", {}),
    }


def context_system_prompt() -> str:
    return """You are a Context Independence Verifier.

Verify one observed activity only.
Do not decide READY/BLOCKED/UNSUPPORTED.
Do not classify by family.
Do not invent missing text.
Do not use outside subject-matter knowledge to make the candidate look standalone.

Test:
1. Candidate-only: using only the candidate source evidence, can the activity preserve its task, target concept, pedagogical role, and answer basis as a source-material object?
2. With proposed context objects: do any of those objects supply necessary document context, parent concept, shared passage, instruction frame, or answer basis?

Return JSON only. Use the provided schema."""


def verify_context(row: dict[str, Any], graph: dict[str, Any], objects: dict[str, dict[str, Any]], *, api_key: str, model: str, timeout: int) -> dict[str, Any]:
    graph_doc = doc_by_id(graph)[row["doc_id"]]
    target_id = object_id(row["doc_id"], row["source_unit_id"])
    target = objects[target_id]
    candidates = context_candidates(graph_doc, target_id, objects)
    payload = {
        "task": "Context independence verification for one observed unit.",
        "output_schema": {
            "packet_id": "string",
            "candidate_independent_complete": "boolean",
            "required_context": "boolean",
            "required_context_object_ids": ["string"],
            "required_relation_predicates": ["depends_on or shares_context"],
            "evidence_refs": ["p001:b2"],
            "reason": "string",
            "confidence": 0.0,
        },
        "packet_id": row["packet_id"],
        "candidate": compact_object(target),
        "proposed_context_objects": candidates,
        "rules": [
            "Judge source-material independence, not whether a knowledgeable student could answer from memory.",
            "If candidate-only preserves task, target concept, pedagogical role, and answer basis, required_context=false.",
            "If context is helpful but not necessary, required_context=false.",
            "If the activity loses task target, parent concept, document role, reference, answer basis, or required instructional frame without a context object, required_context=true.",
            "A shared reading passage can be required context; report relation predicate shares_context.",
            "A parent instructional/knowledge object can be required context; report relation predicate depends_on.",
            "If a candidate is answerable only by outside knowledge but its document context explains what learning object it belongs to, required_context=true.",
            "Do not output projection status.",
        ],
    }
    result = call_json_model(
        api_key=api_key,
        model=model,
        timeout=timeout,
        system_prompt=context_system_prompt(),
        user_payload=payload,
    )
    result.update(
        {
            "verifier": "context_independence",
            "packet_id": row["packet_id"],
            "doc_id": row["doc_id"],
            "proposed_context_candidates": candidates,
        }
    )
    return result


def asset_system_prompt() -> str:
    return """You are an Asset Coverage Verifier.

Verify one target activity and its visual/crop assets.
Do not decide READY/BLOCKED/UNSUPPORTED.
Do not assume an asset is complete because an asset_ref exists.
Compare the original page evidence with the derivative crop evidence.
Return JSON only."""


def verify_asset(row: dict[str, Any], graph: dict[str, Any], objects: dict[str, dict[str, Any]], *, api_key: str, model: str, timeout: int) -> dict[str, Any]:
    graph_doc = doc_by_id(graph)[row["doc_id"]]
    target_id = object_id(row["doc_id"], row["source_unit_id"])
    target = objects[target_id]
    assets = asset_candidates(graph_doc, target_id, objects)
    image_paths: list[Path] = []
    for page_id in target.get("page_ids", []):
        path = page_image_for_ref(graph_doc, str(page_id))
        if path and path not in image_paths:
            image_paths.append(path)
    for asset_group in assets:
        for derivative in asset_group.get("derivative_assets", []):
            raw = derivative.get("raw_asset_ref", {})
            asset_path_value = str(raw.get("asset_path", "") or "")
            if asset_path_value:
                path = workspace_path(Path("outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/base") / asset_path_value)
                if path.exists() and path not in image_paths:
                    image_paths.append(path)
            source_page_id = str(raw.get("source_page_id", "") or "")
            page_path = page_image_for_ref(graph_doc, source_page_id)
            if page_path and page_path not in image_paths:
                image_paths.append(page_path)
    payload = {
        "task": "Asset coverage verification for one observed activity.",
        "output_schema": {
            "packet_id": "string",
            "has_required_visual_requirements": "boolean",
            "requirements": [
                {
                    "description": "string",
                    "required": "boolean",
                    "source_regions": ["p001:b2"],
                    "coverage_status": "complete | partial | missing | not_required",
                    "covered_by_asset_ids": ["string"],
                    "reason": "string",
                    "confidence": 0.0,
                }
            ],
            "overall_required_asset_coverage": "complete | partial | missing | not_required",
            "reason": "string",
        },
        "packet_id": row["packet_id"],
        "candidate": compact_object(target),
        "asset_candidates": assets,
        "rules": [
            "If no visual region is necessary to faithfully preserve this activity, use not_required.",
            "If visual regions are required, compare source page requirements against derivative crop coverage.",
            "Derivative crops marked ROUGH_DERIVED_VIEW are not automatically complete.",
            "A full source page fallback preserves evidence but is not a precise crop.",
            "Do not output projection status.",
        ],
    }
    result = call_json_model(
        api_key=api_key,
        model=model,
        timeout=timeout,
        system_prompt=asset_system_prompt(),
        user_payload=payload,
        image_paths=image_paths,
    )
    result.update(
        {
            "verifier": "asset_coverage",
            "packet_id": row["packet_id"],
            "doc_id": row["doc_id"],
            "asset_candidates": assets,
        }
    )
    return result


def solution_fact(row: dict[str, Any], graph: dict[str, Any], objects: dict[str, dict[str, Any]]) -> dict[str, Any]:
    graph_doc = doc_by_id(graph)[row["doc_id"]]
    target_id = object_id(row["doc_id"], row["source_unit_id"])
    incoming = claims_by_object(graph_doc).get(target_id, [])
    answer_claims = [claim for claim in incoming if claim.get("predicate") == "answers"]
    answer_objects = [objects.get(str(claim.get("subject", ""))) for claim in answer_claims]
    answer_objects = [obj for obj in answer_objects if obj]
    return {
        "verifier": "solution_requirement",
        "packet_id": row["packet_id"],
        "doc_id": row["doc_id"],
        "called": False,
        "parsed": True,
        "result": {
            "solution_required": True,
            "verified_solution": bool(answer_objects),
            "answer_object_ids": [obj["id"] for obj in answer_objects],
            "evidence_refs": [ref for obj in answer_objects for ref in obj.get("line_refs", [])],
            "reason": "Current Runtime QuestionPacket target requires a verified solution object.",
        },
    }


def normalize_context_fact(call: dict[str, Any]) -> dict[str, Any]:
    result = call.get("result", {}) if call.get("parsed") else {}
    required = bool(result.get("required_context"))
    predicates = [pred for pred in result.get("required_relation_predicates", []) or [] if pred in {"depends_on", "shares_context"}]
    proposed_dependency_ids = [
        str(item.get("object", {}).get("id", ""))
        for item in call.get("proposed_context_candidates", []) or []
        if item.get("relation_predicate") == "depends_on"
    ]
    dependency_disagreement = bool(proposed_dependency_ids) and not (required and "depends_on" in predicates)
    return {
        "packet_id": call.get("packet_id"),
        "verifier": "context_independence",
        "protocol_valid": bool(call.get("parsed")),
        "candidate_independent_complete": bool(result.get("candidate_independent_complete")) if result else None,
        "required_context": required,
        "required_context_object_ids": result.get("required_context_object_ids", []) or [],
        "required_relation_predicates": predicates,
        "blocking_dependency_required": required and "depends_on" in predicates,
        "shared_context_required": required and "shares_context" in predicates,
        "composer_dependency_object_ids": proposed_dependency_ids,
        "dependency_disagreement_requires_review": dependency_disagreement,
        "evidence_refs": result.get("evidence_refs", []) or [],
        "reason": result.get("reason", "") or call.get("parse_error", ""),
        "confidence": result.get("confidence"),
    }


def normalize_asset_fact(call: dict[str, Any]) -> dict[str, Any]:
    result = call.get("result", {}) if call.get("parsed") else {}
    requirements = result.get("requirements", []) or []
    required_requirements = [req for req in requirements if req.get("required")]
    incomplete = [
        req
        for req in required_requirements
        if str(req.get("coverage_status", "")).lower() not in {"complete", "not_required"}
    ]
    has_required = bool(result.get("has_required_visual_requirements")) or bool(required_requirements)
    overall = str(result.get("overall_required_asset_coverage", "not_required") or "not_required").lower()
    rough_asset_ids: set[str] = set()
    for group in call.get("asset_candidates", []) or []:
        for asset in group.get("derivative_assets", []) or []:
            raw = asset.get("raw_asset_ref", {}) or {}
            if raw.get("crop_precision") == "ROUGH_DERIVED_VIEW" or raw.get("needs_precise_bbox"):
                rough_asset_ids.add(str(asset.get("id", "")))
    covered_required_asset_ids = {
        str(asset_id)
        for req in required_requirements
        for asset_id in (req.get("covered_by_asset_ids", []) or [])
    }
    rough_derivative_used_for_required_coverage = bool(rough_asset_ids & covered_required_asset_ids)
    return {
        "packet_id": call.get("packet_id"),
        "verifier": "asset_coverage",
        "protocol_valid": bool(call.get("parsed")),
        "has_required_visual_requirements": has_required,
        "requirements": requirements,
        "overall_required_asset_coverage": overall,
        "required_asset_complete": (not has_required)
        or (overall == "complete" and not incomplete and not rough_derivative_used_for_required_coverage),
        "rough_derivative_used_for_required_coverage": rough_derivative_used_for_required_coverage,
        "incomplete_required_requirements": incomplete,
        "reason": result.get("reason", "") or call.get("parse_error", ""),
    }


def normalize_solution_fact(call: dict[str, Any]) -> dict[str, Any]:
    result = call["result"]
    return {
        "packet_id": call["packet_id"],
        "verifier": "solution_requirement",
        "protocol_valid": True,
        "solution_required": result["solution_required"],
        "verified_solution": result["verified_solution"],
        "answer_object_ids": result["answer_object_ids"],
        "evidence_refs": result["evidence_refs"],
        "reason": result["reason"],
    }


def project(row: dict[str, Any], graph: dict[str, Any], objects: dict[str, dict[str, Any]], facts_by_packet: dict[str, dict[str, Any]]) -> dict[str, Any]:
    target = objects[object_id(row["doc_id"], row["source_unit_id"])]
    context = facts_by_packet[row["packet_id"]]["context"]
    asset = facts_by_packet[row["packet_id"]]["asset"]
    solution = facts_by_packet[row["packet_id"]]["solution"]
    reasons: list[str] = []
    status = "READY"
    if target.get("semantic_status") == "INCOMPLETE_SOURCE":
        status = "BLOCKED"
        reasons.append("source_incomplete_or_unresolved_continuation")
    if solution["solution_required"] and not solution["verified_solution"]:
        status = "BLOCKED"
        reasons.append("required_solution_not_verified")
    if status != "BLOCKED" and (context["blocking_dependency_required"] or context.get("dependency_disagreement_requires_review")):
        status = "NEEDS_REVIEW"
        if context["blocking_dependency_required"]:
            reasons.append("verified_required_parent_or_instructional_context_must_be_preserved")
        else:
            reasons.append("composer_dependency_not_safely_refuted_by_context_verifier")
    if status not in {"BLOCKED", "NEEDS_REVIEW"} and asset["has_required_visual_requirements"] and not asset["required_asset_complete"]:
        status = "READY_WITH_LOSS"
        reasons.append("required_visual_requirements_not_fully_covered_by_verified_assets")
    return {
        "packet_id": row["packet_id"],
        "doc_id": row["doc_id"],
        "source_unit_id": row["source_unit_id"],
        "human_verdict": row["human_verdict"],
        "semantic_status": target.get("semantic_status"),
        "evidence_status": target.get("evidence_status"),
        "projection_status": status,
        "projection_reasons": reasons,
        "verified_facts": facts_by_packet[row["packet_id"]],
        "projector_policy": "deterministic_verified_facts_only_no_model_status",
    }


def matches_human(row: dict[str, Any]) -> bool:
    human = str(row["human_verdict"])
    status = row["projection_status"]
    if human.startswith("ACCEPT_WITH_MINOR_FORMAT_ISSUE"):
        return status in {"READY", "READY_WITH_LOSS"}
    if human == "ACCEPT":
        return status == "READY"
    if human.startswith("ACCEPT_WITH_PARENT_LINK"):
        return status in {"READY", "NEEDS_REVIEW"}
    if human == "HOLD_PARENT_RELATION":
        return status == "NEEDS_REVIEW"
    if human == "HOLD_BAD_ASSET_INCOMPLETE_WRITING_SURFACE":
        return status in {"READY_WITH_LOSS", "NEEDS_REVIEW", "BLOCKED"}
    if human == "HOLD_MISSING_SOLUTION":
        return status == "BLOCKED"
    if human == "HOLD_INCOMPLETE_TAIL":
        return status == "BLOCKED"
    return False


def render_html(out_dir: Path, summary: dict[str, Any], context_calls: list[dict[str, Any]], asset_calls: list[dict[str, Any]], projections: list[dict[str, Any]]) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>English Verifier Projector v02 Review</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.45}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ddd;padding:8px;vertical-align:top}th{background:#f5f5f5}.ok{background:#eef9f0}.bad{background:#fff0f0}.mono{font-family:Consolas,monospace;white-space:pre-wrap}.call{border:1px solid #ddd;background:#fafafa;padding:10px;margin:8px 0}</style>",
        "<h1>English Verifier Projector v02 Review</h1>",
        "<p>Composer output is reused. Model calls are only candidate-level verifier calls. Projection status is computed by code from verified facts.</p>",
        f"<h2>Summary</h2><pre class='mono'>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>",
        "<h2>17-Item Comparison</h2>",
        "<table><thead><tr><th>packet</th><th>human</th><th>projected</th><th>verified facts</th><th>match</th></tr></thead><tbody>",
    ]
    for row in projections:
        css = "ok" if row["matches_human_direction"] else "bad"
        projected = {
            "projection_status": row["projection_status"],
            "semantic_status": row["semantic_status"],
            "evidence_status": row["evidence_status"],
            "projection_reasons": row["projection_reasons"],
        }
        parts.append(f"<tr class='{css}'>")
        parts.append(f"<td>{html.escape(row['packet_id'])}<br><small>{html.escape(row['doc_id'])}</small></td>")
        parts.append(f"<td><b>{html.escape(str(row['human_verdict']))}</b></td>")
        parts.append(f"<td><pre class='mono'>{html.escape(json.dumps(projected, ensure_ascii=False, indent=2))}</pre></td>")
        parts.append(f"<td><pre class='mono'>{html.escape(json.dumps(row['verified_facts'], ensure_ascii=False, indent=2))}</pre></td>")
        parts.append(f"<td>{row['matches_human_direction']}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    parts.append("<h2>Verifier Calls</h2>")
    parts.append(f"<p>context calls: {len(context_calls)}; asset calls: {len(asset_calls)}</p>")
    for call in context_calls + asset_calls:
        parts.append(
            f"<div class='call'><b>{html.escape(str(call.get('verifier')))} {html.escape(str(call.get('packet_id')))}</b> "
            f"parsed={call.get('parsed')} latency={call.get('latency_seconds')}s images={call.get('image_count', 0)}"
            f"<pre class='mono'>{html.escape(json.dumps(call.get('result', {}), ensure_ascii=False, indent=2))}</pre></div>"
        )
    write_text(out_dir / "verifier_projector_review.html", "\n".join(parts))


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = str(args.api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing_ark_api_key")
    sidecar_root = workspace_path(args.sidecar_root)
    out_dir = workspace_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = read_json(sidecar_root / "semantic_graph.json")
    human_review = read_json(workspace_path(args.human_review))
    objects = object_by_id(graph)
    rows = target_rows(human_review)

    context_calls: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as executor:
        futures = [
            executor.submit(verify_context, row, graph, objects, api_key=api_key, model=args.model, timeout=int(args.timeout))
            for row in rows
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                context_calls.append(future.result())
            except Exception as exc:  # noqa: BLE001 - persisted as verifier evidence
                context_calls.append({"verifier": "context_independence", "called": True, "parsed": False, "error": f"{type(exc).__name__}: {exc}", "result": {}})

    rows_with_assets = [
        row
        for row in rows
        if asset_candidates(doc_by_id(graph)[row["doc_id"]], object_id(row["doc_id"], row["source_unit_id"]), objects)
    ]
    asset_calls: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as executor:
        futures = [
            executor.submit(verify_asset, row, graph, objects, api_key=api_key, model=args.model, timeout=int(args.timeout))
            for row in rows_with_assets
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                asset_calls.append(future.result())
            except Exception as exc:  # noqa: BLE001
                asset_calls.append({"verifier": "asset_coverage", "called": True, "parsed": False, "error": f"{type(exc).__name__}: {exc}", "result": {}})

    context_by_packet = {str(call.get("packet_id")): normalize_context_fact(call) for call in context_calls}
    asset_by_packet = {str(call.get("packet_id")): normalize_asset_fact(call) for call in asset_calls}
    facts_by_packet: dict[str, dict[str, Any]] = {}
    for row in rows:
        solution = normalize_solution_fact(solution_fact(row, graph, objects))
        facts_by_packet[row["packet_id"]] = {
            "context": context_by_packet.get(
                row["packet_id"],
                {
                    "packet_id": row["packet_id"],
                    "verifier": "context_independence",
                    "protocol_valid": False,
                    "required_context": False,
                    "blocking_dependency_required": False,
                    "shared_context_required": False,
                    "reason": "context verifier missing",
                },
            ),
            "asset": asset_by_packet.get(
                row["packet_id"],
                {
                    "packet_id": row["packet_id"],
                    "verifier": "asset_coverage",
                    "protocol_valid": True,
                    "has_required_visual_requirements": False,
                    "required_asset_complete": True,
                    "overall_required_asset_coverage": "not_required",
                    "requirements": [],
                    "reason": "no asset candidates attached to this target",
                },
            ),
            "solution": solution,
        }
    projections = [project(row, graph, objects, facts_by_packet) for row in rows]
    for item in projections:
        item["matches_human_direction"] = matches_human(item)
    summary = {
        "schema": "english_text_first_verifier_projector_v02.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "composer_model_calls": 0,
        "context_verifier_calls": len(context_calls),
        "asset_verifier_calls": len(asset_calls),
        "solution_verifier_model_calls": 0,
        "parsed_context_calls": sum(1 for call in context_calls if call.get("parsed")),
        "parsed_asset_calls": sum(1 for call in asset_calls if call.get("parsed")),
        "comparison_counts": {
            "items": len(projections),
            "matched": sum(1 for item in projections if item["matches_human_direction"]),
            "mismatched": sum(1 for item in projections if not item["matches_human_direction"]),
        },
        "projector_policy": "deterministic_from_verified_facts_no_model_projection_status",
    }
    write_json(out_dir / "context_verifier_calls.json", {"schema": "english_text_first_verifier_projector_v02.context_calls", "calls": context_calls})
    write_json(out_dir / "asset_verifier_calls.json", {"schema": "english_text_first_verifier_projector_v02.asset_calls", "calls": asset_calls})
    write_json(out_dir / "verified_facts.json", {"schema": "english_text_first_verifier_projector_v02.verified_facts", "facts_by_packet": facts_by_packet})
    write_json(out_dir / "projector_results.json", {"schema": "english_text_first_verifier_projector_v02.projector_results", "rows": projections})
    write_json(out_dir / "run_summary.json", summary)
    render_html(out_dir, summary, context_calls, asset_calls, projections)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate-level verifiers and deterministic projector over English sidecar graph.")
    parser.add_argument("--sidecar-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/sidecar_rescue_v01_20260715")
    parser.add_argument("--human-review", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json")
    parser.add_argument("--out", default="outputs/english_text_first_pipeline_v02_spec_20260715/verifier_projector_v02_17p_20260715")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
