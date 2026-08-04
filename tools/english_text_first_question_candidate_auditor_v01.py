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
from jsonschema import Draft202012Validator

from english_text_first_normalizer.common import rel_workspace, render_template, workspace_path, write_json, write_text


AUDITOR_VERSION = "english_question_candidate_auditor_v0.1_source_page_constrained_20260727"
PROMPT_VERSION = "english_question_candidate_auditor_prompt_v0.1_20260727"
SCHEMA_PATH = "schemas/english_question_candidate_audit.schema.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = str(text or "").strip()
    try:
        return json.loads(stripped), ""
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), ""
            except json.JSONDecodeError as nested:
                return None, str(nested)
        return None, str(exc)


def image_to_data_url(path: Path) -> str:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def family_from_doc_id(doc_id: str) -> str:
    text = str(doc_id or "")
    if text.startswith("reading_"):
        return "reading"
    if text.startswith("grammar_"):
        return "grammar"
    if text.startswith("writing_"):
        return "writing"
    return ""


def source_pages(packet: dict[str, Any]) -> list[int]:
    pages = (packet.get("evidence") or {}).get("source_pages") or []
    result: list[int] = []
    for page in pages:
        try:
            value = int(page)
        except (TypeError, ValueError):
            continue
        if value not in result:
            result.append(value)
    return result[:3]


def page_images_from_manifest(manifest: dict[str, Any], packet: dict[str, Any]) -> list[Path]:
    family = family_from_doc_id(str(packet.get("doc_id") or ""))
    page_root = ((manifest.get("source_page_images") or {}).get(family) or {}).get("path")
    if not page_root:
        return []
    root = workspace_path(page_root)
    images: list[Path] = []
    for page in source_pages(packet):
        path = root / f"page_{page:03d}.png"
        if path.exists():
            images.append(path)
    return images[:3]


def compact_packet(packet: dict[str, Any]) -> dict[str, Any]:
    content = {}
    for key, value in (packet.get("content") or {}).items():
        if not isinstance(value, dict):
            continue
        text = str(value.get("text") or "")
        refs = value.get("refs") or []
        missing_refs = value.get("missing_refs") or []
        if text.strip() or refs or missing_refs:
            content[key] = {"text": text[:3200], "refs": refs, "missing_refs": missing_refs}
    return {
        "packet_id": packet.get("packet_id"),
        "doc_id": packet.get("doc_id"),
        "source_group_id": packet.get("source_group_id"),
        "projection_status": packet.get("projection_status"),
        "packet_family": packet.get("packet_family"),
        "project_directly_to_question": packet.get("project_directly_to_question"),
        "content": content,
        "evidence": packet.get("evidence") or {},
        "relations": packet.get("relations") or {},
        "asset_refs": packet.get("asset_refs") or {},
        "source_surfaces": packet.get("source_surfaces") or {},
        "missing_fields": packet.get("missing_fields") or [],
        "builder_warnings": packet.get("builder_warnings") or [],
        "source_text_health": packet.get("source_text_health") or {},
    }


