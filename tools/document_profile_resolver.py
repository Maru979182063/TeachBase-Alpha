from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .semantic_profile_config import load_semantic_profile_configs
except ImportError:
    from semantic_profile_config import load_semantic_profile_configs


PROFILE_VERSION = "document_profile_shadow.v0.2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _subject_from_text(text: str) -> tuple[str, float, str]:
    lowered = text.lower()
    if "英语" in text or "english" in lowered or "reading" in lowered or "writing" in lowered:
        return "english", 0.78, "path_or_text"
    if "数学" in text or "math" in lowered or any(token in text for token in ["函数", "几何", "导数", "向量"]):
        return "math", 0.78, "path_or_text"
    if "生物" in text or "biology" in lowered or any(token in text for token in ["遗传", "细胞", "实验"]):
        return "biology", 0.72, "path_or_text"
    return "unknown", 0.30, "unknown"


def _content_modes(subject: str, text: str) -> list[str]:
    modes: list[str] = []
    lowered = text.lower()
    if any(token in text for token in ["知识", "梳理", "课程目标", "要点", "方法"]):
        modes.append("knowledge_explanation")
    if any(token in text for token in ["例题", "例", "worked", "example"]):
        modes.append("worked_examples")
    if any(token in text for token in ["练", "训练", "题"]) or "practice" in lowered or "choose" in lowered:
        modes.append("exercise_driven")
    if subject == "english" and any(token in text for token in ["阅读", "文章", "主旨", "体裁"]) or "passage" in lowered:
        modes.append("reading")
    if subject == "english" and any(token in text for token in ["语法", "定语从句"]) or "grammar" in lowered:
        modes.append("grammar")
    if subject == "english" and any(token in text for token in ["写作", "求助信", "作文"]) or "writing" in lowered:
        modes.append("writing")
    if subject == "biology" and "实验" in text:
        modes.append("experiment")
    return modes or ["exercise_driven"]


def _node_text_stub(semantic_nodes: dict[str, Any], limit: int = 8) -> str:
    nodes = list(semantic_nodes.get("nodes") or [])
    return "\n".join(str(node.get("text_stub", "")) for node in nodes[:limit])


def resolve_document_profile(
    *,
    doc_root: Path,
    semantic_nodes: dict[str, Any],
    audit_report: dict[str, Any],
    pdf_path: str = "",
    doc_key: str = "",
    source_run_id: str = "",
    document_id: str = "",
    document_revision_id: str = "",
    manual_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic shadow profile without reading models or mutating pipeline artifacts."""
    configs = load_semantic_profile_configs()
    config_version = str(configs["common.yaml"].get("config_version") or "semantic_profiles_v0.2")
    nodes = list(semantic_nodes.get("nodes") or [])
    audit_records = list(audit_report.get("records") or [])
    status_counts = Counter(str(node.get("review_status") or "") for node in nodes)
    node_type_counts = Counter(str(node.get("node_type") or "") for node in nodes)
    pages = sorted(
        {
            int(fragment.get("page"))
            for node in nodes
            for fragment in (node.get("fragments") or [])
            if fragment.get("page") is not None
        }
    )
    review_reasons = sorted(
        {
            str(reason)
            for record in audit_records
            for reason in (record.get("reasons") or [])
        }
    )
    seed_text = " ".join([str(pdf_path), str(doc_key), str(doc_root), _node_text_stub(semantic_nodes)])
    subject, confidence, source = _subject_from_text(seed_text)
    effective_profile = {
        "subject": subject,
        "document_type": "teacher_handout" if "教师" in seed_text or "teacher" in seed_text.lower() else "unknown",
        "content_mode": _content_modes(subject, seed_text),
        "stage": "senior" if any(token in seed_text for token in ["高中", "高考", "高三", "高二"]) else "unknown",
        "language": "en" if subject == "english" else ("zh" if subject in {"math", "biology"} else "unknown"),
    }
    model_profile = {**effective_profile, "confidence": confidence}
    profile_conflict = False
    if manual_override:
        for key in ["subject", "document_type", "content_mode", "stage", "language"]:
            if key in manual_override and manual_override[key]:
                if key in effective_profile and effective_profile[key] != manual_override[key]:
                    profile_conflict = True
                effective_profile[key] = manual_override[key]
    profile_id_seed = {
        "document_revision_id": document_revision_id,
        "profile_version": PROFILE_VERSION,
        "effective_profile": effective_profile,
        "config_version": config_version,
    }
    needs_review = confidence < 0.55 or profile_conflict
    return {
        "schema_version": PROFILE_VERSION,
        "doc_root": str(doc_root),
        "resolver_mode": "shadow_only_deterministic_profile",
        "adapter_mode": "shadow_only",
        "business_mutation_allowed": False,
        "model_invoked": False,
        "paid_model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
        "document_profile_id": _stable_hash(profile_id_seed),
        "document_id": document_id,
        "document_revision_id": document_revision_id,
        "source_run_id": source_run_id,
        "model_profile": model_profile,
        "manual_override": manual_override or {},
        "effective_profile": effective_profile,
        "confidence": confidence,
        "confidence_source": "rule_fallback",
        "threshold_version": "uncalibrated_v0.2",
        "evidence": [{"type": source, "detail": seed_text[:500], "weight": confidence}],
        "source": "manual_override" if manual_override else "rule_fallback",
        "profile_conflict": profile_conflict,
        "needs_profile_review": needs_review,
        "prompt_version": "no_prompt_shadow_rules_v0.2",
        "config_version": config_version,
        "node_count": len(nodes),
        "node_type_counts": dict(sorted(node_type_counts.items())),
        "review_status_counts": dict(sorted(status_counts.items())),
        "pages": pages,
        "review_reasons": review_reasons,
        "created_at": _now(),
    }
