from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from compose_legacy_stem_md import compose_legacy_stem_md
from question_visual_structure_contract import SCHEMA_VERSION, normalize_review_flags
from source_refs_json_merge import merge_source_refs_json

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
# Source container images are evidence only. Formal image assets must come from
# staged_visual_assets so the runtime doesn't confuse whole long crops with
# semantic in-question figures.
IMAGE_FIELDS = (
    ("question_image", "evidence_only", "question_source"),
    ("stem_image", "evidence_only", "stem_source"),
    ("analysis_image", "evidence_only", "analysis_source"),
)


def safe_slug(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(text or "").strip())
    value = value.strip("._-")
    return value[:80].rstrip("._-") or "question"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_path(raw: str, base_dir: Path) -> Path:
    candidate = Path(str(raw or "").strip())
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def load_split_questions(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("source_json_must_be_object")
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("source_json_questions_must_be_list")
    return [q for q in questions if isinstance(q, dict)]


def flatten_visual_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def load_visual_results(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = read_json(path)
    records = flatten_visual_records(payload)
    by_question_id: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = str(record.get("question_id", "") or "").strip()
        if not question_id:
            continue
        transcription = record.get("transcription")
        merged = dict(record)
        if isinstance(transcription, dict):
            merged.update(transcription)
        by_question_id[question_id] = merged
    return by_question_id


def pick_text(question: dict[str, Any], visual: dict[str, Any], split_key: str, md_key: str) -> str:
    for source in (visual, question):
        value = source.get(md_key)
        if value:
            return str(value)
    value = question.get(split_key)
    return str(value or "")


def pick_bool(question: dict[str, Any], visual: dict[str, Any], key: str) -> bool:
    if key in visual:
        return bool(visual.get(key))
    return bool(question.get(key))


def image_extension(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else ".png"


def copy_asset(
    source_path: Path,
    out_dir: Path,
    question_id: str,
    role: str,
    placement: str,
    include_debug_paths: bool = False,
) -> dict[str, Any]:
    asset_id = f"{safe_slug(question_id)}__{role}"
    rel_path = Path("assets") / safe_slug(question_id) / f"{role}{image_extension(source_path)}"
    target_path = out_dir / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    asset = {
        "asset_id": asset_id,
        "role": role,
        "placement": placement,
        "asset_role": role,
        "placement_scope": placement,
        "option_key": None,
        "display_ref": f"asset://{asset_id}",
        "storage_key": rel_path.as_posix(),
        "mime_type": "image/png" if rel_path.suffix.lower() == ".png" else f"image/{rel_path.suffix.lower().lstrip('.')}",
        "materialized": True,
        "file_status": "materialized",
        "attach_status": "attached" if placement != "evidence_only" else "not_attached_unassigned",
        "review_flags": [],
    }
    if include_debug_paths:
        asset["debug"] = {
            "local_path": str(target_path.resolve()),
            "source_path": str(source_path.resolve()),
        }
    return asset


def _resolve_bbox_source(question: dict[str, Any], bbox_space: str, base_dir: Path) -> Path | None:
    source_key = "stem_image" if bbox_space == "stem_image" else "question_image"
    if bbox_space == "analysis_image":
        source_key = "analysis_image"
    raw = str(question.get(source_key, "") or "").strip()
    if not raw:
        return None
    return resolve_path(raw, base_dir)


def _is_suspicious_crop(image: Image.Image) -> bool:
    if image.width < 24 or image.height < 24:
        return True
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    extrema = gray.getextrema()
    if extrema and abs(extrema[1] - extrema[0]) <= 4:
        return True
    if stat.stddev and stat.stddev[0] < 2.0:
        return True
    return False


def _average_hash(path: Path, size: int = 8) -> str:
    with Image.open(path) as image:
        gray = image.convert("L").resize((size, size))
        pixels = list(gray.getdata())
    mean = sum(pixels) / max(len(pixels), 1)
    bits = "".join("1" if px >= mean else "0" for px in pixels)
    return f"{int(bits, 2):016x}"


def _hamming_distance(a: str, b: str) -> int:
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except Exception:
        return 64


def _role_priority(asset: dict[str, Any]) -> int:
    role = str(asset.get("asset_role", asset.get("role", "")) or "")
    if role == "option":
        return 4
    if role == "analysis":
        return 3
    if role == "stem":
        return 2
    if role == "evidence":
        return 1
    return 0


def dedupe_materialized_assets(assets: list[dict[str, Any]], out_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    signatures: list[tuple[dict[str, Any], str, tuple[int, int]]] = []

    for asset in assets:
        storage_key = str(asset.get("storage_key", "") or "").strip()
        target_path = out_dir / storage_key if storage_key else None
        if not storage_key or target_path is None or not target_path.exists() or not bool(asset.get("materialized", False)):
            kept.append(asset)
            continue
        try:
            with Image.open(target_path) as image:
                size = image.size
            signature = _average_hash(target_path)
        except Exception:
            kept.append(asset)
            continue

        duplicate_of: dict[str, Any] | None = None
        for existing_asset, existing_sig, existing_size in signatures:
            if size != existing_size:
                continue
            if _hamming_distance(signature, existing_sig) <= 1:
                duplicate_of = existing_asset
                break

        if duplicate_of is None:
            signatures.append((asset, signature, size))
            kept.append(asset)
            continue

        current_priority = _role_priority(asset)
        existing_priority = _role_priority(duplicate_of)
        if current_priority > existing_priority:
            duplicate_of["review_flags"] = normalize_review_flags(list(duplicate_of.get("review_flags", []) or []) + ["duplicate_visual_asset_removed"])
            dup_storage_key = str(duplicate_of.get("storage_key", "") or "").strip()
            if dup_storage_key:
                dup_path = out_dir / dup_storage_key
                try:
                    if dup_path.exists():
                        dup_path.unlink()
                except Exception:
                    pass
            removed.append(duplicate_of)
            kept = [item for item in kept if item is not duplicate_of]
            signatures = [
                (asset if existing_asset is duplicate_of else existing_asset, signature if existing_asset is duplicate_of else existing_sig, size if existing_asset is duplicate_of else existing_size)
                for existing_asset, existing_sig, existing_size in signatures
            ]
            asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + ["duplicate_visual_asset_kept"])
            kept.append(asset)
        else:
            asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + ["duplicate_visual_asset_removed"])
            dup_storage_key = str(asset.get("storage_key", "") or "").strip()
            if dup_storage_key:
                dup_path = out_dir / dup_storage_key
                try:
                    if dup_path.exists():
                        dup_path.unlink()
                except Exception:
                    pass
            removed.append(asset)

    return kept, removed


def materialize_staged_asset(
    staged_asset: dict[str, Any],
    question: dict[str, Any],
    base_dir: Path,
    out_dir: Path,
    include_debug_paths: bool = False,
) -> dict[str, Any]:
    asset = dict(staged_asset)
    asset["placement"] = str(asset.get("placement", asset.get("placement_scope", "")) or "")
    storage_key = str(asset.get("storage_key", "") or "").strip()
    bbox_space = str(asset.get("bbox_space", "") or "").strip()
    bbox = asset.get("bbox_json", {}) if isinstance(asset.get("bbox_json"), dict) else {}
    source_path = _resolve_bbox_source(question, bbox_space, base_dir)
    if not storage_key or source_path is None or not source_path.exists():
        asset["materialized"] = False
        asset["file_status"] = "failed"
        asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + ["asset_materialize_failed"])
        return asset
    target_path = out_dir / Path(storage_key)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    x = max(int(bbox.get("x", 0) or 0), 0)
    y = max(int(bbox.get("y", 0) or 0), 0)
    w = max(int(bbox.get("w", 0) or 0), 0)
    h = max(int(bbox.get("h", 0) or 0), 0)
    try:
        with Image.open(source_path) as image:
            crop = image.crop((x, y, min(x + w, image.width), min(y + h, image.height))).convert("RGB")
            if crop.width <= 0 or crop.height <= 0 or _is_suspicious_crop(crop):
                if str(asset.get("asset_role", "") or "") == "option":
                    asset["asset_role"] = "evidence"
                    asset["placement_scope"] = "evidence_only"
                    asset["option_key"] = None
                    asset["attach_status"] = "not_attached_low_confidence"
                asset["materialized"] = False
                asset["file_status"] = "failed"
                asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + ["option_asset_suspicious_crop"])
                return asset
            crop.save(target_path)
    except Exception:
        asset["materialized"] = False
        asset["file_status"] = "failed"
        asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + ["asset_materialize_failed"])
        return asset
    asset["materialized"] = True
    asset["file_status"] = "materialized"
    if include_debug_paths:
        asset["debug"] = {
            "local_path": str(target_path.resolve()),
            "source_path": str(source_path.resolve()),
        }
    return asset


