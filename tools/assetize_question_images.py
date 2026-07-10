from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from compose_legacy_stem_md import compose_legacy_stem_md
from question_visual_structure_contract import SCHEMA_VERSION, normalize_review_flags
from source_refs_json_merge import merge_source_refs_json

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
HTML_ASSETS_CACHE = WORKSPACE_ROOT / "runtime" / "html_assets_cache"
# Source container images are evidence only. Formal image assets must come from
# staged_visual_assets so the runtime doesn't confuse whole long crops with
# semantic in-question figures.
IMAGE_FIELDS = (
    ("question_image", "evidence_only", "question_source"),
    ("stem_image", "evidence_only", "stem_source"),
    ("analysis_image", "evidence_only", "analysis_source"),
)

EVIDENCE_ROLE_PRIORITY = {
    "question_source": 3,
    "stem_source": 2,
    "analysis_source": 1,
}

VISUAL_INSERT_FIGURE_REF_RE = re.compile(
    r"(?:如图\s*(?:\d{1,2}|[一二三四五六七八九十]+|备用图)?|图\s*(?:\d{1,2}|[一二三四五六七八九十]+|备用图))[\s,，:：]*"
)
VISUAL_INSERT_SUBQUESTION_RE = re.compile(r"(?:（\d+）|\(\d+\)|[①②③④⑤⑥⑦⑧⑨⑩])")


def safe_slug(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(text or "").strip())
    value = value.strip("._-")
    return value[:80].rstrip("._-") or "question"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def stage_html_assets(bundle_dir: Path) -> dict[str, str]:
    asset_dir = bundle_dir / "_html_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    wanted = {
        "katex_css": "katex_css.css",
        "katex_js": "katex_js.js",
        "auto_render_js": "auto_render_js.js",
    }
    refs: dict[str, str] = {}
    for key, filename in wanted.items():
        src = HTML_ASSETS_CACHE / filename
        dst = asset_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            refs[key] = f"_html_assets/{filename}"
    return refs


def resolve_path(raw: str, base_dir: Path) -> Path:
    candidate = Path(str(raw or "").strip())
    if candidate.is_absolute():
        return candidate
    for root in (base_dir, WORKSPACE_ROOT, Path.cwd()):
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
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
    try:
        with Image.open(source_path) as image:
            review_key, review_meta = _write_review_display_copy(
                image.convert("RGB"),
                out_dir=out_dir,
                storage_key=rel_path.as_posix(),
            )
        if review_key and review_meta:
            asset["review_storage_key"] = review_key
            asset["review_render"] = review_meta
            asset["delivery_storage_key"] = review_key
            asset["delivery_render"] = review_meta
    except Exception:
        pass
    return asset


def copy_bridge_fragment_asset(
    fragment: dict[str, Any],
    source_path: Path,
    out_dir: Path,
    question_id: str,
    ordinal: int,
    include_debug_paths: bool = False,
) -> dict[str, Any]:
    role = "question_fragment_evidence"
    fragment_id = str(fragment.get("fragment_id", "") or f"{question_id}_fragment_{ordinal:02d}")
    asset_id = f"{safe_slug(question_id)}__fragment_{ordinal:02d}"
    rel_path = Path("assets") / safe_slug(question_id) / "fragments" / f"fragment_{ordinal:02d}{image_extension(source_path)}"
    target_path = out_dir / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    asset = {
        "asset_id": asset_id,
        "fragment_id": fragment_id,
        "role": role,
        "asset_role": role,
        "placement": "evidence_only",
        "placement_scope": "evidence_only",
        "attach_status": "not_attached_unassigned",
        "option_key": None,
        "display_ref": f"asset://{asset_id}",
        "storage_key": rel_path.as_posix(),
        "mime_type": "image/png" if rel_path.suffix.lower() == ".png" else f"image/{rel_path.suffix.lower().lstrip('.')}",
        "materialized": True,
        "file_status": "materialized",
        "review_flags": normalize_review_flags(["semantic_v03_bridge_fragment_evidence"]),
        "page": fragment.get("page"),
        "bbox_px": fragment.get("bbox_px", []),
        "coordinate_space": str(fragment.get("coordinate_space", "") or "page_master_px"),
        "source_image_role": str(fragment.get("source_image_role", "") or "source_page"),
        "source_block_ids": fragment.get("source_block_ids", []),
        "fragment_role": str(fragment.get("role", "") or "fragment"),
    }
    if include_debug_paths:
        asset["debug"] = {
            "local_path": str(target_path.resolve()),
            "source_path": str(source_path.resolve()),
        }
    try:
        with Image.open(source_path) as image:
            review_key, review_meta = _write_review_display_copy(
                image.convert("RGB"),
                out_dir=out_dir,
                storage_key=rel_path.as_posix(),
            )
        if review_key and review_meta:
            asset["review_storage_key"] = review_key
            asset["review_render"] = review_meta
            asset["delivery_storage_key"] = review_key
            asset["delivery_render"] = review_meta
    except Exception:
        pass
    return asset


