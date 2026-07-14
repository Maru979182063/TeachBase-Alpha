from __future__ import annotations

import base64
import hashlib
import html
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.semantic_profile_config import (
    default_route_for_role,
    eligible_for_question_bank,
    load_semantic_profile_configs,
    route_availability,
    semantic_enums,
    threshold_version,
)
from tools.vision_prompt_store import get_semantic_role_adapter_prompt_bundle


ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ADAPTER_VERSION = "semantic_role_adapter_v0.2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_obj(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _extract_json_block(text: str) -> Any:
    clean = str(text or "").strip()
    start_obj = clean.find("{")
    start_arr = clean.find("[")
    starts = [x for x in [start_obj, start_arr] if x >= 0]
    if not starts:
        raise ValueError("json_not_found")
    start = min(starts)
    end = clean.rfind("}" if clean[start] == "{" else "]")
    if end < start:
        raise ValueError("json_not_found")
    return json.loads(clean[start : end + 1])


def _image_to_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _audit_map(audit_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("node_id", "")): r for r in audit_report.get("records", []) if r.get("node_id")}


def _reading_block_map(reading_blocks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(b.get("block_id", "")): b for b in reading_blocks.get("blocks", []) if b.get("block_id")}


def _node_block_ids(node: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for frag in node.get("fragments", []) or []:
        ids.extend(str(x) for x in frag.get("block_ids", []) or [])
    return ids


def _node_context(nodes: list[dict[str, Any]], idx: int) -> dict[str, Any]:
    before = nodes[max(0, idx - 2) : idx]
    after = nodes[idx + 1 : idx + 3]
    def slim(n: dict[str, Any]) -> dict[str, Any]:
        return {
            "node_id": n.get("node_id"),
            "node_type": n.get("node_type"),
            "review_status": n.get("review_status"),
            "text_stub": str(n.get("text_stub", ""))[:320],
        }
    return {"previous_nodes": [slim(n) for n in before], "next_nodes": [slim(n) for n in after]}


def _infer_semantic_role(node: dict[str, Any], audit: dict[str, Any], text: str) -> tuple[str, str, float, list[dict[str, Any]]]:
    lower = text.lower()
    flags = [flag for frag in node.get("fragments", []) or [] for flag in frag.get("flags", []) or []]
    evidence: list[dict[str, Any]] = []
    if node.get("node_type") == "knowledge_block" or "knowledge_like" in flags or "possible_section_heading" in flags:
        evidence.append({"type": "existing_assignment", "detail": "knowledge_like_or_section", "weight": 0.5})
        return "knowledge", "text", 0.76, evidence
    if audit.get("status") == "QUARANTINED":
        evidence.append({"type": "audit_signal", "detail": "quarantined", "weight": 1.0})
        return "unknown", "unknown", 0.35, evidence
    if any(token in text for token in ["【答案】", "答案", "【解析】", "解析", "【详解】", "翻译"]):
        if "question_body" not in [f.get("role") for f in node.get("fragments", []) or []]:
            evidence.append({"type": "content_function", "detail": "answer_or_analysis_without_stem", "weight": 0.8})
            return "answer_explanation", "text", 0.74, evidence
    if "passage" in lower or any(token in text for token in ["阅读", "文章", "材料", "实验材料"]):
        evidence.append({"type": "content_function", "detail": "source_material_marker", "weight": 0.6})
        return "source_material", "text", 0.72, evidence
    if any(token in text for token in ["例题", "【例", "解：", "分析", "详解"]) and any(token in text for token in ["答案", "解析", "解得"]):
        evidence.append({"type": "content_function", "detail": "worked_example_like", "weight": 0.65})
        return "worked_example", _presentation_kind(text, flags), 0.78, evidence
    if node.get("node_type") == "question" or "possible_question_start" in flags:
        evidence.append({"type": "existing_assignment", "detail": "question_node_or_start_flag", "weight": 0.65})
        return "exercise", _presentation_kind(text, flags), 0.82, evidence
    evidence.append({"type": "fallback", "detail": "no_strong_role_signal", "weight": 0.2})
    return "unknown", _presentation_kind(text, flags), 0.40, evidence


def _presentation_kind(text: str, flags: list[str]) -> str:
    if "table_like" in flags or "|" in text or "□" in text:
        return "table"
    if "diagram_like" in flags or any(token in text for token in ["如图", "图", "函数图象", "几何"]):
        return "diagram"
    if any(token in text for token in ["\\frac", "\\overrightarrow", "∠", "⊥", "∥"]):
        return "formula_heavy"
    return "text"


def _relations_for(node: dict[str, Any], role: str, nodes: list[dict[str, Any]], idx: int, confidence: float) -> list[dict[str, Any]]:
    if role != "answer_explanation":
        return []
    for prev in reversed(nodes[:idx]):
        if prev.get("node_type") == "question":
            return [
                {
                    "type": "explains",
                    "source_node_id": node.get("node_id", ""),
                    "target_node_id": prev.get("node_id", ""),
                    "confidence": max(0.0, min(confidence, 0.72)),
                    "evidence": [{"type": "context_relation", "detail": "nearest_previous_question"}],
                }
            ]
    return []


def _safe_unknown(node: dict[str, Any], profile: dict[str, Any], reason: str, configs: dict[str, Any]) -> dict[str, Any]:
    return _finalize_result(
        {
            "adapter_version": ADAPTER_VERSION,
            "source_run_id": profile.get("source_run_id", ""),
            "document_profile_id": profile.get("document_profile_id", ""),
            "node_id": node.get("node_id", ""),
            "node_type": node.get("node_type", ""),
            "semantic_role": "unknown",
            "presentation_kind": "unknown",
            "disposition": "review_required",
            "profile_subtype": "",
            "functional_description": reason,
            "route": "review_only",
            "route_availability": "implemented",
            "effective_route": "review_only",
            "confidence": 0.0,
            "confidence_source": "fallback",
            "threshold_version": threshold_version(configs),
            "hard_constraints_passed": False,
            "evidence": [{"type": "fallback", "detail": reason, "weight": 1.0}],
            "title_text": "",
            "content_summary": str(node.get("text_stub", ""))[:360],
            "shared_context_node_ids": [],
            "relations": [],
            "requires_secondary_split": False,
            "preserve_as_handout_content": True,
            "eligible_for_question_bank": False,
            "needs_role_review": True,
            "fallback_route": "review_only",
            "prompt_version": "",
            "config_version": "semantic_profiles_v0.2",
            "model": "",
            "created_at": _now(),
        },
        configs,
        {},
    )


def _finalize_result(result: dict[str, Any], configs: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    enums = semantic_enums(configs)
    if result.get("semantic_role") not in enums["semantic_roles"]:
        result["semantic_role"] = "unknown"
        result["disposition"] = "review_required"
        result["needs_role_review"] = True
    if result.get("presentation_kind") not in enums["presentation_kinds"]:
        result["presentation_kind"] = "unknown"
    if result.get("disposition") not in enums["dispositions"]:
        result["disposition"] = "review_required"
    if result.get("route") not in enums["routes"]:
        result["route"] = "review_only"
    if not result.get("route"):
        result["route"] = default_route_for_role(configs, str(result.get("semantic_role") or "unknown"))
    result["route_availability"] = route_availability(configs, str(result.get("route") or "review_only"))
    result["effective_route"] = result.get("route") if result["route_availability"] == "implemented" else "review_only"
    result["threshold_version"] = result.get("threshold_version") or threshold_version(configs)
    result["hard_constraints_passed"] = True

    audit_status = audit.get("status") or result.get("split_audit_status")
    if audit_status and audit_status != "AUDITED_READY":
        result["disposition"] = "structurally_blocked"
        result["effective_route"] = "review_only"
        result["hard_constraints_passed"] = False
        result["needs_role_review"] = True
    if result.get("semantic_role") == "mixed":
        result["requires_secondary_split"] = True
        result["disposition"] = "review_required"
        result["effective_route"] = "review_only"
        result["hard_constraints_passed"] = False
        result["needs_role_review"] = True
    if result.get("semantic_role") == "answer_explanation":
        valid_relation = False
        for rel in result.get("relations", []) or []:
            if rel.get("type") in {"answers", "explains"} and rel.get("target_node_id") and float(rel.get("confidence") or 0) >= 0.88:
                valid_relation = True
        if not valid_relation:
            result["disposition"] = "review_required"
            result["effective_route"] = "review_only"
            result["hard_constraints_passed"] = False
            result["needs_role_review"] = True
    if result["route_availability"] != "implemented":
        result["effective_route"] = "review_only"
    if result.get("semantic_role") in {"unknown", "mixed"} or result.get("disposition") != "processable":
        result["needs_role_review"] = True
    result["eligible_for_question_bank"] = bool(eligible_for_question_bank(configs, str(result.get("semantic_role"))))
    return result


def _mock_result(
    node: dict[str, Any],
    nodes: list[dict[str, Any]],
    idx: int,
    audit: dict[str, Any],
    profile: dict[str, Any],
    configs: dict[str, Any],
) -> dict[str, Any]:
    text = str(node.get("text_stub", "") or "")
    role, presentation, confidence, evidence = _infer_semantic_role(node, audit, text)
    route = default_route_for_role(configs, role)
    result = {
        "adapter_version": ADAPTER_VERSION,
        "source_run_id": profile.get("source_run_id", ""),
        "document_profile_id": profile.get("document_profile_id", ""),
        "node_id": node.get("node_id", ""),
        "node_type": node.get("node_type", ""),
        "semantic_role": role,
        "presentation_kind": presentation,
        "disposition": "processable",
        "profile_subtype": "",
        "functional_description": f"mock semantic role inferred as {role}",
        "route": route,
        "route_availability": route_availability(configs, route),
        "effective_route": route,
        "confidence": confidence,
        "confidence_source": "fallback",
        "threshold_version": threshold_version(configs),
        "hard_constraints_passed": True,
        "evidence": evidence,
        "title_text": "",
        "content_summary": text[:360],
        "shared_context_node_ids": [],
        "relations": _relations_for(node, role, nodes, idx, confidence),
        "requires_secondary_split": role == "mixed",
        "preserve_as_handout_content": True,
        "eligible_for_question_bank": eligible_for_question_bank(configs, role),
        "needs_role_review": confidence < 0.80 or role in {"unknown", "mixed"},
        "fallback_route": "review_only",
        "prompt_version": "semantic_role_adapter_mock_v0.2",
        "config_version": "semantic_profiles_v0.2",
        "model": "mock",
        "created_at": _now(),
    }
    return _finalize_result(result, configs, audit)


def _call_visual_batch(
    *,
    api_key: str,
    model: str,
    prompt: str,
    nodes: list[dict[str, Any]],
    timeout_seconds: int = 90,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        ARK_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    parsed = _extract_json_block(payload["choices"][0]["message"]["content"])
    if isinstance(parsed, dict):
        results = parsed.get("results") or parsed.get("nodes") or []
    else:
        results = parsed
    if not isinstance(results, list):
        raise ValueError("visual_adapter_results_not_list")
    return results, {"latency_seconds": round(time.time() - started, 3), "usage": payload.get("usage", {}), "node_count": len(nodes)}


def adapt_semantic_roles(
    *,
    semantic_nodes: dict[str, Any],
    reading_blocks: dict[str, Any],
    audit_report: dict[str, Any],
    document_profile: dict[str, Any],
    provider: str = "mock",
    api_key: str = "",
    model: str = "",
    batch_size: int = 8,
    max_calls: int = 12,
) -> tuple[dict[str, Any], dict[str, Any]]:
    configs = load_semantic_profile_configs()
    nodes = list(semantic_nodes.get("nodes", []) or [])
    audits = _audit_map(audit_report)
    rb_map = _reading_block_map(reading_blocks)
    results: list[dict[str, Any]] = []
    metrics = {
        "schema": "semantic_role_adapter_metrics_v0.2",
        "provider": provider,
        "model": model if provider == "visual" else "mock",
        "actual_model_calls": 0,
        "max_calls": max_calls,
        "cache_hits": 0,
        "fallback_count": 0,
        "failed_calls": 0,
        "usage": {},
        "latency_seconds": 0.0,
        "node_count": len(nodes),
    }
    if provider == "mock":
        for idx, node in enumerate(nodes):
            results.append(_mock_result(node, nodes, idx, audits.get(str(node.get("node_id")), {}), document_profile, configs))
    elif provider == "visual":
        if not api_key:
            raise RuntimeError("visual_semantic_role_provider_requires_api_key")
        bundle = get_semantic_role_adapter_prompt_bundle()
        for start in range(0, len(nodes), max(1, batch_size)):
            if metrics["actual_model_calls"] >= max_calls:
                for node in nodes[start:]:
                    metrics["fallback_count"] += 1
                    results.append(_safe_unknown(node, document_profile, "max_calls_exceeded", configs))
                break
            batch = nodes[start : start + max(1, batch_size)]
            slim_batch = []
            for idx, node in enumerate(batch, start=start):
                block_ids = _node_block_ids(node)
                slim_batch.append(
                    {
                        "node": {
                            "node_id": node.get("node_id"),
                            "node_type": node.get("node_type"),
                            "review_status": node.get("review_status"),
                            "text_stub": str(node.get("text_stub", ""))[:1200],
                            "fragments": node.get("fragments", []),
                        },
                        "reading_blocks": [rb_map.get(block_id, {}) for block_id in block_ids][:8],
                        "audit": audits.get(str(node.get("node_id")), {}),
                        "context": _node_context(nodes, idx),
                    }
                )
            prompt = bundle["user_template"].replace("{{document_profile}}", json.dumps(document_profile, ensure_ascii=False)).replace(
                "{{nodes_json}}", json.dumps(slim_batch, ensure_ascii=False)
            )
            try:
                parsed_results, meta = _call_visual_batch(api_key=api_key, model=model, prompt=prompt, nodes=batch)
                metrics["actual_model_calls"] += 1
                metrics["latency_seconds"] += float(meta.get("latency_seconds", 0) or 0)
                metrics["usage"] = _merge_usage(metrics["usage"], meta.get("usage", {}))
                by_id = {str(item.get("node_id", "")): item for item in parsed_results if isinstance(item, dict)}
                for node in batch:
                    raw = by_id.get(str(node.get("node_id"))) or {}
                    if not raw:
                        metrics["fallback_count"] += 1
                        results.append(_safe_unknown(node, document_profile, "model_missing_node_result", configs))
                        continue
                    merged = _mock_result(node, nodes, nodes.index(node), audits.get(str(node.get("node_id")), {}), document_profile, configs)
                    for key in [
                        "semantic_role",
                        "presentation_kind",
                        "disposition",
                        "profile_subtype",
                        "functional_description",
                        "route",
                        "confidence",
                        "evidence",
                        "relations",
                        "requires_secondary_split",
                        "needs_role_review",
                    ]:
                        if key in raw:
                            merged[key] = raw[key]
                    merged["confidence_source"] = "model_self_report"
                    merged["prompt_version"] = bundle["prompt_version"]
                    merged["model"] = model
                    results.append(_finalize_result(merged, configs, audits.get(str(node.get("node_id")), {})))
            except Exception as exc:
                metrics["actual_model_calls"] += 1
                metrics["failed_calls"] += 1
                for node in batch:
                    metrics["fallback_count"] += 1
                    results.append(_safe_unknown(node, document_profile, f"model_call_failed:{exc}", configs))
    else:
        raise ValueError(f"unsupported_semantic_role_provider:{provider}")
    payload = {
        "schema": "semantic_role_adapter_results_v0.2",
        "adapter_version": ADAPTER_VERSION,
        "document_profile_id": document_profile.get("document_profile_id", ""),
        "result_id": _hash_obj({"nodes": [r.get("node_id") for r in results], "profile": document_profile.get("document_profile_id", "")}),
        "results": results,
    }
    return payload, metrics


def _merge_usage(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a or {})
    for key, value in (b or {}).items():
        if isinstance(value, (int, float)):
            out[key] = out.get(key, 0) + value
    return out


def build_diff_report(
    *,
    semantic_nodes: dict[str, Any],
    adapter_results: dict[str, Any],
    audit_report: dict[str, Any],
) -> dict[str, Any]:
    audits = _audit_map(audit_report)
    result_by_id = {str(r.get("node_id")): r for r in adapter_results.get("results", [])}
    rows = []
    counts = {
        "exercise_to_knowledge_candidates": 0,
        "knowledge_to_question_splitter_candidates": 0,
        "answer_target_missing": 0,
        "mixed_review": 0,
        "needs_manual_review": 0,
    }
    for node in semantic_nodes.get("nodes", []) or []:
        node_id = str(node.get("node_id"))
        result = result_by_id.get(node_id, {})
        old_type = str(node.get("node_type", ""))
        semantic_role = str(result.get("semantic_role", ""))
        effective_route = str(result.get("effective_route", ""))
        hard = []
        if old_type == "question" and semantic_role == "knowledge":
            counts["exercise_to_knowledge_candidates"] += 1
            hard.append("exercise_to_knowledge_candidate")
        if "knowledge" in old_type and effective_route == "question_splitter":
            counts["knowledge_to_question_splitter_candidates"] += 1
            hard.append("knowledge_to_question_splitter_candidate")
        if semantic_role == "answer_explanation" and not any(rel.get("target_node_id") for rel in result.get("relations", []) or []):
            counts["answer_target_missing"] += 1
            hard.append("answer_target_missing")
        if semantic_role == "mixed" and result.get("needs_role_review"):
            counts["mixed_review"] += 1
        if result.get("needs_role_review"):
            counts["needs_manual_review"] += 1
        pages = sorted({frag.get("page") for frag in node.get("fragments", []) or [] if frag.get("page")})
        rows.append(
            {
                "node_id": node_id,
                "pages": pages,
                "current_node_type": old_type,
                "current_review_status": node.get("review_status", ""),
                "current_audit_reasons": (audits.get(node_id) or {}).get("reasons", []),
                "new_semantic_role": semantic_role,
                "presentation_kind": result.get("presentation_kind", ""),
                "disposition": result.get("disposition", ""),
                "suggested_route": result.get("route", ""),
                "route_availability": result.get("route_availability", ""),
                "effective_route": effective_route,
                "confidence": result.get("confidence", 0),
                "hard_constraints_passed": result.get("hard_constraints_passed", False),
                "relations": result.get("relations", []),
                "hard_misroute_candidates": hard,
                "needs_role_review": bool(result.get("needs_role_review", False)),
                "diff_reason": _diff_reason(node, result),
            }
        )
    return {"schema": "semantic_role_adapter_diff_report_v0.2", "rows": rows, "metrics": counts}


def _diff_reason(node: dict[str, Any], result: dict[str, Any]) -> str:
    old_type = str(node.get("node_type", ""))
    role = str(result.get("semantic_role", ""))
    if old_type == "question" and role not in {"exercise", "worked_example", "question_group", "unknown"}:
        return "old_question_type_role_changed"
    if "knowledge" in old_type and role not in {"knowledge", "method_or_strategy", "unknown"}:
        return "old_knowledge_type_role_changed"
    if result.get("effective_route") != result.get("route"):
        return "route_fallback_by_availability_or_constraints"
    return "no_major_diff"


def write_review_samples(path: Path, diff_report: dict[str, Any], adapter_results: dict[str, Any], max_rows: int = 80) -> None:
    result_by_id = {str(r.get("node_id")): r for r in adapter_results.get("results", [])}
    rows = []
    for row in diff_report.get("rows", [])[:max_rows]:
        result = result_by_id.get(str(row.get("node_id")), {})
        rows.append(
            "<article>"
            f"<h2>{html.escape(str(row.get('node_id','')))} <span>{html.escape(str(row.get('new_semantic_role','')))} / {html.escape(str(row.get('effective_route','')))}</span></h2>"
            f"<p>old: {html.escape(str(row.get('current_node_type','')))} | audit: {html.escape(str(row.get('current_review_status','')))} | confidence: {row.get('confidence',0)}</p>"
            f"<p>presentation: {html.escape(str(row.get('presentation_kind','')))} | disposition: {html.escape(str(row.get('disposition','')))} | availability: {html.escape(str(row.get('route_availability','')))}</p>"
            f"<p>hard: {html.escape(', '.join(row.get('hard_misroute_candidates', [])))} | needs review: {row.get('needs_role_review')}</p>"
            f"<pre>{html.escape(json.dumps(result.get('evidence', []), ensure_ascii=False, indent=2))}</pre>"
            f"<pre>{html.escape(json.dumps(row.get('relations', []), ensure_ascii=False, indent=2))}</pre>"
            "</article>"
        )
    html_text = f"""<!doctype html>
<meta charset="utf-8">
<title>Semantic Role Adapter Shadow Review</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f6f8fb;color:#142033;margin:24px}}
article{{background:white;border:1px solid #d9e1ef;border-radius:12px;padding:14px;margin:12px 0}}
h2{{font-size:16px;margin:0 0 8px}} h2 span{{font-size:12px;color:#667}}
pre{{white-space:pre-wrap;background:#f8fafc;padding:8px;border-radius:8px;max-height:260px;overflow:auto}}
</style>
<h1>Semantic Role Adapter Shadow Review</h1>
{''.join(rows)}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