def _build_qvs(record: dict[str, Any], question: dict[str, Any], visual: dict[str, Any], all_assets: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    base_qvs = visual.get("question_visual_structure", {}) if isinstance(visual.get("question_visual_structure"), dict) else {}
    asset_flags: list[str] = []
    for asset in all_assets:
        asset_flags.extend(asset.get("review_flags", []) or [])
    qvs = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": str(base_qvs.get("generated_by", "assetize_question_images") or "assetize_question_images"),
        "runtime_run_id": str(base_qvs.get("runtime_run_id", "") or ""),
        "question_uid": str(base_qvs.get("question_uid", question.get("question_uid", question.get("question_id", ""))) or ""),
        "stem_md": str(base_qvs.get("stem_md", record["stem_text_md"]) or record["stem_text_md"]),
        "answer_md": str(base_qvs.get("answer_md", record["answer_text_md"]) or record["answer_text_md"]),
        "analysis_md": str(base_qvs.get("analysis_md", record["analysis_text_md"]) or record["analysis_text_md"]),
        "legacy_stem_md": str(base_qvs.get("legacy_stem_md", "") or ""),
        "gating": base_qvs.get("gating", question.get("gating_result", {})) if isinstance(base_qvs.get("gating", question.get("gating_result", {})), dict) else {},
        "options": [item for item in (base_qvs.get("options", []) or []) if isinstance(item, dict)],
        "content_blocks": [item for item in (base_qvs.get("content_blocks", []) or []) if isinstance(item, dict)],
        "visual_assets": all_assets,
        "review_flags": normalize_review_flags(list(base_qvs.get("review_flags", []) or []) + asset_flags),
    }
    legacy_stem_md, legacy_flags = compose_legacy_stem_md(
        qvs["stem_md"],
        qvs["options"],
        qvs["content_blocks"],
        all_assets,
    )
    qvs["legacy_stem_md"] = legacy_stem_md
    qvs["review_flags"] = normalize_review_flags(list(qvs.get("review_flags", []) or []) + legacy_flags)
    merged_source_refs_json, merge_flags = merge_source_refs_json(
        question.get("source_refs_json", {}) if isinstance(question.get("source_refs_json"), dict) else {},
        qvs,
    )
    if merge_flags:
        qvs["review_flags"] = normalize_review_flags(list(qvs.get("review_flags", []) or []) + merge_flags)
    return qvs, merged_source_refs_json


