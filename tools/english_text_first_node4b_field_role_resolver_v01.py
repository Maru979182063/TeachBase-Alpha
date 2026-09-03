from __future__ import annotations

import argparse
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import (
    read_json,
    rel_workspace,
    render_template,
    workspace_path,
    write_json,
    write_text,
)
from english_text_first_normalizer.model_api import call_model


RESOLVER_VERSION = "english_node4b_field_role_resolver_v0.1_flexible_display_policy_20260727"
PROMPT_VERSION = "english_node4b_field_role_resolver_v0.1_20260727"

NON_EMPTY_FIELDS = [
    "instruction",
    "stem",
    "options",
    "passage",
    "answer",
    "analysis",
    "translation",
    "context",
    "examples",
    "visual",
    "writing_surface",
    "rubric",
    "other_evidence",
]

DISPLAY_POLICIES = {
    "show_in_question_body",
    "show_with_question_as_companion",
    "show_in_solution",
    "show_as_context_tag",
    "show_as_visual_asset",
    "preserve_source_only",
    "needs_human_review",
}


def compact_draft(draft: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    for name in NON_EMPTY_FIELDS:
        field = (draft.get("fields") or {}).get(name) or {}
        refs = field.get("refs") or []
        text = str(field.get("text") or "")
        if refs or text.strip():
            fields[name] = {
                "refs": refs,
                "text": text[:2400],
            }
    return {
        "draft_id": draft.get("draft_id"),
        "doc_id": draft.get("doc_id"),
        "source_group_id": draft.get("source_group_id"),
        "record_kind": draft.get("record_kind"),
        "semantic_role": draft.get("semantic_role"),
        "projection_target_hint": draft.get("projection_target_hint"),
        "project_directly_to_question": draft.get("project_directly_to_question"),
        "fields": fields,
        "relations": draft.get("relations") or {},
        "missing_fields": draft.get("missing_fields") or [],
        "warnings": draft.get("warnings") or [],
    }


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


def validate_resolution(item: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if item.get("schema") != "english_field_role_resolution_v0.1":
        errors.append({"path": "$.schema", "message": "invalid schema"})
    if item.get("source_group_id") != draft.get("source_group_id"):
        errors.append({"path": "$.source_group_id", "message": "source_group_id mismatch"})
    draft_fields = set((draft.get("fields") or {}).keys())
    for index, role in enumerate(item.get("field_roles") or []):
        field_name = role.get("field_name")
        if field_name not in draft_fields:
            errors.append({"path": f"$.field_roles[{index}].field_name", "message": "unknown field_name"})
        if role.get("display_policy") not in DISPLAY_POLICIES:
            errors.append({"path": f"$.field_roles[{index}].display_policy", "message": "invalid display_policy"})
        if not isinstance(role.get("source_refs"), list):
            errors.append({"path": f"$.field_roles[{index}].source_refs", "message": "source_refs must be array"})
    return {"valid": not errors, "errors": errors}


def call_model_with_retry(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    retries: int,
) -> dict[str, Any]:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            result = call_model(config, node, system_prompt, user_prompt, api_key)
            result["attempt"] = attempt + 1
            return result
        except Exception as exc:  # noqa: BLE001 - persisted for batch diagnosis.
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    return {
        "request_body": {
            "model": node["model"],
            "temperature": node.get("temperature", 0),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        "raw_response": None,
        "raw_content": "",
        "parsed": None,
        "parse_error": last_error,
        "latency_seconds": 0,
        "attempt": retries + 1,
        "transport_error": last_error,
    }


def render_review(payload: dict[str, Any]) -> str:
    cards = []
    for item in payload.get("items", []):
        draft = item["draft"]
        resolution = item.get("resolution") or {}
        field_blocks = []
        for name, field in (draft.get("fields") or {}).items():
            field_blocks.append(
                f"<section><h4>{html.escape(name)}</h4>"
                f"<div class='refs'>{html.escape(', '.join(field.get('refs') or []))}</div>"
                f"<pre>{html.escape(str(field.get('text') or ''))}</pre></section>"
            )
        roles = []
        for role in resolution.get("field_roles") or []:
            roles.append(
                "<tr>"
                f"<td>{html.escape(str(role.get('field_name','')))}</td>"
                f"<td>{html.escape(str(role.get('resolved_role','')))}</td>"
                f"<td>{html.escape(str(role.get('display_policy','')))}</td>"
                f"<td>{html.escape(str(role.get('should_builder_include','')))}</td>"
                f"<td>{html.escape(str(role.get('should_refiner_rewrite','')))}</td>"
                f"<td>{html.escape(str(role.get('should_render_preserve_layout','')))}</td>"
                f"<td>{html.escape(str(role.get('reason','')))}</td>"
                "</tr>"
            )
        cards.append(
            f"""
<article class="card">
  <h2>{html.escape(str(draft.get('doc_id')))} / {html.escape(str(draft.get('source_group_id')))}</h2>
  <p><b>usable_for_node4</b>锛圢ode4 鏄惁鍙敤锛? <code>{html.escape(str((resolution.get('overall_assessment') or {}).get('field_roles_usable_for_node4')))}</code>
  <b>needs_repair</b>锛堟槸鍚﹂渶瑕佸瓧娈靛洖淇級: <code>{html.escape(str((resolution.get('overall_assessment') or {}).get('needs_field_repair_before_builder')))}</code></p>
  <p>{html.escape(str((resolution.get('overall_assessment') or {}).get('reason','')))}</p>
  <div class="grid">
    <div><h3>Node4 draft fields锛圢ode4 灞曞紑鐨勫瓧娈碉級</h3>{''.join(field_blocks)}</div>
    <div><h3>Resolved roles锛堝瓧娈佃鑹插垽鏂級</h3>
      <table><thead><tr><th>field</th><th>role</th><th>display</th><th>include</th><th>rewrite</th><th>layout</th><th>reason</th></tr></thead><tbody>{''.join(roles)}</tbody></table>
      <h3>warnings锛堣鍛婏級</h3><pre>{html.escape(json.dumps(resolution.get('warnings') or [], ensure_ascii=False, indent=2))}</pre>
      <h3>validation锛堟牎楠岋級</h3><pre>{html.escape(json.dumps(item.get('validation') or {}, ensure_ascii=False, indent=2))}</pre>
    </div>
  </div>
</article>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Node3d Field Role Resolver Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f7f9;color:#111827;line-height:1.45}}
.card{{background:white;border:1px solid #d8dee8;border-radius:8px;margin:18px 0;padding:16px}}
.grid{{display:grid;grid-template-columns: minmax(360px, 42%) 1fr;gap:16px}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;max-height:420px;overflow:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #cbd5e1;padding:6px;vertical-align:top}}
th{{background:#f1f5f9}}
code{{background:#eef2ff;padding:2px 5px;border-radius:4px}}
.refs{{color:#64748b;font-size:12px}}
@media(max-width:1000px){{.grid{{grid-template-columns:1fr}}}}
</style>
<h1>Node4b FieldRoleResolver 鍊欓€夊鏍?/h1>
<p>瀹冧笉鏀瑰唴瀹癸紝鍙垽鏂瘡涓瓧娈靛湪褰撳墠 group 涓殑鍔熻兘鍜屽睍绀虹瓥鐣ワ紝鐢ㄦ潵鍙嶆帹 Node3 缁?Node4 鐨勬爣鍑嗚緭鍑恒€?/p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = {
        "model": config.get("default_model_endpoint_id", "doubao-seed-2-0-lite-260428"),
        "temperature": 0,
    }
    api_key = os.environ.get(config.get("api_key_env", "ARK_API_KEY"), "")
    if not api_key:
        raise RuntimeError(f"missing api key env: {config.get('api_key_env', 'ARK_API_KEY')}")

    draft_payload = read_json(workspace_path(args.draft_items_json))
    drafts = draft_payload.get("draft_items") or []
    selected = set(args.group_ids or [])
    if selected:
        drafts = [d for d in drafts if d.get("source_group_id") in selected]

    system_prompt = workspace_path(args.system_prompt).read_text(encoding="utf-8")
    user_template = workspace_path(args.user_prompt).read_text(encoding="utf-8")
    out_dir = workspace_path(config["owned_output_root"]) / args.run_id
    items = []
    for draft in drafts:
        compact = compact_draft(draft)
        group_out = out_dir / str(draft.get("source_group_id"))
        existing = group_out / "field_role_resolution.json"
        existing_validation = group_out / "validation_report.json"
        if args.resume and existing.exists() and existing_validation.exists():
            parsed = read_json(existing)
            validation = read_json(existing_validation)
            items.append({"draft": compact, "resolution": parsed or {}, "validation": validation})
            continue
        user_prompt = render_template(user_template, {"draft_payload": json.dumps(compact, ensure_ascii=False, indent=2)})
        call = call_model_with_retry(
            config=config,
            node=node,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            retries=args.retries,
        )
        parsed = call.get("parsed")
        if not parsed:
            parsed, parse_error = extract_json(call.get("raw_content") or "")
            call["parse_error"] = parse_error
        validation = validate_resolution(parsed or {}, compact) if parsed else {"valid": False, "errors": [{"message": call.get("parse_error", "parse failed")}]}
        write_json(group_out / "draft_input.json", compact)
        write_json(group_out / "model_call.json", call)
        if call.get("transport_error"):
            write_json(group_out / "model_error.json", {"error": call["transport_error"], "attempt": call.get("attempt")})
        write_json(group_out / "field_role_resolution.json", parsed or {})
        write_json(group_out / "validation_report.json", validation)
        items.append({"draft": compact, "resolution": parsed or {}, "validation": validation})

    payload = {
        "schema": "english_node4b_field_role_resolver_run_v0.1",
        "resolver_version": RESOLVER_VERSION,
        "prompt_version": PROMPT_VERSION,
        "source_draft_items_json": rel_workspace(workspace_path(args.draft_items_json)),
        "items": items,
        "summary": {
            "item_count": len(items),
            "valid_count": sum(1 for item in items if item["validation"].get("valid")),
            "needs_repair_count": sum(
                1
                for item in items
                if ((item.get("resolution") or {}).get("overall_assessment") or {}).get("needs_field_repair_before_builder") is True
            ),
        },
    }
    write_json(out_dir / "field_role_resolutions.json", payload)
    write_json(out_dir / "run_summary.json", {
        "schema": "english_node4b_field_role_resolver.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": rel_workspace(out_dir),
        "review_html": rel_workspace(out_dir / "review.html"),
        "summary": payload["summary"],
        "model_call_enabled": True,
        "database_write_enabled": False,
        "runtime_import_enabled": False,
    })
    write_text(out_dir / "review.html", render_review(payload))
    print(json.dumps(read_json(out_dir / "run_summary.json"), ensure_ascii=False, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--draft-items-json", required=True)
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--system-prompt", default="prompts/english_node4b_field_role_resolver_system_v0.1.md")
    parser.add_argument("--user-prompt", default="prompts/english_node4b_field_role_resolver_user_v0.1.md")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