def copy_bridge_fragment_assets(
    question: dict[str, Any],
    base_dir: Path,
    out_dir: Path,
    question_id: str,
    include_debug_paths: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    copied: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    fragments = question.get("bridge_fragments", []) if isinstance(question.get("bridge_fragments"), list) else []
    for ordinal, fragment in enumerate([item for item in fragments if isinstance(item, dict)], start=1):
        raw = str(fragment.get("fragment_image", "") or fragment.get("asset_path", "") or "").strip()
        if not raw:
            missing.append({"field": "bridge_fragments", "path": "", "fragment_id": str(fragment.get("fragment_id", "") or "")})
            continue
        source_path = resolve_path(raw, base_dir)
        if not source_path.exists():
            missing.append({"field": "bridge_fragments", "path": str(source_path), "fragment_id": str(fragment.get("fragment_id", "") or "")})
            continue
        copied.append(
            copy_bridge_fragment_asset(
                fragment,
                source_path,
                out_dir,
                question_id,
                ordinal,
                include_debug_paths=include_debug_paths,
            )
        )
    return copied, missing


def _pick_single_evidence_asset(
    question: dict[str, Any],
    visual: dict[str, Any],
    base_dir: Path,
    out_dir: Path,
    question_id: str,
    include_debug_paths: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    missing_assets: list[dict[str, str]] = []
    candidates: list[tuple[str, str, Path]] = []
    for field, _placement_field, role in IMAGE_FIELDS:
        raw = str(visual.get(field) or question.get(field) or "").strip()
        if not raw:
            continue
        source_path = resolve_path(raw, base_dir)
        if not source_path.exists():
            missing_assets.append({"field": field, "path": str(source_path)})
            continue
        candidates.append((field, role, source_path))

    if not candidates:
        return [], missing_assets, {}

    field, role, source_path = candidates[0]
    selected_asset = copy_asset(source_path, out_dir, question_id, role, "evidence_only", include_debug_paths)
    selected_asset["evidence_source_field"] = field
    selected_meta = {
        "selected_evidence_asset_id": str(selected_asset.get("asset_id", "") or ""),
        "selected_evidence_role": role,
        "selected_evidence_source_field": field,
        "candidate_count": len(candidates),
    }
    return [selected_asset], missing_assets, selected_meta


def _resolve_bbox_source(question: dict[str, Any], bbox_space: str, base_dir: Path) -> Path | None:
    source_key = "stem_image" if bbox_space == "stem_image" else "question_image"
    if bbox_space == "analysis_image":
        source_key = "analysis_image"
    raw = str(question.get(source_key, "") or "").strip()
    if not raw:
        return None
    return resolve_path(raw, base_dir)


def _is_formal_export_asset(asset: dict[str, Any]) -> bool:
    placement = str(asset.get("placement", asset.get("placement_scope", "")) or "").strip()
    return placement != "evidence_only"


def _preferred_source_roles(source_role: str) -> list[str]:
    normalized = str(source_role or "").strip()
    if normalized == "stem_image":
        return ["stem_source", "question_source"]
    if normalized == "analysis_image":
        return ["analysis_source", "question_source"]
    return ["question_source", "stem_source", "analysis_source"]


def _backfill_formal_asset_source_refs(all_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_assets = [asset for asset in all_assets if not _is_formal_export_asset(asset)]
    if not evidence_assets:
        return all_assets

    by_source_field: dict[str, dict[str, Any]] = {}
    by_asset_role: dict[str, dict[str, Any]] = {}
    for asset in evidence_assets:
        source_field = str(asset.get("evidence_source_field", "") or "").strip()
        if source_field and source_field not in by_source_field:
            by_source_field[source_field] = asset
        asset_role = str(asset.get("asset_role", asset.get("role", "")) or "").strip()
        if asset_role and asset_role not in by_asset_role:
            by_asset_role[asset_role] = asset

    for asset in all_assets:
        if not _is_formal_export_asset(asset):
            continue
        if str(asset.get("source_image_asset_id", "") or "").strip() or str(asset.get("source_image_storage_key", "") or "").strip():
            continue
        source_role = str(asset.get("source_image_role", "") or asset.get("bbox_space", "") or "").strip()
        source_asset = by_source_field.get(source_role)
        if source_asset is None:
            for candidate_role in _preferred_source_roles(source_role):
                if candidate_role in by_asset_role:
                    source_asset = by_asset_role[candidate_role]
                    break
        if source_asset is None and len(evidence_assets) == 1:
            source_asset = evidence_assets[0]
        if source_asset is None:
            continue
        asset["source_image_asset_id"] = str(
            asset.get("source_image_asset_id", "") or source_asset.get("asset_id", "") or ""
        ).strip()
        asset["source_image_storage_key"] = str(
            asset.get("source_image_storage_key", "") or source_asset.get("storage_key", "") or ""
        ).strip()
    return all_assets


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


def _foreground_bounds(image: Image.Image, threshold: int = 220) -> tuple[int, int, int, int] | None:
    gray = image.convert("L")
    pixels = gray.load()
    left = right = top = bottom = None
    for y in range(gray.height):
        for x in range(gray.width):
            if pixels[x, y] < threshold:
                if left is None or x < left:
                    left = x
                if right is None or x > right:
                    right = x
                if top is None or y < top:
                    top = y
                if bottom is None or y > bottom:
                    bottom = y
    if None in {left, right, top, bottom}:
        return None
    return int(left), int(top), int(right), int(bottom)


def _band_dark_ratio(image: Image.Image, *, top: bool, band_px: int = 14, threshold: int = 220) -> float:
    gray = image.convert("L")
    if gray.width <= 0 or gray.height <= 0:
        return 0.0
    band_px = max(1, min(band_px, gray.height))
    y_start = 0 if top else gray.height - band_px
    y_end = min(y_start + band_px, gray.height)
    pixels = gray.load()
    dark = 0
    total = max((y_end - y_start) * gray.width, 1)
    for y in range(y_start, y_end):
        for x in range(gray.width):
            if pixels[x, y] < threshold:
                dark += 1
    return dark / total


def _audit_materialized_bbox(
    asset: dict[str, Any],
    *,
    source_image: Image.Image,
    crop: Image.Image,
    bbox: dict[str, Any],
) -> dict[str, Any]:
    x = max(int(bbox.get("x", 0) or 0), 0)
    y = max(int(bbox.get("y", 0) or 0), 0)
    w = max(int(bbox.get("w", 0) or 0), 0)
    h = max(int(bbox.get("h", 0) or 0), 0)
    source_w, source_h = source_image.size
    fg = _foreground_bounds(crop)
    boundary_margin = {
        "left": None,
        "top": None,
        "right": None,
        "bottom": None,
    }
    clip_risk = {
        "left": False,
        "top": False,
        "right": False,
        "bottom": False,
    }
    if fg is not None:
        fg_left, fg_top, fg_right, fg_bottom = fg
        boundary_margin = {
            "left": int(fg_left),
            "top": int(fg_top),
            "right": int(crop.width - fg_right - 1),
            "bottom": int(crop.height - fg_bottom - 1),
        }
        clip_risk = {
            side: int(boundary_margin[side] or 0) <= 1
            for side in ("left", "top", "right", "bottom")
        }

    source_edge_touch = {
        "left": x <= 1,
        "top": y <= 1,
        "right": x + w >= source_w - 1,
        "bottom": y + h >= source_h - 1,
    }
    top_band_ratio = round(_band_dark_ratio(crop, top=True), 4)
    bottom_band_ratio = round(_band_dark_ratio(crop, top=False), 4)
    text_band_risk = {
        "top": top_band_ratio >= 0.18 and bool(clip_risk["top"]),
        "bottom": bottom_band_ratio >= 0.18 and bool(clip_risk["bottom"]),
    }
    suspect_reasons: list[str] = []
    for side in ("left", "top", "right", "bottom"):
        if clip_risk[side]:
            suspect_reasons.append(f"{side}_clip_risk")
        if source_edge_touch[side]:
            suspect_reasons.append(f"{side}_touches_source_edge")
    for side in ("top", "bottom"):
        if text_band_risk[side]:
            suspect_reasons.append(f"{side}_text_band_risk")

    detector_source = str(asset.get("detector_source", "") or "").strip()
    if not detector_source or detector_source == "unknown":
        suspect_reasons.append("detector_source_unknown")

    if crop.width < 24 or crop.height < 24 or fg is None:
        validity = "invalid"
    elif suspect_reasons:
        validity = "suspect"
    else:
        validity = "valid"

    return {
        "validity": validity,
        "detector_source": detector_source or "unknown",
        "source_edge_touch": source_edge_touch,
        "boundary_margin": boundary_margin,
        "clip_risk": clip_risk,
        "text_band_risk": text_band_risk,
        "top_band_dark_ratio": top_band_ratio,
        "bottom_band_dark_ratio": bottom_band_ratio,
        "suspect_reasons": suspect_reasons,
    }


def _average_hash(path: Path, size: int = 8) -> str:
    with Image.open(path) as image:
        gray = image.convert("L").resize((size, size))
        pixels = list(gray.getdata())
    mean = sum(pixels) / max(len(pixels), 1)
    bits = "".join("1" if px >= mean else "0" for px in pixels)
    return f"{int(bits, 2):016x}"


def _review_scale_for_image(image: Image.Image) -> float:
    long_edge = max(int(image.width or 0), int(image.height or 0))
    if long_edge <= 0:
        return 1.0
    target_long_edge = 960
    scale = target_long_edge / long_edge
    return max(1.0, min(4.0, scale))


def _dense_projection_bands(values: list[float], *, threshold: float, min_len: int = 2, gap_merge: int = 2) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for idx, value in enumerate(values):
        if value >= threshold:
            if start is None:
                start = idx
        elif start is not None:
            if idx - start >= min_len:
                bands.append((start, idx - 1))
            start = None
    if start is not None and len(values) - start >= min_len:
        bands.append((start, len(values) - 1))

    if not bands:
        return []

    merged = [bands[0]]
    for start, end in bands[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end - 1 <= gap_merge:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _clean_delivery_vertical_edges(image: Image.Image) -> tuple[Image.Image, dict[str, Any] | None]:
    if image.height < 80 or image.width < 80:
        return image, None

    gray = image.convert("L")
    threshold = 220
    row_ratios: list[float] = []
    for y in range(gray.height):
        dark = 0
        for x in range(gray.width):
            if gray.getpixel((x, y)) < threshold:
                dark += 1
        row_ratios.append(dark / max(gray.width, 1))

    bands = _dense_projection_bands(
        row_ratios,
        threshold=0.012,
        min_len=max(2, int(gray.height * 0.015)),
        gap_merge=max(2, int(gray.height * 0.01)),
    )
    if len(bands) < 2:
        return image, None

    pad = max(2, int(gray.height * 0.01))
    edge_band_max = max(10, int(gray.height * 0.08))
    gap_min = max(4, int(gray.height * 0.025))
    top_trim = 0
    bottom_trim = gray.height

    first_start, first_end = bands[0]
    second_start, second_end = bands[1]
    first_len = first_end - first_start + 1
    second_len = second_end - second_start + 1
    first_gap = second_start - first_end - 1
    first_mean = sum(row_ratios[first_start:first_end + 1]) / max(first_len, 1)
    first_max = max(row_ratios[first_start:first_end + 1])
    if (
        first_start <= 1
        and first_len <= edge_band_max
        and first_gap >= gap_min
        and second_len >= first_len * 2
        and first_mean >= 0.12
        and first_max >= 0.2
    ):
        top_trim = max(0, second_start - pad)

    last_start, last_end = bands[-1]
    prev_start, prev_end = bands[-2]
    last_len = last_end - last_start + 1
    prev_len = prev_end - prev_start + 1
    last_gap = last_start - prev_end - 1
    last_mean = sum(row_ratios[last_start:last_end + 1]) / max(last_len, 1)
    last_max = max(row_ratios[last_start:last_end + 1])
    if (
        last_end >= gray.height - 2
        and last_len <= edge_band_max
        and last_gap >= gap_min
        and prev_len >= last_len * 1.2
        and last_mean >= 0.1
        and last_max >= 0.18
    ):
        bottom_trim = min(gray.height, prev_end + 1 + pad)

    if top_trim <= 0 and bottom_trim >= gray.height:
        return image, None
    if bottom_trim - top_trim < int(gray.height * 0.55):
        return image, None

    cleaned = image.crop((0, top_trim, image.width, bottom_trim))
    return cleaned, {
        "crop_box": [0, top_trim, image.width, bottom_trim],
        "bands": bands,
        "mode": "vertical_edge_clean",
    }


def _write_review_display_copy(
    image: Image.Image,
    *,
    out_dir: Path,
    storage_key: str,
) -> tuple[str | None, dict[str, Any] | None]:
    cleaned_image, clean_meta = _clean_delivery_vertical_edges(image)
    scale = _review_scale_for_image(cleaned_image)
    if scale <= 1.05 and clean_meta is None:
        return None, None

    review_key = (Path("_delivery_assets") / Path(storage_key)).as_posix()
    review_path = out_dir / review_key
    review_path.parent.mkdir(parents=True, exist_ok=True)

    review_width = max(1, int(round(cleaned_image.width * scale)))
    review_height = max(1, int(round(cleaned_image.height * scale)))
    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    review_image = cleaned_image.resize((review_width, review_height), resample=resampling)
    review_image = review_image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=135, threshold=2))

    suffix = review_path.suffix.lower()
    save_kwargs: dict[str, Any] = {}
    if suffix in {".jpg", ".jpeg"}:
        save_kwargs.update({"quality": 95, "subsampling": 0})
    review_image.save(review_path, **save_kwargs)
    meta: dict[str, Any] = {
        "scale": round(scale, 2),
        "width": review_width,
        "height": review_height,
        "target_long_edge": 960,
        "mode": "review_upscale_unsharp",
    }
    if clean_meta:
        meta["edge_clean"] = clean_meta
    return review_key, meta


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
            if str(asset.get("panel_group_id", "") or "").strip() and str(existing_asset.get("panel_group_id", "") or "").strip():
                if str(asset.get("panel_group_id", "") or "").strip() != str(existing_asset.get("panel_group_id", "") or "").strip():
                    continue
            if int(asset.get("panel_subfigure_count", 0) or 0) > 1 or int(existing_asset.get("panel_subfigure_count", 0) or 0) > 1:
                continue
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
    review_key: str | None = None
    review_meta: dict[str, Any] | None = None
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
            bbox_audit = _audit_materialized_bbox(asset, source_image=image, crop=crop, bbox=bbox)
            crop.save(target_path)
            review_key, review_meta = _write_review_display_copy(
                crop,
                out_dir=out_dir,
                storage_key=storage_key,
            )
    except Exception:
        asset["materialized"] = False
        asset["file_status"] = "failed"
        asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + ["asset_materialize_failed"])
        return asset
    asset["materialized"] = True
    asset["file_status"] = "materialized"
    asset["bbox_audit"] = bbox_audit
    audit_flags: list[str] = []
    if bbox_audit.get("validity") == "suspect":
        audit_flags.append("bbox_audit_suspect")
    elif bbox_audit.get("validity") == "invalid":
        audit_flags.append("bbox_audit_invalid")
    if str(asset.get("detector_source", "") or "").strip() in {"", "unknown"}:
        audit_flags.append("detector_source_missing")
    asset["review_flags"] = normalize_review_flags(list(asset.get("review_flags", []) or []) + audit_flags)
    if review_key and review_meta:
        asset["review_storage_key"] = review_key
        asset["review_render"] = review_meta
        asset["delivery_storage_key"] = review_key
        asset["delivery_render"] = review_meta
    if include_debug_paths:
        asset["debug"] = {
            "local_path": str(target_path.resolve()),
            "source_path": str(source_path.resolve()),
        }
    return asset


def _build_qvs(record: dict[str, Any], question: dict[str, Any], visual: dict[str, Any], all_assets: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    base_qvs = visual.get("question_visual_structure", {}) if isinstance(visual.get("question_visual_structure"), dict) else {}
    all_assets = _backfill_formal_asset_source_refs(all_assets)
    runtime_run_id = str(
        base_qvs.get("runtime_run_id", "")
        or question.get("runtime_run_id", "")
        or next(
            (
                asset.get("runtime_run_id")
                for asset in all_assets
                if isinstance(asset, dict) and str(asset.get("runtime_run_id", "") or "").strip()
            ),
            "",
        )
        or ""
    ).strip()
    asset_flags: list[str] = []
    for asset in all_assets:
        asset_flags.extend(asset.get("review_flags", []) or [])
    qvs = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": str(base_qvs.get("generated_by", "assetize_question_images") or "assetize_question_images"),
        "runtime_run_id": runtime_run_id,
        "question_uid": str(base_qvs.get("question_uid", question.get("question_uid", question.get("question_id", ""))) or ""),
        "stem_md": str(base_qvs.get("stem_md", record["stem_text_md"]) or record["stem_text_md"]),
        "answer_md": str(base_qvs.get("answer_md", record["answer_text_md"]) or record["answer_text_md"]),
        "analysis_md": str(base_qvs.get("analysis_md", record["analysis_text_md"]) or record["analysis_text_md"]),
        "legacy_stem_md": str(base_qvs.get("legacy_stem_md", "") or ""),
        "inline_asset_anchor_mode": str(base_qvs.get("inline_asset_anchor_mode", "") or ""),
        "gating": base_qvs.get("gating", question.get("gating_result", {})) if isinstance(base_qvs.get("gating", question.get("gating_result", {})), dict) else {},
        "options": [item for item in (base_qvs.get("options", []) or []) if isinstance(item, dict)],
        "content_blocks": [item for item in (base_qvs.get("content_blocks", []) or []) if isinstance(item, dict)],
        "long_image_anchor_plan": [item for item in (base_qvs.get("long_image_anchor_plan", []) or []) if isinstance(item, dict)],
        "visual_insert_anchor_plan": [item for item in (base_qvs.get("visual_insert_anchor_plan", []) or []) if isinstance(item, dict)],
        "visual_insert_anchor_slots": [item for item in (base_qvs.get("visual_insert_anchor_slots", []) or []) if isinstance(item, dict)],
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


def build_qvs_display_markdown(
    qvs: dict[str, Any],
    fallback_record: dict[str, Any],
    *,
    include_debug_storage_key: bool = False,
) -> str:
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
                if include_debug_storage_key and storage_key:
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
        image_lines = [f"![{asset.get('role', asset.get('asset_role', 'image'))}]({asset['display_ref']})"]
        if include_debug_storage_key:
            image_lines.append(f"`storage_key: {asset['storage_key']}`")
        parts.append("\n".join(image_lines))
    if answer_md:
        parts.append("## 答案\n" + answer_md)
    if analysis_md:
        parts.append("## 解析\n" + analysis_md)
    for asset in analysis_assets:
        image_lines = [f"![{asset.get('role', asset.get('asset_role', 'image'))}]({asset['display_ref']})"]
        if include_debug_storage_key:
            image_lines.append(f"`storage_key: {asset['storage_key']}`")
        parts.append("\n".join(image_lines))
    return "\n\n".join(parts).strip()


def _asset_sort_key(asset: dict[str, Any]) -> tuple[int, int]:
    bbox = asset.get("bbox_json", {}) if isinstance(asset.get("bbox_json"), dict) else {}
    y = int(bbox.get("y", 0) or 0)
    x = int(bbox.get("x", 0) or 0)
    return y // 160, x, y


def assign_external_labels(assets: list[dict[str, Any]]) -> None:
    if str(os.environ.get("ASSETIZE_ENABLE_EXTERNAL_LABELS", "") or "").strip() != "1":
        for asset in assets:
            asset.pop("external_label_kind", None)
            asset.pop("external_label_text", None)
        return
    for placement, role in (("after_stem", "stem"), ("after_analysis", "analysis")):
        figure_assets = sorted(
            [
                asset
                for asset in assets
                if str(asset.get("placement", asset.get("placement_scope", "")) or "") == placement
                and str(asset.get("asset_role", asset.get("role", "")) or "") == role
            ],
            key=_asset_sort_key,
        )
        for index, asset in enumerate(figure_assets, start=1):
            asset["external_label_kind"] = "figure_index"
            asset["external_label_text"] = f"图{index}"

    for asset in assets:
        option_key = str(asset.get("option_key", "") or "").strip().upper()
        if option_key and str(asset.get("placement_scope", "") or "") == "option_inline":
            asset["external_label_kind"] = "option_key"
            asset["external_label_text"] = option_key


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


def _split_section_for_inline_image(section: str) -> tuple[str, str]:
    value = str(section or "").strip()
    if not value:
        return "", ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) <= 2:
        return value, ""
    split_idx = min(max(2, len(lines) // 4), 5)
    intro = "\n".join(lines[:split_idx]).strip()
    rest = "\n".join(lines[split_idx:]).strip()
    return intro, rest


def _split_stem_for_inline_images_v2(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    if not value:
        return "", ""
    match = re.search(r"(?:^|\n)\s*(?:（|\()1(?:）|\))", value)
    if not match:
        return value, ""
    split_at = match.start() + (1 if value[match.start()] == "\n" else 0)
    return value[:split_at].rstrip(), value[split_at:].lstrip()


def _split_numbered_sections_v2(text: str) -> tuple[str, list[str]]:
    value = str(text or "").strip()
    if not value:
        return "", []
    matches = list(re.finditer(r"(?:（|\()(\d+)(?:）|\))", value))
    if not matches:
        return value, []
    intro = value[: matches[0].start()].rstrip()
    sections: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(value)
        chunk = value[start:end].strip()
        if chunk:
            sections.append(chunk)
    return intro, sections


def _split_stem_for_inline_images_v3(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    if not value:
        return "", ""
    match = re.search(r"(?:(?<=^)|(?<=\n)|(?<=:)|(?<=\uFF1A))\s*(?:\uFF08|\()1(?:\uFF09|\))", value)
    if not match:
        return value, ""
    split_at = match.start() + (1 if value[match.start()] == "\n" else 0)
    return value[:split_at].rstrip(), value[split_at:].lstrip()


def _split_numbered_sections_v3(text: str) -> tuple[str, list[str]]:
    value = str(text or "").strip()
    if not value:
        return "", []
    matches = list(
        re.finditer(
            r"(?:(?<=^)|(?<=\n)|(?<=:)|(?<=\uFF1A))\s*(?:\uFF08|\()(\d+)(?:\uFF09|\))",
            value,
        )
    )
    if not matches:
        return value, []
    intro = value[: matches[0].start()].rstrip()
    sections: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(value)
        chunk = value[start:end].strip()
        if chunk:
            sections.append(chunk)
    return intro, sections


def _split_stem_option_image_labels(text: str, asset_count: int) -> tuple[str, list[str], str]:
    value = str(text or "").strip()
    if asset_count <= 0 or not value:
        return value, [], ""
    lines = value.splitlines()
    option_lines: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        clean = line.strip()
        if re.fullmatch(r"[A-D][\.．、]?", clean):
            option_lines.append((idx, clean if clean.endswith((".", "．", "、")) else f"{clean}."))
    if len(option_lines) != asset_count:
        return value, [], ""
    indexes = [idx for idx, _label in option_lines]
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        return value, [], ""
    prefix = "\n".join(lines[: indexes[0]]).strip()
    suffix = "\n".join(lines[indexes[-1] + 1 :]).strip()
    labels = [label for _idx, label in option_lines]
    return prefix, labels, suffix


def _split_stem_option_image_labels(text: str, asset_count: int) -> tuple[str, list[str], str]:
    value = str(text or "").strip()
    if asset_count <= 0 or not value:
        return value, [], ""
    lines = value.splitlines()
    option_lines: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        clean = line.strip()
        if re.fullmatch(r"[A-D][\.\u3002、]?", clean):
            option_lines.append((idx, f"{clean[0].upper()}."))
    if len(option_lines) != asset_count:
        return value, [], ""
    indexes = [idx for idx, _label in option_lines]
    between_non_empty = [line.strip() for line in lines[indexes[0] : indexes[-1] + 1] if line.strip()]
    labels = [label for _idx, label in option_lines]
    if between_non_empty != labels:
        return value, [], ""
    prefix = "\n".join(lines[: indexes[0]]).strip()
    suffix = "\n".join(lines[indexes[-1] + 1 :]).strip()
    return prefix, labels, suffix


def _assets_by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(asset.get("asset_id", "") or ""): asset
        for asset in (record.get("assets", []) or [])
        if isinstance(asset, dict) and str(asset.get("asset_id", "") or "").strip()
    }


def _selected_scope_asset_ids(record: dict[str, Any], scope: str) -> list[str]:
    selected = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    raw_ids = selected.get(scope, []) if isinstance(selected.get(scope), list) else []
    return [str(item or "").strip() for item in raw_ids if str(item or "").strip()]


def _selected_option_asset_ids_by_key(record: dict[str, Any]) -> dict[str, list[str]]:
    selected = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    raw = selected.get("option_by_key", {}) if isinstance(selected.get("option_by_key"), dict) else {}
    normalized: dict[str, list[str]] = {}
    for key, values in raw.items():
        option_key = str(key or "").strip().upper()
        if not option_key or not isinstance(values, list):
            continue
        normalized[option_key] = [str(item or "").strip() for item in values if str(item or "").strip()]
    return normalized


def _selected_option_assets_by_key(record: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    explicit = _selected_option_asset_ids_by_key(record)
    by_id = _assets_by_id(record)
    if explicit:
        resolved: dict[str, list[dict[str, Any]]] = {}
        for option_key, asset_ids in explicit.items():
            resolved[option_key] = [by_id[item] for item in asset_ids if item in by_id]
        return resolved

    grouped: dict[str, list[dict[str, Any]]] = {}
    option_assets = sorted(
        [
            a
            for a in record.get("assets", [])
            if isinstance(a, dict)
            and str(a.get("placement_scope", "") or a.get("placement", "") or "") == "option_inline"
            and bool(a.get("materialized", False))
            and str(a.get("file_status", "") or "") != "failed"
        ],
        key=lambda asset: (
            {"A": 1, "B": 2, "C": 3, "D": 4}.get(str(asset.get("option_key", "") or "").strip().upper(), 99),
            _asset_sort_key(asset),
        ),
    )
    for asset in option_assets:
        option_key = str(asset.get("option_key", "") or "").strip().upper()
        if not option_key:
            continue
        grouped.setdefault(option_key, []).append(asset)
    return grouped


def _resolve_selected_assets(record: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    selected_ids = _selected_scope_asset_ids(record, scope)
    if selected_ids:
        by_id = _assets_by_id(record)
        return [by_id[item] for item in selected_ids if item in by_id]
    placement_scope = "after_stem" if scope == "stem" else "after_analysis"
    return sorted(
        [
            a
            for a in record["assets"]
            if str(a.get("placement_scope", "") or a.get("placement", "") or "") == placement_scope
            and bool(a.get("materialized", False))
            and str(a.get("file_status", "") or "") != "failed"
        ],
        key=_asset_sort_key,
    )


def _visual_anchor_boundary(text: str, end: int) -> int:
    value = str(text or "")
    index = int(end or 0)
    while index < len(value) and value[index] in " \t\r\n，,。；;：:、)]）】》\"'":
        index += 1
    return index


def _extract_visual_insert_anchor_slots_for_field(field: str, text_md: str) -> list[dict[str, Any]]:
    value = str(text_md or "").strip()
    if not value:
        return []
    raw_slots: list[dict[str, Any]] = []
    for match in VISUAL_INSERT_FIGURE_REF_RE.finditer(value):
        raw_slots.append(
            {
                "slot_type": "figure_ref",
                "start": match.start(),
                "end": _visual_anchor_boundary(value, match.end()),
            }
        )
    for match in VISUAL_INSERT_SUBQUESTION_RE.finditer(value):
        raw_slots.append(
            {
                "slot_type": "subquestion_mark",
                "start": match.start(),
                "end": _visual_anchor_boundary(value, match.end()),
            }
        )
    raw_slots.sort(key=lambda item: (int(item["start"]), -(int(item["end"]) - int(item["start"]))))

    merged: list[dict[str, Any]] = []
    for item in raw_slots:
        start = int(item["start"])
        end = int(item["end"])
        if end <= start:
            continue
        if merged and start < int(merged[-1]["end"]):
            continue
        merged.append(item)

    slots: list[dict[str, Any]] = []
    for idx, item in enumerate(merged, start=1):
        start = int(item["start"])
        end = int(item["end"])
        anchor_text = value[start:end].strip()
        if not anchor_text:
            continue
        slots.append(
            {
                "slot_id": f"{field}_slot_{idx:03d}",
                "field": field,
                "slot_type": str(item["slot_type"]),
                "anchor_text": anchor_text,
                "start": start,
                "end": end,
            }
        )
    return slots


def build_visual_insert_anchor_slots(record: dict[str, Any]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for field in ("stem", "answer", "analysis"):
        slots.extend(_extract_visual_insert_anchor_slots_for_field(field, str(record.get(f"{field}_text_md", "") or "")))
    return slots


def render_visual_insert_anchor_slots_for_prompt(record: dict[str, Any]) -> str:
    slots = build_visual_insert_anchor_slots(record)
    if not slots:
        return "- none"
    lines: list[str] = []
    for item in slots:
        anchor_text = str(item.get("anchor_text", "") or "").replace('"', '\\"')
        lines.append(
            f'- field={str(item.get("field", "") or "").strip()}; '
            f'slot_id={str(item.get("slot_id", "") or "").strip()}; '
            f'slot_type={str(item.get("slot_type", "") or "").strip()}; '
            f'anchor_text="{anchor_text}"'
        )
    return "\n".join(lines)


def build_content_blocks_from_visual_insert_anchor_plan(
    record: dict[str, Any],
    placements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assets_by_id = _assets_by_id(record)
    slot_map = {
        str(item.get("slot_id", "") or "").strip(): item
        for item in build_visual_insert_anchor_slots(record)
        if str(item.get("slot_id", "") or "").strip()
    }
    grouped: dict[str, list[dict[str, Any]]] = {"stem": [], "answer": [], "analysis": []}
    for item in placements:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("asset_id", "") or "").strip()
        target_field = str(item.get("target_field", "") or "").strip()
        if not asset_id or target_field not in grouped or asset_id not in assets_by_id:
            continue
        grouped[target_field].append(item)

    block_order = 0
    text_index: dict[str, int] = {"stem": 1, "answer": 1, "analysis": 1}
    image_index: dict[str, int] = {"stem": 1, "answer": 1, "analysis": 1}
    blocks: list[dict[str, Any]] = []

    def append_markdown(scope: str, text_md: str) -> None:
        nonlocal block_order
        content = str(text_md or "").strip()
        if not content:
            return
        block_order += 1
        idx = text_index[scope]
        text_index[scope] += 1
        blocks.append(
            {
                "block_id": f"blk_visual_anchor_{scope}_md_{idx:03d}",
                "block_order": block_order,
                "scope": scope,
                "block_type": "markdown",
                "text_md": content,
                "asset_id": None,
                "display_ref": None,
                "confidence": 1.0,
                "review_flags": ["visual_insert_anchor_review_applied"],
            }
        )

    def append_image(scope: str, asset: dict[str, Any], placement: dict[str, Any]) -> None:
        nonlocal block_order
        block_order += 1
        idx = image_index[scope]
        image_index[scope] += 1
        blocks.append(
            {
                "block_id": f"blk_visual_anchor_{scope}_img_{idx:03d}",
                "block_order": block_order,
                "scope": scope,
                "block_type": "image",
                "text_md": None,
                "asset_id": str(asset.get("asset_id", "") or "").strip(),
                "display_ref": str(asset.get("display_ref", "") or "").strip(),
                "storage_key": str(asset.get("storage_key", "") or "").strip(),
                "asset_role": str(asset.get("asset_role", asset.get("role", "")) or "").strip(),
                "confidence": float(placement.get("confidence", 0.0) or 0.0),
                "review_flags": normalize_review_flags(
                    list(placement.get("review_flags", []) or []) + ["visual_insert_anchor_review_applied"]
                ),
                "anchor_mode": str(placement.get("anchor_mode", "") or "").strip(),
                "anchor_slot_id": str(placement.get("anchor_slot_id", "") or "").strip(),
                "anchor_text": str(placement.get("anchor_text", "") or "").strip(),
            }
        )

    for field in ("stem", "answer", "analysis"):
        value = str(record.get(f"{field}_text_md", "") or "").strip()
        field_placements = grouped[field]
        if not field_placements:
            append_markdown(field, value)
            continue

        cursor = 0
        positioned: list[tuple[int, int, int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        tail_assets: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for placement_index, placement in enumerate(field_placements):
            asset = assets_by_id.get(str(placement.get("asset_id", "") or "").strip())
            if asset is None:
                continue
            anchor_mode = str(placement.get("anchor_mode", "") or "").strip()
            anchor_slot_id = str(placement.get("anchor_slot_id", "") or "").strip()
            anchor_text = str(placement.get("anchor_text", "") or "").strip()
            if value and anchor_mode == "after_anchor_slot" and anchor_slot_id:
                slot = slot_map.get(anchor_slot_id)
                if isinstance(slot, dict) and str(slot.get("field", "") or "").strip() == field:
                    positioned.append(
                        (
                            int(slot.get("start", 0) or 0),
                            int(slot.get("end", 0) or 0),
                            placement_index,
                            asset,
                            placement,
                            slot,
                        )
                    )
                    continue
            if value and anchor_mode == "after_anchor_text" and anchor_text:
                pos = value.find(anchor_text)
                if pos >= 0:
                    boundary = _visual_anchor_boundary(value, pos + len(anchor_text))
                    positioned.append(
                        (
                            pos,
                            boundary,
                            placement_index,
                            asset,
                            placement,
                            {
                                "slot_id": "",
                                "field": field,
                                "slot_type": "text_fallback",
                                "anchor_text": anchor_text,
                                "start": pos,
                                "end": boundary,
                            },
                        )
                    )
                    continue
            tail_assets.append((asset, placement))

        positioned.sort(key=lambda item: (item[0], item[1], item[2]))
        for _, end, _, asset, placement, slot in positioned:
            boundary = _visual_anchor_boundary(value, end)
            if boundary <= cursor:
                fallback_placement = dict(placement)
                fallback_placement["review_flags"] = normalize_review_flags(
                    list(fallback_placement.get("review_flags", []) or []) + ["visual_insert_anchor_slot_overlap"]
                )
                tail_assets.append((asset, fallback_placement))
                continue
            append_markdown(field, value[cursor:boundary])
            placement_with_slot = dict(placement)
            placement_with_slot["anchor_slot_id"] = str(slot.get("slot_id", "") or "").strip()
            placement_with_slot["anchor_text"] = str(slot.get("anchor_text", placement.get("anchor_text", "")) or "").strip()
            append_image(field, asset, placement_with_slot)
            cursor = boundary

        append_markdown(field, value[cursor:])
        for asset, placement in tail_assets:
            append_image(field, asset, placement)

    return blocks


def _build_display_blocks_from_qvs(record: dict[str, Any]) -> list[dict[str, Any]]:
    qvs = record.get("question_visual_structure", {}) if isinstance(record.get("question_visual_structure"), dict) else {}
    if str(qvs.get("inline_asset_anchor_mode", "") or "").strip() != "slot_reflow_v1":
        return []
    raw_blocks = [item for item in (qvs.get("content_blocks", []) or []) if isinstance(item, dict)]
    if not raw_blocks:
        return []

    assets_by_id = _assets_by_id(record)
    stem_assets = _resolve_selected_assets(record, "stem")
    analysis_assets = _resolve_selected_assets(record, "analysis")
    option_assets_by_key = _selected_option_assets_by_key(record)
    used_asset_ids: set[str] = set()

    def take_next(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        for asset in candidates:
            aid = str(asset.get("asset_id", "") or "").strip()
            if aid and aid not in used_asset_ids:
                used_asset_ids.add(aid)
                return asset
        return None

    def resolve_image_asset(block: dict[str, Any], scope: str, option_key: str) -> dict[str, Any] | None:
        raw_asset_id = str(block.get("asset_id", "") or "").strip()
        exact_asset = assets_by_id.get(raw_asset_id)
        if exact_asset is not None:
            aid = str(exact_asset.get("asset_id", "") or "").strip()
            if aid and aid not in used_asset_ids:
                used_asset_ids.add(aid)
                return exact_asset

        if scope == "option":
            return take_next(option_assets_by_key.get(option_key, []))

        asset_role = str(block.get("asset_role", "") or "").strip()
        candidate_groups: list[list[dict[str, Any]]] = []
        if scope == "stem" or asset_role == "stem":
            candidate_groups.append(stem_assets)
            candidate_groups.append(analysis_assets)
        elif scope in {"analysis", "answer"} or asset_role == "analysis":
            candidate_groups.append(analysis_assets)
            candidate_groups.append(stem_assets)
        else:
            candidate_groups.append(stem_assets)
            candidate_groups.append(analysis_assets)

        for group in candidate_groups:
            asset = take_next(group)
            if asset is not None:
                return asset
        return None

    blocks: list[dict[str, Any]] = []
    for block in raw_blocks:
        block_type = str(block.get("block_type", "") or "").strip()
        scope = str(block.get("scope", "") or "").strip()
        option_key = str(block.get("option_key", "") or "").strip().upper()
        field = "stem" if scope == "option" else scope

        if block_type == "markdown":
            content = str(block.get("text_md", "") or "").strip()
            if content:
                blocks.append({"type": "markdown", "field": field, "content": content})
            continue

        if block_type != "image":
            continue

        asset = resolve_image_asset(block, scope, option_key)
        if asset is None:
            continue

        blocks.append(
            {
                "type": "image",
                "field": field,
                "asset_id": str(asset.get("asset_id", "") or "").strip(),
                "display_ref": str(asset.get("display_ref", "") or "").strip(),
            }
        )
    return blocks


def build_display_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    qvs_blocks = _build_display_blocks_from_qvs(record)
    if qvs_blocks:
        return qvs_blocks

    blocks: list[dict[str, Any]] = []
    selected_option_by_key = _selected_option_asset_ids_by_key(record)
    if selected_option_by_key:
        by_id = _assets_by_id(record)
        option_assets: list[dict[str, Any]] = []
        ordered_option_keys = sorted(
            selected_option_by_key.keys(),
            key=lambda value: {"A": 1, "B": 2, "C": 3, "D": 4}.get(value, 99),
        )
        for option_key in ordered_option_keys:
            for asset_id in selected_option_by_key.get(option_key, []):
                asset = by_id.get(asset_id)
                if asset is not None:
                    option_assets.append(asset)
    else:
        option_assets = sorted(
            [
                a
                for a in record["assets"]
                if str(a.get("placement_scope", "") or a.get("placement", "") or "") == "option_inline"
                and bool(a.get("materialized", False))
                and str(a.get("file_status", "") or "") != "failed"
            ],
            key=lambda asset: (
                {"A": 1, "B": 2, "C": 3, "D": 4}.get(str(asset.get("option_key", "") or "").strip().upper(), 99),
                _asset_sort_key(asset),
            ),
        )
    if option_assets:
        option_prefix, option_labels, option_suffix = _split_stem_option_image_labels(record["stem_text_md"], len(option_assets))
        if option_labels:
            if option_prefix:
                blocks.append({"type": "markdown", "field": "stem", "content": option_prefix})
            assets_by_key = {
                str(asset.get("option_key", "") or "").strip().upper(): asset
                for asset in option_assets
                if str(asset.get("option_key", "") or "").strip()
            }
            unused_assets = [asset for asset in option_assets if str(asset.get("option_key", "") or "").strip().upper() not in set(option_labels)]
            for idx, label in enumerate(option_labels):
                blocks.append({"type": "markdown", "field": "stem", "content": label})
                asset = assets_by_key.get(str(label).rstrip(".").strip().upper())
                if asset is None and idx < len(unused_assets):
                    asset = unused_assets[idx]
                if asset is not None:
                    blocks.append({"type": "image", "field": "stem", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
            if option_suffix:
                blocks.append({"type": "markdown", "field": "stem", "content": option_suffix})
        else:
            if record["stem_text_md"].strip():
                blocks.append({"type": "markdown", "field": "stem", "content": record["stem_text_md"]})
            for asset in option_assets:
                label = str(asset.get("option_key", "") or "").strip().upper()
                if label:
                    blocks.append({"type": "markdown", "field": "stem", "content": f"{label}."})
                blocks.append({"type": "image", "field": "stem", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
    else:
        stem_assets = _resolve_selected_assets(record, "stem")
        option_prefix, option_labels, option_suffix = _split_stem_option_image_labels(record["stem_text_md"], len(stem_assets))
        if option_labels:
            if option_prefix:
                blocks.append({"type": "markdown", "field": "stem", "content": option_prefix})
            for label, asset in zip(option_labels, stem_assets):
                blocks.append({"type": "markdown", "field": "stem", "content": label})
                blocks.append({"type": "image", "field": "stem", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
            if option_suffix:
                blocks.append({"type": "markdown", "field": "stem", "content": option_suffix})
        else:
            stem_intro, stem_rest = _split_stem_for_inline_images_v3(record["stem_text_md"])
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

    analysis_assets = _resolve_selected_assets(record, "analysis")
    analysis_intro, analysis_sections = _split_numbered_sections_v3(record["analysis_text_md"])
    if analysis_assets and analysis_sections:
        if analysis_intro:
            blocks.append({"type": "markdown", "field": "analysis", "content": analysis_intro})
        for idx, section in enumerate(analysis_sections):
            if idx < len(analysis_assets):
                section_intro, section_rest = _split_section_for_inline_image(section)
                if section_intro:
                    blocks.append({"type": "markdown", "field": "analysis", "content": section_intro})
                asset = analysis_assets[idx]
                blocks.append({"type": "image", "field": "analysis", "asset_id": asset["asset_id"], "display_ref": asset["display_ref"]})
                if section_rest:
                    blocks.append({"type": "markdown", "field": "analysis", "content": section_rest})
            else:
                blocks.append({"type": "markdown", "field": "analysis", "content": section})
        for asset in sorted(analysis_assets[len(analysis_sections):], key=_asset_sort_key):
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
        assets, missing_assets, evidence_meta = _pick_single_evidence_asset(
            question,
            visual,
            base_dir,
            out_dir,
            question_id,
            include_debug_paths=include_debug_paths,
        )
        bridge_fragment_assets, missing_bridge_fragments = copy_bridge_fragment_assets(
            question,
            base_dir,
            out_dir,
            question_id,
            include_debug_paths=include_debug_paths,
        )
        missing_assets.extend(missing_bridge_fragments)

        staged_assets = [dict(item) for item in (question.get("staged_visual_assets", []) or []) if isinstance(item, dict)]
        materialized_staged_assets = [
            materialize_staged_asset(item, question, base_dir, out_dir, include_debug_paths=include_debug_paths)
            for item in staged_assets
        ]
        # Do not similarity-dedupe math figures. Set/function diagrams can be
        # visually close while carrying different labels or auxiliary lines.
        removed_duplicate_assets: list[dict[str, Any]] = []
        all_assets = assets + bridge_fragment_assets + materialized_staged_assets
        assign_external_labels(all_assets)

        record = {
            "question_id": question_id,
            "question_uid": str(question.get("question_uid", "") or question_id),
            "checkpoint": str(question.get("checkpoint", "") or ""),
            "component_label": str(question.get("component_label", "") or ""),
            "local_number": str(question.get("local_number", "") or ""),
            "visual_pages": question.get("visual_pages", []),
            "image_need_gate": question.get("image_need_gate", {}) if isinstance(question.get("image_need_gate"), dict) else {},
            "figure_detection_scope": question.get("figure_detection_scope", {}) if isinstance(question.get("figure_detection_scope"), dict) else {},
            "option_detection_review_flags": question.get("option_detection_review_flags", []) if isinstance(question.get("option_detection_review_flags"), list) else [],
            "stem_text_md": pick_text(question, visual, "stem_text", "stem_text_md"),
            "answer_text_md": pick_text(question, visual, "answer_text", "answer_text_md"),
            "analysis_text_md": pick_text(question, visual, "analysis_text", "analysis_text_md"),
            "stem_requires_image": pick_bool(question, visual, "stem_requires_image"),
            "analysis_requires_image": pick_bool(question, visual, "analysis_requires_image"),
            "assets": all_assets,
            "missing_assets": missing_assets,
            "removed_duplicate_assets": removed_duplicate_assets,
            "selected_scope_asset_ids": {
                "evidence": [str(evidence_meta.get("selected_evidence_asset_id", "") or "")] if str(evidence_meta.get("selected_evidence_asset_id", "") or "") else [],
                "bridge_fragments": [str(asset.get("asset_id", "") or "") for asset in bridge_fragment_assets],
                "stem": [],
                "analysis": [],
                "option_by_key": {},
            },
        }
        if evidence_meta:
            record["evidence_selection"] = evidence_meta
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
    repaired = str(text or "")
    repaired = re.sub(r"\\r\\n", "\n", repaired)
    repaired = re.sub(
        r"\\n(?=\s*(?:[A-D][.．、]|[①②③④⑤⑥⑦⑧⑨⑩]|[（(]\d+[）)]|##\s|【|图\d|第\d+题|解[:：]|证明[:：]|分析[:：]))",
        "\n",
        repaired,
    )
    repaired = re.sub(
        r"\\r(?=\s*(?:[A-D][.．、]|[①②③④⑤⑥⑦⑧⑨⑩]|[（(]\d+[）)]|##\s|【|图\d|第\d+题|解[:：]|证明[:：]|分析[:：]))",
        "\n",
        repaired,
    )
    repaired = re.sub(r"\?([A-Z]{3,6})\b", lambda m: "\u25b1" + m.group(1), repaired)
    repaired = repair_latex_for_render(repaired)
    escaped = html.escape(repaired)
    escaped = re.sub(r"^## (.+)$", r"<h4>\1</h4>", escaped, flags=re.MULTILINE)
    return escaped.replace("\n", "<br>")


def repair_latex_for_render(text: str) -> str:
    repaired = str(text or "")
    repaired = re.sub(r"(\\langle[^\n]{0,240})\nangle", r"\1\\rangle", repaired)
    repaired = re.sub(r"\\langle\s*([^$\n<>]{1,180})\n\s*angle", r"\\langle \1 \\rangle", repaired)
    repaired = re.sub(r"\\cos\\langle\s*([^$\n<>]{1,180})\n\s*angle", r"\\cos\\langle \1 \\rangle", repaired)
    repaired = re.sub(r"(?<!\\)rangle", r"\\rangle", repaired)
    repaired = re.sub(
        r"\$\$(.*?)\$\$",
        lambda m: "$$" + re.sub(r"\s*\n\s*", " ", m.group(1)) + "$$",
        repaired,
        flags=re.S,
    )
    repaired = re.sub(
        r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)",
        lambda m: "$" + re.sub(r"\s*\n\s*", " ", m.group(1)) + "$",
        repaired,
        flags=re.S,
    )
    return repaired


def asset_url(asset: dict[str, Any]) -> str:
    return html.escape(str(asset.get("delivery_storage_key", asset.get("review_storage_key", asset["storage_key"]))))


def asset_meta_badges(asset: dict[str, Any]) -> str:
    badges: list[str] = []
    detector_source = str(asset.get("detector_source", "") or "").strip()
    if detector_source:
        badges.append(f"<span class='badge'>{html.escape(detector_source)}</span>")
    crop_policy = str(asset.get("crop_policy", "") or "").strip()
    if crop_policy:
        badges.append(f"<span class='badge'>{html.escape(crop_policy)}</span>")
    audit = asset.get("bbox_audit", {}) if isinstance(asset.get("bbox_audit"), dict) else {}
    validity = str(audit.get("validity", "") or "").strip()
    if validity:
        badge_class = "badge ok" if validity == "valid" else "badge warn"
        badges.append(f"<span class='{badge_class}'>{html.escape(validity)}</span>")
    external_label_kind = str(asset.get("external_label_kind", "") or "").strip()
    if external_label_kind:
        badges.append(f"<span class='badge'>{html.escape(external_label_kind)}</span>")
    external_label_text = str(asset.get("external_label_text", "") or "").strip()
    if external_label_text:
        badges.append(f"<span class='badge ok'>{html.escape(external_label_text)}</span>")
    review_render = asset.get("delivery_render", asset.get("review_render", {}))
    review_render = review_render if isinstance(review_render, dict) else {}
    review_scale = float(review_render.get("scale", 0) or 0)
    if review_scale > 1.05:
        badges.append(f"<span class='badge ok'>delivery x{review_scale:g}</span>")
    return "".join(badges)


def asset_external_label_html(asset: dict[str, Any]) -> str:
    label = str(asset.get("external_label_text", "") or "").strip()
    if not label:
        return ""
    kind = str(asset.get("external_label_kind", "") or "").strip()
    class_name = "asset-label option-label" if kind == "option_key" else "asset-label"
    return f"<div class='{class_name}'>{html.escape(label)}</div>"


def asset_audit_caption(asset: dict[str, Any]) -> str:
    parts: list[str] = []
    role = str(asset.get("role", asset.get("asset_role", "")) or "")
    display_ref = str(asset.get("display_ref", asset.get("asset_id", "")) or "")
    if role:
        parts.append(role)
    if display_ref:
        parts.append(display_ref)
    audit = asset.get("bbox_audit", {}) if isinstance(asset.get("bbox_audit"), dict) else {}
    validity = str(audit.get("validity", "") or "").strip()
    if validity:
        parts.append(f"bbox={validity}")
    detector_source = str(asset.get("detector_source", "") or "").strip()
    if detector_source:
        parts.append(f"source={detector_source}")
    panel_group_id = str(asset.get("panel_group_id", "") or "").strip()
    if panel_group_id:
        parts.append(f"group={panel_group_id}")
    panel_subfigure_count = int(asset.get("panel_subfigure_count", 0) or 0)
    if panel_subfigure_count > 1:
        parts.append(f"subfigures={panel_subfigure_count}")
    suspect_reasons = audit.get("suspect_reasons", []) if isinstance(audit.get("suspect_reasons"), list) else []
    if suspect_reasons:
        parts.append("risk=" + ",".join(str(item) for item in suspect_reasons[:4]))
    return " | ".join(parts)


def asset_figure_html(asset: dict[str, Any], asset_id: str = "", *, show_asset_debug: bool = False) -> str:
    rendered_asset_id = asset_id or str(asset.get("asset_id", "") or "")
    debug_html = ""
    if show_asset_debug:
        debug_html = (
            f"<div class='badges'>{asset_meta_badges(asset)}</div>"
            f"<figcaption>{html.escape(asset_audit_caption(asset))}</figcaption>"
        )
    return (
        "<figure>"
        f"{asset_external_label_html(asset)}"
        f"<img src='{asset_url(asset)}' alt='{html.escape(rendered_asset_id)}'>"
        f"{debug_html}"
        "</figure>"
    )


def render_text_block(text: str) -> str:
    body = render_md(text)
    return f"<div class='md'>{body}</div>" if body else ""


def _asset_render_size(asset: dict[str, Any]) -> tuple[int, int]:
    meta = asset.get("delivery_render", asset.get("review_render", {}))
    meta = meta if isinstance(meta, dict) else {}
    return int(meta.get("width", 0) or 0), int(meta.get("height", 0) or 0)


def _prefer_stacked_image_group(assets: list[dict[str, Any]]) -> bool:
    if len(assets) <= 1:
        return False
    if len(assets) >= 3:
        return True
    for asset in assets:
        width, height = _asset_render_size(asset)
        if width >= 560 or height >= 420:
            return True
        if int(asset.get("panel_subfigure_count", 0) or 0) > 1:
            return True
    return False


def render_display_blocks_html(record: dict[str, Any], *, show_asset_debug: bool = False) -> str:
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
            parts.append(asset_figure_html(asset, asset_id, show_asset_debug=show_asset_debug))
    return "".join(parts)


def render_display_blocks_html_v2(record: dict[str, Any], *, show_asset_debug: bool = False) -> str:
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
            card_assets: list[dict[str, Any]] = []
            while index < len(blocks):
                image_block = blocks[index]
                if str(image_block.get("type", "") or "").strip() != "image" or str(image_block.get("field", "") or "").strip() != field:
                    break
                asset_id = str(image_block.get("asset_id", "") or "").strip()
                asset = assets_by_id.get(asset_id)
                if asset:
                    card_assets.append(asset)
                    cards.append(asset_figure_html(asset, asset_id, show_asset_debug=show_asset_debug))
                index += 1
            if cards:
                container_class = "image-stack" if _prefer_stacked_image_group(card_assets) else "image-row"
                parts.append(f"<div class='{container_class}'>{''.join(cards)}</div>")
            continue

        index += 1

    return "".join(parts)


def write_html(out_path: Path, payload: dict[str, Any]) -> None:
    html_assets = stage_html_assets(out_path.parent)
    katex_css_link = (
        f"<link rel=\"stylesheet\" href=\"{html.escape(html_assets['katex_css'])}\" />"
        if "katex_css" in html_assets
        else ""
    )
    katex_js_script = (
        f"<script defer src=\"{html.escape(html_assets['katex_js'])}\"></script>"
        if "katex_js" in html_assets
        else ""
    )
    auto_render_script = (
        f"<script defer src=\"{html.escape(html_assets['auto_render_js'])}\"></script>"
        if "auto_render_js" in html_assets
        else ""
    )
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

        review_html = render_display_blocks_html_v2(record, show_asset_debug=True)

        rows.append(
            "<section class='card'>"
            f"<h2>{html.escape(record['question_id'])} <small>{html.escape(record['component_label'])} Q{html.escape(record['local_number'])}</small></h2>"
            f"<div class='badges'>{asset_badges}{missing}</div>"
            "<div class='grid'>"
            "<div>"
            "<h3>落库结构版</h3>"
            f"{render_display_blocks_html_v2(record, show_asset_debug=True)}"
            "</div>"
            "<div>"
            "<h3>审核复写版</h3>"
            f"{review_html}"
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
  {katex_css_link}
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
    .md {{ background: #fbfcff; border: 1px solid #e7edf8; border-radius: 12px; padding: 14px; line-height: 1.9; white-space: normal; }}
    .badges {{ margin: 8px 0 12px; }}
    .badge {{ display: inline-block; margin: 0 6px 6px 0; padding: 4px 8px; border-radius: 999px; background: #eef4ff; color: #175cd3; font-size: 12px; }}
    .badge.warn {{ background: #fff1f3; color: #c01048; }}
    .badge.ok {{ background: #ecfdf3; color: #027a48; }}
    .asset-label {{ display: inline-block; margin: 0 0 8px; padding: 3px 8px; border-radius: 6px; background: #101828; color: #fff; font-size: 13px; font-weight: 700; }}
    .option-label {{ background: #175cd3; }}
    .image-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 12px; }}
    .image-stack {{ display: grid; grid-template-columns: 1fr; gap: 12px; margin-top: 12px; }}
    figure {{ margin: 0 0 12px; padding: 10px; border: 1px solid #e7edf8; border-radius: 12px; background: #fff; }}
    img {{ max-width: 100%; height: auto; display: block; border-radius: 8px; background: #fff; }}
    figcaption {{ margin-top: 8px; color: #667085; font-size: 12px; word-break: break-all; }}
    .katex {{ font-size: 1.06em; line-height: 1.35; }}
    .md .katex {{ vertical-align: -0.12em; }}
    .md .katex-html {{ white-space: nowrap; }}
    .katex-display {{ margin: .6em 0; overflow-x: auto; overflow-y: hidden; }}
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
  {katex_js_script}
  {auto_render_script}
  <script>
    window.addEventListener('DOMContentLoaded', function () {{
      if (!window.renderMathInElement) return;
      window.renderMathInElement(document.body, {{
        delimiters: [
          {{ left: '$$', right: '$$', display: true }},
          {{ left: '$', right: '$', display: false }}
        ],
        throwOnError: false
      }});
    }});
  </script>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")


def write_html_clean(out_path: Path, payload: dict[str, Any], *, show_asset_debug: bool = False) -> None:
    html_assets = stage_html_assets(out_path.parent)
    katex_css_link = (
        f"<link rel=\"stylesheet\" href=\"{html.escape(html_assets['katex_css'])}\" />"
        if "katex_css" in html_assets
        else ""
    )
    katex_js_script = (
        f"<script defer src=\"{html.escape(html_assets['katex_js'])}\"></script>"
        if "katex_js" in html_assets
        else ""
    )
    auto_render_script = (
        f"<script defer src=\"{html.escape(html_assets['auto_render_js'])}\"></script>"
        if "auto_render_js" in html_assets
        else ""
    )

    def image_cards(assets: list[dict[str, Any]]) -> str:
        cards: list[str] = []
        for asset in assets:
            cards.append(
                asset_figure_html(
                    asset,
                    str(asset.get("asset_id", "") or ""),
                    show_asset_debug=show_asset_debug,
                )
            )
        return "".join(cards)

    rows: list[str] = []
    for record in payload["questions"]:
        evidence_assets = [a for a in record["assets"] if str(a.get("placement", "")) == "evidence_only"]
        asset_badges = ""
        missing = ""
        if show_asset_debug:
            asset_badges = " ".join(
                f"<span class='badge'>{html.escape(str(a.get('asset_role', a.get('role', ''))))}: {html.escape(str(a.get('display_ref', '')))}</span>"
                for a in record["assets"]
            )
            missing = " ".join(
                f"<span class='badge warn'>{html.escape(m['field'])} missing</span>"
                for m in record["missing_assets"]
            )
        debug_badges_html = (
            f"<div class='badges'>{asset_badges}{missing}</div>"
            if show_asset_debug and (asset_badges or missing)
            else ""
        )
        rows.append(
            "<section class='card'>"
            f"<h2>{html.escape(record['question_id'])} <small>{html.escape(record['component_label'])} Q{html.escape(record['local_number'])}</small></h2>"
            f"{debug_badges_html}"
            "<div class='grid'>"
            "<div>"
            "<h3>落库结构版</h3>"
            f"{render_display_blocks_html_v2(record, show_asset_debug=show_asset_debug)}"
            "</div>"
            "<div>"
            "<h3>审核复写版</h3>"
            f"{render_display_blocks_html_v2(record, show_asset_debug=show_asset_debug)}"
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
  <title>{'题目图片资产调试页' if show_asset_debug else '题目图片资产审核页'}</title>
  {katex_css_link}
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
    .md {{ background: #fbfcff; border: 1px solid #e7edf8; border-radius: 12px; padding: 14px; line-height: 1.9; white-space: normal; }}
    .badges {{ margin: 8px 0 12px; }}
    .badge {{ display: inline-block; margin: 0 6px 6px 0; padding: 4px 8px; border-radius: 999px; background: #eef4ff; color: #175cd3; font-size: 12px; }}
    .badge.warn {{ background: #fff1f3; color: #c01048; }}
    .badge.ok {{ background: #ecfdf3; color: #027a48; }}
    .asset-label {{ display: inline-block; margin: 0 0 8px; padding: 3px 8px; border-radius: 6px; background: #101828; color: #fff; font-size: 13px; font-weight: 700; }}
    .option-label {{ background: #175cd3; }}
    .image-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 12px; }}
    .image-stack {{ display: grid; grid-template-columns: 1fr; gap: 12px; margin-top: 12px; }}
    figure {{ margin: 0 0 12px; padding: 10px; border: 1px solid #e7edf8; border-radius: 12px; background: #fff; }}
    img {{ max-width: 100%; height: auto; display: block; border-radius: 8px; background: #fff; }}
    figcaption {{ margin-top: 8px; color: #667085; font-size: 12px; word-break: break-all; }}
    .katex {{ font-size: 1.06em; line-height: 1.35; }}
    .md .katex {{ vertical-align: -0.12em; }}
    .md .katex-html {{ white-space: nowrap; }}
    .katex-display {{ margin: .6em 0; overflow-x: auto; overflow-y: hidden; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .wrap {{ padding: 14px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{'题目图片资产调试页' if show_asset_debug else '题目图片资产审核页'}</h1>
    <p>生成时间：{html.escape(payload["generated_at"])} | 题目数：{payload["question_count"]} | 图片资产：{payload["asset_count"]}</p>
  </header>
  <main class="wrap">
    {body}
  </main>
  {katex_js_script}
  {auto_render_script}
  <script>
    window.addEventListener('DOMContentLoaded', function () {{
      if (!window.renderMathInElement) return;
      window.renderMathInElement(document.body, {{
        delimiters: [
          {{ left: '$$', right: '$$', display: true }},
          {{ left: '$', right: '$', display: false }}
        ],
        throwOnError: false
      }});
    }});
  </script>
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
            "asset_storage_key_strategy": "question_assets/{question_uid}/{runtime_run_id}/...",
            "delivery_storage_key_strategy": "_delivery_assets/{storage_key}",
            "debug_absolute_paths_included": bool(args.include_debug_paths),
        },
        "question_count": len(records),
        "asset_count": asset_count,
        "questions": records,
    }
    write_json(out_dir / "question_asset_manifest_v0.1.json", payload)
    write_html_clean(out_dir / "question_asset_review.html", payload)
    write_html_clean(out_dir / "question_asset_review_debug.html", payload, show_asset_debug=True)

    summary = {
        "out_dir": str(out_dir),
        "manifest": str(out_dir / "question_asset_manifest_v0.1.json"),
        "html": str(out_dir / "question_asset_review.html"),
        "debug_html": str(out_dir / "question_asset_review_debug.html"),
        "question_count": len(records),
        "asset_count": asset_count,
        "questions_with_stem_image": sum(any(str(a.get("role") or a.get("asset_role") or "") == "stem" for a in r["assets"]) for r in records),
        "questions_with_analysis_image": sum(any(str(a.get("role") or a.get("asset_role") or "") == "analysis" for a in r["assets"]) for r in records),
        "questions_with_option_assets": sum(any(str(a.get("role") or a.get("asset_role") or "") == "option" for a in r["assets"]) for r in records),
        "questions_with_missing_assets": sum(bool(r["missing_assets"]) for r in records),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