def build_markdown(record: dict[str, Any]) -> str:
    stem = record["stem_text_md"].strip()
    answer = record["answer_text_md"].strip()
    analysis = record["analysis_text_md"].strip()
    stem_assets = [a for a in record["assets"] if a["placement"] == "after_stem"]
    analysis_assets = [a for a in record["assets"] if a["placement"] == "after_analysis"]

    parts: list[str] = []
    if stem:
        parts.append("## 题干\n" + stem)
    for asset in stem_assets:
        parts.append(
            "\n".join(
                [
                    f"![{asset.get('role', asset.get('asset_role', 'image'))}]({asset['display_ref']})",
                    f"`storage_key: {asset['storage_key']}`",
                ]
            )
        )
    if answer:
        parts.append("## 答案\n" + answer)
    if analysis:
        parts.append("## 解析\n" + analysis)
    for asset in analysis_assets:
        parts.append(
            "\n".join(
                [
                    f"![{asset.get('role', asset.get('asset_role', 'image'))}]({asset['display_ref']})",
                    f"`storage_key: {asset['storage_key']}`",
                ]
            )
        )
    return "\n\n".join(parts).strip()


def build_qvs_display_markdown(qvs: dict[str, Any], fallback_record: dict[str, Any]) -> str:
    parts: list[str] = []
    blocks = qvs.get("content_blocks", []) if isinstance(qvs.get("content_blocks"), list) else []
    if blocks:
        heading_map = {
            "stem": "## 题干",
            "answer": "## 答案",
            "analysis": "## 解析",
            "handwriting": "## 手写",
        }
        for block in blocks:
            block_type = str(block.get("block_type", "") or "").strip()
            scope = str(block.get("scope", "") or "").strip()
            if block_type == "markdown":
                text_md = str(block.get("text_md", "") or "").strip()
                if not text_md:
                    continue
                heading = heading_map.get(scope)
                parts.append((heading + "\n" + text_md) if heading else text_md)
                continue
            if block_type == "image":
                display_ref = str(block.get("display_ref", "") or "").strip()
                storage_key = str(block.get("storage_key", "") or "").strip()
                asset_role = str(block.get("asset_role", scope or "image") or "image")
                image_lines: list[str] = []
                if display_ref:
                    image_lines.append(f"![{asset_role}]({display_ref})")
                if storage_key:
                    image_lines.append(f"`storage_key: {storage_key}`")
                if image_lines:
                    parts.append("\n".join(image_lines))
        return "\n\n".join(parts).strip()

    stem_md = str(qvs.get("legacy_stem_md", "") or "").strip()
    answer_md = str(qvs.get("answer_md", "") or fallback_record.get("answer_text_md", "")).strip()
    analysis_md = str(qvs.get("analysis_md", "") or fallback_record.get("analysis_text_md", "")).strip()
    stem_assets = [a for a in fallback_record.get("assets", []) if str(a.get("placement", "")) == "after_stem"]
    analysis_assets = [a for a in fallback_record.get("assets", []) if str(a.get("placement", "")) == "after_analysis"]
    if stem_md:
        parts.append("## 题干\n" + stem_md)
    for asset in stem_assets:
        parts.append(
            "\n".join(
                [
                    f"![{asset.get('role', asset.get('asset_role', 'image'))}]({asset['display_ref']})",
                    f"`storage_key: {asset['storage_key']}`",
                ]
            )
        )
    if answer_md:
        parts.append("## 答案\n" + answer_md)
    if analysis_md:
        parts.append("## 解析\n" + analysis_md)
    for asset in analysis_assets:
        parts.append(
            "\n".join(
                [
                    f"![{asset.get('role', asset.get('asset_role', 'image'))}]({asset['display_ref']})",
                    f"`storage_key: {asset['storage_key']}`",
                ]
            )
        )
    return "\n\n".join(parts).strip()


