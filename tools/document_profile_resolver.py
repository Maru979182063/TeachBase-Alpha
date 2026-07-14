from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.semantic_profile_config import load_semantic_profile_configs
from tools.vision_prompt_store import get_document_profile_resolver_prompt_bundle


ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
PROFILE_VERSION = "document_profile_v0.2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _extract_json_block(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_not_found")
    return json.loads(clean[start : end + 1])


def _image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


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
    if any(token in text for token in ["知识", "梳理", "课程目标", "要点", "方法"]):
        modes.append("knowledge_explanation")
    if any(token in text for token in ["例题", "例", "worked", "example"]):
        modes.append("worked_examples")
    if any(token in text for token in ["练", "训练", "题", "Practice", "Choose"]):
        modes.append("exercise_driven")
    if subject == "english" and any(token in text for token in ["阅读", "Passage", "主旨", "体裁"]):
        modes.append("reading")
    if subject == "english" and any(token in text for token in ["语法", "grammar", "定语从句"]):
        modes.append("grammar")
    if subject == "english" and any(token in text for token in ["写作", "求助信", "作文", "writing"]):
        modes.append("writing")
    if subject == "biology" and "实验" in text:
        modes.append("experiment")
    return modes or ["exercise_driven"]


def _default_profile(
    *,
    pdf_path: str = "",
    doc_key: str = "",
    source_run_id: str = "",
    document_id: str = "",
    document_revision_id: str = "",
    text_stub: str = "",
    manual_override: dict[str, Any] | None = None,
    confidence_source: str = "fallback",
    prompt_version: str = "document_profile_resolver_mock_v0.2",
    config_version: str = "semantic_profiles_v0.2",
) -> dict[str, Any]:
    seed_text = " ".join([pdf_path, doc_key, text_stub])
    subject, confidence, source = _subject_from_text(seed_text)
    effective = {
        "subject": subject,
        "document_type": "teacher_handout" if "教师" in seed_text or "teacher" in seed_text.lower() else "unknown",
        "content_mode": _content_modes(subject, seed_text),
        "stage": "senior" if any(token in seed_text for token in ["高中", "高考", "高三", "高二"]) else "unknown",
        "language": "en" if subject == "english" else ("zh" if subject in {"math", "biology"} else "unknown"),
    }
    model_profile = {**effective, "confidence": confidence}
    profile_conflict = False
    if manual_override:
        for key in ["subject", "document_type", "content_mode", "stage", "language"]:
            if key in manual_override and manual_override[key]:
                if key in effective and effective[key] != manual_override[key]:
                    profile_conflict = True
                effective[key] = manual_override[key]
    profile_id_seed = {
        "document_revision_id": document_revision_id,
        "profile_version": PROFILE_VERSION,
        "effective_profile": effective,
        "config_version": config_version,
    }
    needs_review = confidence < 0.55 or profile_conflict
    return {
        "profile_version": PROFILE_VERSION,
        "document_profile_id": _stable_hash(profile_id_seed),
        "document_id": document_id,
        "document_revision_id": document_revision_id,
        "source_run_id": source_run_id,
        "model_profile": model_profile,
        "manual_override": manual_override,
        "effective_profile": effective,
        "confidence": confidence,
        "confidence_source": confidence_source,
        "threshold_version": "uncalibrated_v0.2",
        "evidence": [{"type": source, "detail": seed_text[:500], "weight": confidence}],
        "source": "manual_override" if manual_override else ("model" if confidence_source == "model_self_report" else "rule_fallback"),
        "profile_conflict": profile_conflict,
        "needs_profile_review": needs_review,
        "prompt_version": prompt_version,
        "config_version": config_version,
        "created_at": _now(),
    }


def _call_visual_profile_model(
    *,
    api_key: str,
    model: str,
    prompt: str,
    sample_images: list[Path],
    timeout_seconds: int = 45,
) -> tuple[dict[str, Any], dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in sample_images[:5]:
        if path.exists():
            content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(path)}})
    body = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0}
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
    meta = {"latency_seconds": round(time.time() - started, 3), "usage": payload.get("usage", {})}
    return parsed, meta


def resolve_document_profile(
    *,
    provider: str = "mock",
    pdf_path: str = "",
    doc_key: str = "",
    source_run_id: str = "",
    document_id: str = "",
    document_revision_id: str = "",
    text_stub: str = "",
    page_manifests: list[dict[str, Any]] | None = None,
    manual_override: dict[str, Any] | None = None,
    api_key: str = "",
    model: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    configs = load_semantic_profile_configs()
    config_version = str((configs["common.yaml"].get("config_version") or "semantic_profiles_v0.2"))
    if provider == "mock":
        return _default_profile(
            pdf_path=pdf_path,
            doc_key=doc_key,
            source_run_id=source_run_id,
            document_id=document_id,
            document_revision_id=document_revision_id,
            text_stub=text_stub,
            manual_override=manual_override,
            config_version=config_version,
        ), {"provider": "mock", "calls": 0, "usage": {}, "latency_seconds": 0.0}
    if provider != "visual":
        raise ValueError(f"unsupported_profile_provider:{provider}")
    if not api_key:
        raise RuntimeError("visual_profile_provider_requires_api_key")
    bundle = get_document_profile_resolver_prompt_bundle()
    sample_images: list[Path] = []
    for manifest in page_manifests or []:
        path = manifest.get("page_image_vlm") or manifest.get("page_image_master")
        if path:
            sample_images.append(Path(path))
    prompt = bundle["user_template"].replace("{{doc_key}}", doc_key).replace("{{text_stub}}", text_stub[:2000])
    parsed, meta = _call_visual_profile_model(api_key=api_key, model=model, prompt=prompt, sample_images=sample_images)
    profile = _default_profile(
        pdf_path=pdf_path,
        doc_key=doc_key,
        source_run_id=source_run_id,
        document_id=document_id,
        document_revision_id=document_revision_id,
        text_stub=json.dumps(parsed, ensure_ascii=False),
        manual_override=manual_override,
        confidence_source="model_self_report",
        prompt_version=bundle["prompt_version"],
        config_version=config_version,
    )
    model_profile = parsed.get("model_profile") or parsed
    if isinstance(model_profile, dict):
        for key in ["subject", "document_type", "content_mode", "stage", "language", "confidence"]:
            if key in model_profile:
                profile["model_profile"][key] = model_profile[key]
        profile["confidence"] = float(model_profile.get("confidence") or profile["confidence"])
    profile["evidence"].append({"type": "model", "detail": parsed, "weight": profile["confidence"]})
    profile["source"] = "manual_override" if manual_override else "model"
    profile["needs_profile_review"] = bool(profile["confidence"] < 0.55 or profile["profile_conflict"])
    profile["document_profile_id"] = _stable_hash(
        {
            "document_revision_id": document_revision_id,
            "profile_version": PROFILE_VERSION,
            "effective_profile": profile["effective_profile"],
            "config_version": config_version,
        }
    )
    return profile, {"provider": "visual", "calls": 1, "usage": meta.get("usage", {}), "latency_seconds": meta.get("latency_seconds", 0)}


def write_document_profile(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