def call_model(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path],
    api_key: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    }
    started = time.time()
    response = requests.post(
        config["api_url"],
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
    raw = response.json()
    raw_content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(raw_content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def fallback_audit(packet: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema": "english_question_candidate_audit_v0.1",
        "doc_id": str(packet.get("doc_id") or ""),
        "packet_id": str(packet.get("packet_id") or ""),
        "source_group_id": str(packet.get("source_group_id") or ""),
        "auditor_version": AUDITOR_VERSION,
        "audit_level": "WARN",
        "recommended_route": "TO_5B_WITH_CONSTRAINTS",
        "risk_flags": [
            {
                "code": "source_page_unclear",
                "severity": "warn",
                "target_fields": [],
                "source_refs": list((packet.get("evidence") or {}).get("source_refs") or []),
                "reason": reason,
            }
        ],
        "downstream_constraints": [
            {
                "for_node": "node5b",
                "instruction": "Preserve source-backed fields conservatively because Node5a audit could not complete.",
                "source_refs": list((packet.get("evidence") or {}).get("source_refs") or []),
                "must_not": ["invent missing text", "delete source-visible content"],
            }
        ],
        "surface_requirements": [],
        "evidence_notes": [],
        "blocking_reasons": [],
    }


def coerce_list_objects(audit: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(audit or {})
    source_refs = [str(ref) for ref in (packet.get("evidence") or {}).get("source_refs") or [] if str(ref).strip()]
    pages = source_pages(packet)

    risk_flags = []
    for item in repaired.get("risk_flags") or []:
        if isinstance(item, dict):
            risk_flags.append(item)
        else:
            risk_flags.append(
                {
                    "code": "other",
                    "severity": "warn",
                    "target_fields": [],
                    "source_refs": source_refs,
                    "reason": str(item),
                }
            )
    repaired["risk_flags"] = risk_flags

    constraints = []
    for item in repaired.get("downstream_constraints") or []:
        if isinstance(item, dict):
            constraints.append(item)
        else:
            constraints.append(
                {
                    "for_node": "node5b",
                    "instruction": str(item),
                    "source_refs": source_refs,
                    "must_not": ["invent missing text", "delete source-visible content"],
                }
            )
    repaired["downstream_constraints"] = constraints

    surfaces = []
    for item in repaired.get("surface_requirements") or []:
        if isinstance(item, dict):
            surfaces.append(item)
        else:
            surfaces.append(
                {
                    "surface_kind": "source_page",
                    "required": True,
                    "source_refs": source_refs,
                    "page_refs": pages,
                    "reason": str(item),
                }
            )
    repaired["surface_requirements"] = surfaces

    evidence_notes = []
    for item in repaired.get("evidence_notes") or []:
        if isinstance(item, dict):
            evidence_notes.append(item)
        else:
            evidence_notes.append(
                {
                    "source_refs": source_refs,
                    "page_refs": pages,
                    "observation": str(item),
                }
            )
    repaired["evidence_notes"] = evidence_notes

    blocking_reasons = []
    for item in repaired.get("blocking_reasons") or []:
        if isinstance(item, dict):
            blocking_reasons.append(item)
        else:
            blocking_reasons.append(
                {
                    "code": "other",
                    "reason": str(item),
                    "source_refs": source_refs,
                }
            )
    repaired["blocking_reasons"] = blocking_reasons
    return repaired


def validate_audit(audit: dict[str, Any], packet: dict[str, Any], validator: Draft202012Validator) -> dict[str, Any]:
    errors = [{"path": ".".join(map(str, err.path)), "message": err.message} for err in validator.iter_errors(audit)]
    for key, expected in [
        ("doc_id", packet.get("doc_id")),
        ("packet_id", packet.get("packet_id")),
        ("source_group_id", packet.get("source_group_id")),
        ("auditor_version", AUDITOR_VERSION),
    ]:
        if audit.get(key) != expected:
            errors.append({"path": f"$.{key}", "message": "identifier mismatch"})
    if audit.get("audit_level") == "BLOCK" and not audit.get("blocking_reasons"):
        errors.append({"path": "$.blocking_reasons", "message": "BLOCK requires blocking_reasons"})
    hard_block_codes = {"invalid_reference", "empty_candidate", "high_confidence_group_collision"}
    for reason in audit.get("blocking_reasons") or []:
        if reason.get("code") not in hard_block_codes:
            errors.append({"path": "$.blocking_reasons", "message": "unsupported blocking reason"})
    return {"valid": not errors, "errors": errors}


def render_review(payload: dict[str, Any]) -> str:
    rows = []
    for item in payload.get("items", []):
        packet = item.get("packet") or {}
        audit = item.get("audit") or {}
        image_cells = []
        for path in item.get("page_images") or []:
            abs_path = workspace_path(path)
            if abs_path.exists():
                url = abs_path.resolve().as_uri()
                image_cells.append(f"<a href='{html.escape(url)}' target='_blank'><img src='{html.escape(url)}'></a>")
        rows.append(
            "<section class='card'>"
            f"<h2>{html.escape(str(packet.get('source_group_id')))} / {html.escape(str(audit.get('audit_level')))} / {html.escape(str(audit.get('recommended_route')))}</h2>"
            "<div class='grid'>"
            f"<div><h3>原页</h3>{''.join(image_cells) or '<p class=\"muted\">无原页图</p>'}</div>"
            f"<div><h3>候选字段</h3><pre>{html.escape(json.dumps(packet.get('content') or {}, ensure_ascii=False, indent=2))}</pre></div>"
            f"<div><h3>5a 风险体检</h3><pre>{html.escape(json.dumps(audit, ensure_ascii=False, indent=2))}</pre>"
            f"<h3>校验</h3><pre>{html.escape(json.dumps(item.get('validation') or {}, ensure_ascii=False, indent=2))}</pre></div>"
            "</div></section>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Node5a Candidate Auditor Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:22px;background:#f6f7f9;color:#111827;line-height:1.45}}
.card{{background:white;border:1px solid #d8dee8;border-radius:8px;margin:18px 0;padding:16px}}
.grid{{display:grid;grid-template-columns:minmax(340px,32%) minmax(360px,34%) 1fr;gap:16px;align-items:start}}
img{{width:320px;border:1px solid #cbd5e1;background:white;margin:0 8px 8px 0}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;max-height:560px;overflow:auto}}
.muted{{color:#64748b}}
@media(max-width:1100px){{.grid{{grid-template-columns:1fr}} img{{width:100%;max-width:420px}}}}
</style>
<h1>Node5a Candidate Auditor（候选题风险体检）</h1>
<p>只审核并生成给 Node5b/Node6b 的约束，不改题、不阻断普通 WARN。</p>
{''.join(rows)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    manifest = read_json(workspace_path(args.manifest))
    source = read_json(workspace_path(args.packet_candidates_json))
    schema = read_json(workspace_path(SCHEMA_PATH))
    validator = Draft202012Validator(schema)
    node = {
        "model": args.model or config.get("default_model_endpoint_id", "doubao-seed-2-0-lite-260428"),
        "temperature": 0,
    }
    api_key = os.environ.get(config.get("api_key_env", "ARK_API_KEY"), "")
    if not api_key and not args.no_model:
        raise RuntimeError(f"missing api key env: {config.get('api_key_env', 'ARK_API_KEY')}")

    packets = source.get("packet_candidates") or []
    selected = set(args.group_ids or [])
    if selected:
        packets = [packet for packet in packets if packet.get("source_group_id") in selected]
    if args.limit:
        packets = packets[: args.limit]

    system_prompt = workspace_path(args.system_prompt).read_text(encoding="utf-8")
    user_template = workspace_path(args.user_prompt).read_text(encoding="utf-8")
    out_dir = workspace_path(config["owned_output_root"]) / args.run_id
    items: list[dict[str, Any]] = []
    for packet in packets:
        packet_id = str(packet.get("packet_id") or packet.get("source_group_id") or "packet")
        packet_dir = out_dir / "packets" / packet_id
        page_images = page_images_from_manifest(manifest, packet)
        compact = compact_packet(packet)
        input_payload = {
            "packet_candidate": compact,
            "original_page_images": [
                {"path": rel_workspace(path), "page": int(path.stem.replace("page_", ""))}
                for path in page_images
            ],
            "auditor_policy": {
                "warn_not_gate": True,
                "block_only_for": ["invalid_reference", "empty_candidate", "high_confidence_group_collision"],
                "respect_source_page_design": True,
            },
        }
        existing = packet_dir / "candidate_audit.json"
        if args.resume and existing.exists():
            audit = read_json(existing)
            call = {}
        elif args.no_model:
            audit = fallback_audit(packet, "no_model mode")
            call = {}
        else:
            user_prompt = render_template(
                user_template,
                {
                    "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
                    "doc_id": packet.get("doc_id", ""),
                    "packet_id": packet.get("packet_id", ""),
                    "source_group_id": packet.get("source_group_id", ""),
                    "auditor_version": AUDITOR_VERSION,
                },
            )
            call = call_model(
                config=config,
                node=node,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_paths=page_images,
                api_key=api_key,
            )
            audit = call.get("parsed") or fallback_audit(packet, call.get("parse_error") or "parse failed")
            audit = coerce_list_objects(audit, packet)
            if audit.get("audit_level") == "BLOCK":
                allowed = {"invalid_reference", "empty_candidate", "high_confidence_group_collision"}
                if any(reason.get("code") not in allowed for reason in audit.get("blocking_reasons") or []):
                    audit["audit_level"] = "WARN"
                    audit["recommended_route"] = "TO_5B_WITH_CONSTRAINTS"
                    audit.setdefault("risk_flags", []).append(
                        {
                            "code": "other",
                            "severity": "warn",
                            "target_fields": [],
                            "source_refs": [],
                            "reason": "Program downgraded unsupported BLOCK to WARN to avoid content-type overblocking.",
                        }
                    )
        validation = validate_audit(audit, packet, validator)
        write_json(packet_dir / "input_payload.json", input_payload)
        if call:
            write_json(packet_dir / "model_call.json", call)
            write_text(packet_dir / "raw_content.txt", call.get("raw_content") or "")
        write_json(packet_dir / "candidate_audit.json", audit)
        write_json(packet_dir / "validation_report.json", validation)
        items.append(
            {
                "packet_id": packet.get("packet_id"),
                "source_group_id": packet.get("source_group_id"),
                "packet": compact,
                "audit": audit,
                "validation": validation,
                "page_images": [rel_workspace(path) for path in page_images],
                "artifact_path": rel_workspace(packet_dir / "candidate_audit.json"),
            }
        )

    payload = {
        "schema": "english_question_candidate_auditor_run_v0.1",
        "auditor_version": AUDITOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "source_packet_candidates_json": rel_workspace(workspace_path(args.packet_candidates_json)),
        "items": items,
        "summary": {
            "item_count": len(items),
            "valid_count": sum(1 for item in items if item["validation"].get("valid")),
            "audit_level_counts": {
                level: sum(1 for item in items if item["audit"].get("audit_level") == level)
                for level in ["OK", "WARN", "BLOCK"]
            },
            "route_counts": {},
        },
    }
    routes: dict[str, int] = {}
    for item in items:
        route = str(item["audit"].get("recommended_route") or "")
        routes[route] = routes.get(route, 0) + 1
    payload["summary"]["route_counts"] = routes
    write_json(out_dir / "candidate_audits.json", payload)
    write_json(
        out_dir / "run_summary.json",
        {
            "schema": "english_question_candidate_auditor.run_summary",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "out_dir": rel_workspace(out_dir),
            "candidate_audits_json": rel_workspace(out_dir / "candidate_audits.json"),
            "review_html": rel_workspace(out_dir / "review.html"),
            "summary": payload["summary"],
            "runtime_import_enabled": False,
            "database_write_enabled": False,
        },
    )
    write_text(out_dir / "review.html", render_review(payload))
    print(json.dumps(read_json(out_dir / "run_summary.json"), ensure_ascii=False, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--manifest", default="config/english_text_first_graph_first/active_manifest.json")
    parser.add_argument("--packet-candidates-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--system-prompt", default="prompts/english_question_candidate_auditor_system_v0.1.md")
    parser.add_argument("--user-prompt", default="prompts/english_question_candidate_auditor_user_v0.1.md")
    parser.add_argument("--model", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