def _asset_sort_key(asset: dict[str, Any]) -> tuple[int, int]:
    bbox = asset.get("bbox_json", {}) if isinstance(asset.get("bbox_json"), dict) else {}
    return int(bbox.get("y", 0) or 0), int(bbox.get("x", 0) or 0)


def _split_stem_for_inline_images(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    if not value:
        return "", ""
    match = re.search(r"\n[（(]1[）)]", value)
    if not match:
        return value, ""
    split_at = match.start() + 1
    return value[:split_at].rstrip(), value[split_at:].lstrip()


def _split_numbered_sections(text: str) -> tuple[str, list[str]]:
    value = str(text or "").strip()
    if not value:
        return "", []
    matches = list(re.finditer(r"(?:^|\n)([（(]\d+[）)])", value))
    if not matches:
        return value, []
    first = matches[0]
    intro = value[: first.start()].rstrip()
    sections: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start() + (1 if value[match.start()] == "\n" else 0)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(value)
        chunk = value[start:end].strip()
        if chunk:
            sections.append(chunk)
    return intro, sections


def build_display_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    stem_assets = sorted(
        [a for a in record["assets"] if a["placement"] == "after_stem"],
        key=_asset_sort_key,
    )
    stem_intro, stem_rest = _split_stem_for_inline_images(record["stem_text_md"])
    if stem_intro:
        blocks.append({"type": "markdown", "field": "stem", "content": stem_intro})
    for asset in stem_assets:
        blocks.append({"type": "image", "field": "stem", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
    if stem_rest:
        blocks.append({"type": "markdown", "field": "stem", "content": stem_rest})
    elif not stem_intro and record["stem_text_md"].strip():
        blocks.append({"type": "markdown", "field": "stem", "content": record["stem_text_md"]})

    if record["answer_text_md"].strip():
        blocks.append({"type": "markdown", "field": "answer", "content": record["answer_text_md"]})

    analysis_assets = sorted(
        [a for a in record["assets"] if a["placement"] == "after_analysis"],
        key=_asset_sort_key,
    )
    analysis_intro, analysis_sections = _split_numbered_sections(record["analysis_text_md"])
    if analysis_assets and analysis_sections:
        if analysis_intro:
            blocks.append({"type": "markdown", "field": "analysis", "content": analysis_intro})
        for idx, section in enumerate(analysis_sections):
            blocks.append({"type": "markdown", "field": "analysis", "content": section})
            if idx < len(analysis_assets):
                asset = analysis_assets[idx]
                blocks.append({"type": "image", "field": "analysis", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
        for asset in analysis_assets[len(analysis_sections):]:
            blocks.append({"type": "image", "field": "analysis", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
    else:
        if record["analysis_text_md"].strip():
            blocks.append({"type": "markdown", "field": "analysis", "content": record["analysis_text_md"]})
        for asset in analysis_assets:
            blocks.append({"type": "image", "field": "analysis", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
    return blocks


def build_records(
    source_json: Path,
    visual_results: Path | None,
    out_dir: Path,
    include_debug_paths: bool = False,
) -> list[dict[str, Any]]:
    questions = load_split_questions(source_json)
    visual_by_qid = load_visual_results(visual_results)
    base_dir = source_json.parent
    records: list[dict[str, Any]] = []

    for index, question in enumerate(questions, start=1):
        question_id = str(question.get("question_id", "") or f"q_{index:03d}").strip()
        visual = visual_by_qid.get(question_id, {})
        assets: list[dict[str, Any]] = []
        missing_assets: list[dict[str, str]] = []

        for field, placement_field, role in IMAGE_FIELDS:
            raw = str(visual.get(field) or question.get(field) or "").strip()
            if not raw:
                continue
            source_path = resolve_path(raw, base_dir)
            if not source_path.exists():
                missing_assets.append({"field": field, "path": str(source_path)})
                continue
            placement = "evidence_only"
            assets.append(copy_asset(source_path, out_dir, question_id, role, placement, include_debug_paths))

        staged_assets = [dict(item) for item in (question.get("staged_visual_assets", []) or []) if isinstance(item, dict)]
        materialized_staged_assets = [
            materialize_staged_asset(item, question, base_dir, out_dir, include_debug_paths=include_debug_paths)
            for item in staged_assets
        ]
        deduped_staged_assets, removed_duplicate_assets = dedupe_materialized_assets(materialized_staged_assets, out_dir)
        all_assets = assets + deduped_staged_assets

        record = {
            "question_id": question_id,
            "question_uid": str(question.get("question_uid", "") or question_id),
            "checkpoint": str(question.get("checkpoint", "") or ""),
            "component_label": str(question.get("component_label", "") or ""),
            "local_number": str(question.get("local_number", "") or ""),
            "visual_pages": question.get("visual_pages", []),
            "stem_text_md": pick_text(question, visual, "stem_text", "stem_text_md"),
            "answer_text_md": pick_text(question, visual, "answer_text", "answer_text_md"),
            "analysis_text_md": pick_text(question, visual, "analysis_text", "analysis_text_md"),
            "stem_requires_image": pick_bool(question, visual, "stem_requires_image"),
            "analysis_requires_image": pick_bool(question, visual, "analysis_requires_image"),
            "assets": all_assets,
            "missing_assets": missing_assets,
            "removed_duplicate_assets": removed_duplicate_assets,
        }
        if include_debug_paths:
            record["debug_source_refs"] = {
                "source_json": str(source_json.resolve()),
                "visual_results": str(visual_results.resolve()) if visual_results else "",
                "source_question_image": str(question.get("question_image", "") or ""),
                "source_stem_image": str(question.get("stem_image", "") or ""),
                "source_analysis_image": str(question.get("analysis_image", "") or ""),
            }
        qvs, merged_source_refs_json = _build_qvs(record, question, visual, all_assets)
        record["question_visual_structure"] = qvs
        record["merged_source_refs_json"] = merged_source_refs_json
        record["display_blocks"] = build_display_blocks(record)
        record["display_markdown"] = build_qvs_display_markdown(qvs, record) or build_markdown(record)
        records.append(record)
    return records


def render_md(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = re.sub(r"^## (.+)$", r"<h4>\1</h4>", escaped, flags=re.MULTILINE)
    return escaped.replace("\n", "<br>")


def asset_url(asset: dict[str, Any]) -> str:
    return html.escape(asset["storage_key"])


def render_text_block(text: str) -> str:
    body = render_md(text)
    return f"<div class='md'>{body}</div>" if body else ""


def render_display_blocks_html(record: dict[str, Any]) -> str:
    blocks = [item for item in (record.get("display_blocks", []) or []) if isinstance(item, dict)]
    assets_by_id = {
        str(asset.get("asset_id", "") or ""): asset
        for asset in (record.get("assets", []) or [])
        if isinstance(asset, dict)
    }
    if not blocks:
        return render_text_block(str(record.get("display_markdown", "") or ""))

    heading_map = {
        "stem": "题干",
        "answer": "答案",
        "analysis": "解析",
        "handwriting": "手写",
        "stem_image": "题干图片",
        "analysis_image": "解析图片",
    }
    parts: list[str] = []
    for block in blocks:
        block_type = str(block.get("type", "") or "").strip()
        field = str(block.get("field", "") or "").strip()
        if block_type == "markdown":
            content = str(block.get("content", "") or "").strip()
            if not content:
                continue
            title = heading_map.get(field, field or "内容")
            parts.append(f"<h4>{html.escape(title)}</h4>")
            parts.append(render_text_block(content))
            continue
        if block_type == "image":
            asset_id = str(block.get("asset_id", "") or "").strip()
            asset = assets_by_id.get(asset_id)
            if not asset:
                continue
            title = heading_map.get(field, field or str(asset.get("asset_role", "image") or "image"))
            parts.append(f"<h4>{html.escape(title)}</h4>")
            parts.append(
                "<figure>"
                f"<img src='{asset_url(asset)}' alt='{html.escape(asset_id)}'>"
                f"<figcaption>{html.escape(str(asset.get('asset_role', 'image')))} · {html.escape(str(asset.get('display_ref', '')))}</figcaption>"
                "</figure>"
            )
    return "".join(parts)


def render_display_blocks_html_v2(record: dict[str, Any]) -> str:
    blocks = [item for item in (record.get("display_blocks", []) or []) if isinstance(item, dict)]
    assets_by_id = {
        str(asset.get("asset_id", "") or ""): asset
        for asset in (record.get("assets", []) or [])
        if isinstance(asset, dict)
    }
    if not blocks:
        return render_text_block(str(record.get("display_markdown", "") or ""))

    heading_map = {
        "stem": "题干",
        "answer": "答案",
        "analysis": "解析",
        "handwriting": "手写",
    }
    parts: list[str] = []
    seen_fields: set[str] = set()
    index = 0
    while index < len(blocks):
        block = blocks[index]
        block_type = str(block.get("type", "") or "").strip()
        field = str(block.get("field", "") or "").strip()

        if field and field not in seen_fields:
            title = heading_map.get(field, field or "内容")
            parts.append(f"<h4>{html.escape(title)}</h4>")
            seen_fields.add(field)

        if block_type == "markdown":
            content = str(block.get("content", "") or "").strip()
            if content:
                parts.append(render_text_block(content))
            index += 1
            continue

        if block_type == "image":
            cards: list[str] = []
            while index < len(blocks):
                image_block = blocks[index]
                if str(image_block.get("type", "") or "").strip() != "image" or str(image_block.get("field", "") or "").strip() != field:
                    break
                asset_id = str(image_block.get("asset_id", "") or "").strip()
                asset = assets_by_id.get(asset_id)
                if asset:
                    cards.append(
                        "<figure>"
                        f"<img src='{asset_url(asset)}' alt='{html.escape(asset_id)}'>"
                        f"<figcaption>{html.escape(str(asset.get('asset_role', 'image')))} 路 {html.escape(str(asset.get('display_ref', '')))}</figcaption>"
                        "</figure>"
                    )
                index += 1
            if cards:
                parts.append(f"<div class='image-row'>{''.join(cards)}</div>")
            continue

        index += 1

    return "".join(parts)


def write_html(out_path: Path, payload: dict[str, Any]) -> None:
    rows: list[str] = []
    for record in payload["questions"]:
        evidence_assets = [a for a in record["assets"] if str(a.get("placement", "")) == "evidence_only"]
        stem_assets = [a for a in record["assets"] if str(a.get("placement", "")) == "after_stem"]
        analysis_assets = [a for a in record["assets"] if str(a.get("placement", "")) == "after_analysis"]
        option_assets = [a for a in record["assets"] if a.get("placement_scope") == "option_inline"]
        asset_badges = " ".join(
            f"<span class='badge'>{html.escape(str(a.get('asset_role', a.get('role', ''))))}: {html.escape(str(a.get('display_ref', '')))}</span>"
            for a in record["assets"]
        )
        missing = " ".join(
            f"<span class='badge warn'>{html.escape(m['field'])} missing</span>"
            for m in record["missing_assets"]
        )

        def image_cards(assets: list[dict[str, Any]]) -> str:
            cards = []
            for asset in assets:
                asset.setdefault("role", str(asset.get("asset_role", "") or ""))
                asset.setdefault("display_ref", str(asset.get("asset_id", "") or ""))
                cards.append(
                    "<figure>"
                    f"<img src='{asset_url(asset)}' alt='{html.escape(asset['asset_id'])}'>"
                    f"<figcaption>{html.escape(asset['role'])} · {html.escape(asset['display_ref'])}</figcaption>"
                    "</figure>"
                )
            return "".join(cards)

        review_parts: list[str] = []
        if str(record.get("stem_text_md", "") or "").strip():
            review_parts.append("<h4>题干</h4>")
            review_parts.append(f"<div class='md'>{render_md(record['stem_text_md'])}</div>")
        if stem_assets or option_assets:
            review_parts.append(f"<div class='image-row'>{image_cards(stem_assets + option_assets)}</div>")
        if str(record.get("answer_text_md", "") or "").strip():
            review_parts.append("<h4>答案</h4>")
            review_parts.append(f"<div class='md'>{render_md(record['answer_text_md'])}</div>")
        if str(record.get("analysis_text_md", "") or "").strip():
            review_parts.append("<h4>解析</h4>")
            review_parts.append(f"<div class='md'>{render_md(record['analysis_text_md'])}</div>")
        if analysis_assets:
            review_parts.append(f"<div class='image-row'>{image_cards(analysis_assets)}</div>")

        rows.append(
            "<section class='card'>"
            f"<h2>{html.escape(record['question_id'])} <small>{html.escape(record['component_label'])} Q{html.escape(record['local_number'])}</small></h2>"
            f"<div class='badges'>{asset_badges}{missing}</div>"
            "<div class='grid'>"
            "<div>"
            "<h3>落库结构版</h3>"
            f"{render_display_blocks_html_v2(record)}"
            "</div>"
            "<div>"
            "<h3>审核复写版</h3>"
            f"{''.join(review_parts)}"
            "</div>"
            "<div>"
            "<h3>原始证据图</h3>"
            f"{image_cards(evidence_assets)}"
            "</div>"
            "</div>"
            "</section>"
        )

    body = "\n".join(rows)
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>题目图片资产化审核</title>
  <style>
    body {{ margin: 0; background: #f6f7fb; color: #182230; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    header {{ padding: 24px 32px; background: #172033; color: white; }}
    header h1 {{ margin: 0 0 8px; font-size: 24px; }}
    header p {{ margin: 0; opacity: .82; }}
    .wrap {{ padding: 24px; }}
    .card {{ background: white; border: 1px solid #e3e8f2; border-radius: 16px; padding: 18px; margin: 0 0 18px; box-shadow: 0 8px 24px rgba(18, 31, 55, .06); }}
    h2 {{ margin: 0 0 10px; color: #0f1d2e; }}
    h2 small {{ color: #667085; font-weight: 500; margin-left: 8px; }}
    h3 {{ margin: 14px 0 10px; font-size: 16px; color: #344054; }}
    h4 {{ margin: 12px 0 6px; color: #101828; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(280px, .8fr); gap: 18px; align-items: start; }}
    .md {{ background: #fbfcff; border: 1px solid #e7edf8; border-radius: 12px; padding: 14px; line-height: 1.75; white-space: normal; }}
    .badges {{ margin: 8px 0 12px; }}
    .badge {{ display: inline-block; margin: 0 6px 6px 0; padding: 4px 8px; border-radius: 999px; background: #eef4ff; color: #175cd3; font-size: 12px; }}
    .badge.warn {{ background: #fff1f3; color: #c01048; }}
    .image-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 12px; }}
    figure {{ margin: 0 0 12px; padding: 10px; border: 1px solid #e7edf8; border-radius: 12px; background: #fff; }}
    img {{ max-width: 100%; height: auto; display: block; border-radius: 8px; background: #fff; }}
    figcaption {{ margin-top: 8px; color: #667085; font-size: 12px; word-break: break-all; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .wrap {{ padding: 14px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>题目图片资产化审核</h1>
    <p>生成时间：{html.escape(payload["generated_at"])} · 题目数：{payload["question_count"]} · 图片资产：{payload["asset_count"]}</p>
  </header>
  <main class="wrap">
    {body}
  </main>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy question images into a portable asset bundle and emit DB-friendly refs.")
    parser.add_argument("--source-json", required=True, help="teacher_visual_question_transcription_v0.1.json")
    parser.add_argument("--visual-results", default="", help="Optional visual_transcription_results.json or visual_transcription_compact.json")
    parser.add_argument("--out-dir", default="", help="Output asset bundle directory. Defaults beside source json.")
    parser.add_argument("--include-debug-paths", action="store_true", help="Include local absolute paths under debug fields for local audit only.")
    args = parser.parse_args()

    source_json = Path(args.source_json).expanduser().resolve()
    if not source_json.exists():
        raise SystemExit(f"source_json_not_found: {source_json}")
    visual_results = Path(args.visual_results).expanduser().resolve() if args.visual_results.strip() else None
    if visual_results is not None and not visual_results.exists():
        raise SystemExit(f"visual_results_not_found: {visual_results}")
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir.strip() else source_json.parent / "question_asset_bundle_v0.1"
    out_dir.mkdir(parents=True, exist_ok=True)

    records = build_records(source_json, visual_results, out_dir, include_debug_paths=args.include_debug_paths)
    asset_count = sum(len(record["assets"]) for record in records)
    payload = {
        "schema_version": "question_asset_bundle_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_json": str(source_json),
        "visual_results": str(visual_results) if visual_results else "",
        "path_policy": {
            "deploy_fields_are_relative": True,
            "asset_storage_key_base": "bundle_root",
            "debug_absolute_paths_included": bool(args.include_debug_paths),
        },
        "question_count": len(records),
        "asset_count": asset_count,
        "questions": records,
    }
    write_json(out_dir / "question_asset_manifest_v0.1.json", payload)
    write_html(out_dir / "question_asset_review.html", payload)

    summary = {
        "out_dir": str(out_dir),
        "manifest": str(out_dir / "question_asset_manifest_v0.1.json"),
        "html": str(out_dir / "question_asset_review.html"),
        "question_count": len(records),
        "asset_count": asset_count,
        "questions_with_stem_image": sum(any(a["role"] == "stem" for a in r["assets"]) for r in records),
        "questions_with_analysis_image": sum(any(a["role"] == "analysis" for a in r["assets"]) for r in records),
        "questions_with_option_assets": sum(any(a.get("asset_role") == "option" for a in r["assets"]) for r in records),
        "questions_with_missing_assets": sum(bool(r["missing_assets"]) for r in records),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
