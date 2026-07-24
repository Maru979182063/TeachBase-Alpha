"""Probe a true VLM-first unit planner on rendered handout pages.

This is intentionally separate from the production splitter. It verifies whether
the model can plan business units directly from page images before we wire the
node into the main pipeline.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw

import vision_prompt_store


ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
DEFAULT_DPI = 120


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def extract_json_block(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_not_found")
    return json.loads(clean[start : end + 1])


def render_pdf_pages(pdf_path: Path, pages: list[int], out_dir: Path, dpi: int = DEFAULT_DPI) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    rendered: dict[int, Path] = {}
    for page_no in pages:
        pix = doc[page_no - 1].get_pixmap(matrix=mat, alpha=False)
        out = out_dir / f"page_{page_no:03d}.png"
        pix.save(str(out))
        rendered[page_no] = out
    doc.close()
    return rendered


def call_model(
    page_paths: dict[int, Path],
    api_key: str,
    model: str,
    error_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt_bundle = vision_prompt_store.get_visual_unit_planner_probe_prompt_bundle()
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt_bundle["system_prompt"]},
        {"type": "text", "text": prompt_bundle["user_template"]},
    ]
    for page_no, path in sorted(page_paths.items()):
        content.append({"type": "text", "text": f"PAGE {page_no}"})
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(path)}})
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        ARK_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    payload = json.loads(raw)
    model_text = payload["choices"][0]["message"]["content"]
    meta = {
        "latency_seconds": round(time.time() - started, 3),
        "usage": payload.get("usage", {}),
        "raw_response": payload,
        "model_text": model_text,
    }
    try:
        parsed = extract_json_block(model_text)
    except Exception:
        if error_dir is not None:
            error_dir.mkdir(parents=True, exist_ok=True)
            (error_dir / "visual_unit_planner_raw_response_on_parse_error.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (error_dir / "visual_unit_planner_model_text_on_parse_error.txt").write_text(
                str(model_text),
                encoding="utf-8",
            )
        raise
    return parsed, meta


def norm_to_image_bbox(box: list[Any], image_size: tuple[int, int]) -> list[int]:
    width, height = image_size
    if not isinstance(box, list) or len(box) != 4:
        return [0, 0, 1, 1]
    x1, y1, x2, y2 = [float(v) for v in box]
    px = [
        int(round(x1 / 1000.0 * width)),
        int(round(y1 / 1000.0 * height)),
        int(round(x2 / 1000.0 * width)),
        int(round(y2 / 1000.0 * height)),
    ]
    px[0] = max(0, min(px[0], width - 1))
    px[1] = max(0, min(px[1], height - 1))
    px[2] = max(px[0] + 1, min(px[2], width))
    px[3] = max(px[1] + 1, min(px[3], height))
    return px


def _valid_norm_box(box: Any) -> list[float] | None:
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in box]
    except (TypeError, ValueError):
        return None
    x1 = max(0.0, min(1000.0, x1))
    y1 = max(0.0, min(1000.0, y1))
    x2 = max(0.0, min(1000.0, x2))
    y2 = max(0.0, min(1000.0, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def enforce_parent_child_containment(parsed: dict[str, Any]) -> dict[str, Any]:
    """Expand parent fragments to include their own child assets.

    The VLM decides semantic ownership. This post-pass only makes the geometry
    internally consistent; it never creates, deletes, or merges semantic units.
    """
    adjustments: list[dict[str, Any]] = []
    for unit in parsed.get("units", []):
        if not isinstance(unit, dict):
            continue
        fragments = unit.get("fragments", [])
        child_assets = unit.get("child_assets", [])
        if not isinstance(fragments, list) or not isinstance(child_assets, list):
            continue
        for frag in fragments:
            if not isinstance(frag, dict):
                continue
            page = int(frag.get("page", 0) or 0)
            parent_box = _valid_norm_box(frag.get("bbox_norm1000"))
            if page <= 0 or parent_box is None:
                continue
            union_box = list(parent_box)
            included_assets: list[str] = []
            for asset in child_assets:
                if not isinstance(asset, dict):
                    continue
                if int(asset.get("page", 0) or 0) != page:
                    continue
                asset_box = _valid_norm_box(asset.get("bbox_norm1000"))
                if asset_box is None:
                    continue
                union_box = [
                    min(union_box[0], asset_box[0]),
                    min(union_box[1], asset_box[1]),
                    max(union_box[2], asset_box[2]),
                    max(union_box[3], asset_box[3]),
                ]
                included_assets.append(str(asset.get("asset_id", "") or "asset"))
            if union_box != parent_box:
                frag["bbox_norm1000"] = [round(value, 2) for value in union_box]
                adjustments.append(
                    {
                        "unit_id": str(unit.get("unit_id", "") or ""),
                        "page": page,
                        "before": [round(value, 2) for value in parent_box],
                        "after": frag["bbox_norm1000"],
                        "included_child_assets": included_assets,
                    }
                )
    parsed.setdefault("postprocess", {})
    if isinstance(parsed["postprocess"], dict):
        parsed["postprocess"]["parent_child_containment"] = adjustments
    return parsed


def color_for_role(role: str) -> tuple[int, int, int]:
    if role in {"knowledge"}:
        return (37, 99, 235)
    if role in {"passage_group", "writing_task", "single_question"}:
        return (16, 145, 80)
    if role in {"table_or_form", "diagram_or_mindmap"}:
        return (147, 51, 234)
    if role == "noise":
        return (180, 83, 9)
    return (220, 38, 38)


def draw_overlays(parsed: dict[str, Any], page_paths: dict[int, Path], out_dir: Path) -> dict[str, dict[int, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base_images = {page: Image.open(path).convert("RGB") for page, path in page_paths.items()}
    parent_images = {page: img.copy() for page, img in base_images.items()}
    child_images = {page: img.copy() for page, img in base_images.items()}
    combined_images = {page: img.copy() for page, img in base_images.items()}
    parent_draws = {page: ImageDraw.Draw(img) for page, img in parent_images.items()}
    child_draws = {page: ImageDraw.Draw(img) for page, img in child_images.items()}
    combined_draws = {page: ImageDraw.Draw(img) for page, img in combined_images.items()}
    for unit in parsed.get("units", []):
        role = str(unit.get("semantic_role", "review_only"))
        color = color_for_role(role)
        label = f"{unit.get('unit_id','')} {role} {unit.get('route','')}"
        for frag in unit.get("fragments", []):
            page = int(frag.get("page", 0) or 0)
            if page not in base_images:
                continue
            bbox = norm_to_image_bbox(frag.get("bbox_norm1000", []), base_images[page].size)
            for draw in (parent_draws[page], combined_draws[page]):
                draw.rectangle(bbox, outline=color, width=4)
                draw.text((bbox[0] + 4, max(0, bbox[1] - 18)), label, fill=color)
        for asset in unit.get("child_assets", []):
            page = int(asset.get("page", 0) or 0)
            if page not in base_images:
                continue
            bbox = norm_to_image_bbox(asset.get("bbox_norm1000", []), base_images[page].size)
            asset_label = f"{asset.get('asset_id','asset')} {asset.get('asset_type','child')}"
            for draw in (child_draws[page], combined_draws[page]):
                draw.rectangle(bbox, outline=(147, 51, 234), width=2)
                draw.text((bbox[0] + 4, max(0, bbox[1] - 14)), asset_label, fill=(147, 51, 234))
    outputs: dict[str, dict[int, Path]] = {"parent_only": {}, "child_assets": {}, "combined": {}}
    for layer_name, layer_images in (
        ("parent_only", parent_images),
        ("child_assets", child_images),
        ("combined", combined_images),
    ):
        layer_dir = out_dir / layer_name
        layer_dir.mkdir(parents=True, exist_ok=True)
        for page, img in layer_images.items():
            out = layer_dir / f"page_{page:03d}_{layer_name}.png"
            img.save(out)
            outputs[layer_name][page] = out
            if layer_name == "combined":
                legacy_out = out_dir / f"page_{page:03d}_visual_unit_overlay.png"
                img.save(legacy_out)
    return outputs


def crop_units(parsed: dict[str, Any], page_paths: dict[int, Path], out_dir: Path) -> list[dict[str, Any]]:
    crop_dir = out_dir / "unit_cuts"
    crop_dir.mkdir(parents=True, exist_ok=True)
    images = {page: Image.open(path).convert("RGB") for page, path in page_paths.items()}
    rows: list[dict[str, Any]] = []
    for unit in parsed.get("units", []):
        parts: list[tuple[int, list[int], Image.Image]] = []
        for frag in unit.get("fragments", []):
            page = int(frag.get("page", 0) or 0)
            if page not in images:
                continue
            bbox = norm_to_image_bbox(frag.get("bbox_norm1000", []), images[page].size)
            parts.append((page, bbox, images[page].crop(tuple(bbox))))
        if not parts:
            continue
        pad = 24
        gap = 16
        width = max(crop.width for _, _, crop in parts) + pad * 2
        height = pad + sum(crop.height for _, _, crop in parts) + gap * (len(parts) - 1) + pad
        canvas = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(canvas)
        y = pad
        for page, bbox, crop in parts:
            canvas.paste(crop, (pad, y))
            draw.rectangle([pad, y, pad + crop.width - 1, y + crop.height - 1], outline=(37, 99, 235), width=2)
            draw.text((pad + 4, y + 4), f"p{page} {bbox}", fill=(37, 99, 235))
            y += crop.height + gap
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(unit.get("unit_id", "unit")))
        out = crop_dir / f"{safe}_{unit.get('semantic_role','unit')}.png"
        canvas.save(out)
        rows.append({"unit": unit, "path": out})
    return rows


def write_review(
    parsed: dict[str, Any],
    meta: dict[str, Any],
    rows: list[dict[str, Any]],
    overlays: dict[str, dict[int, Path]],
    out_dir: Path,
) -> Path:
    cards = []
    for row in rows:
        unit = row["unit"]
        rel = row["path"].relative_to(out_dir).as_posix()
        child_assets = unit.get("child_assets", [])
        child_html = "".join(
            f"<li><b>{html.escape(str(asset.get('asset_id','')))}</b> {html.escape(str(asset.get('asset_type','')))} "
            f"p{html.escape(str(asset.get('page','')))} {html.escape(str(asset.get('bbox_norm1000','')))} "
            f"{html.escape(str(asset.get('reason','')))}</li>"
            for asset in child_assets
        )
        cards.append(
            "<section class='card'>"
            f"<h2>{html.escape(str(unit.get('unit_id','')))} <span>{html.escape(str(unit.get('semantic_role','')))} / {html.escape(str(unit.get('route','')))}</span></h2>"
            f"<div class='meta'>pages: {html.escape(','.join(map(str, unit.get('pages', []))))} | confidence: {html.escape(str(unit.get('confidence','')))} | continuation: {html.escape(str(unit.get('continuation','')))}</div>"
            f"<div class='reason'>{html.escape(str(unit.get('reason','')))}</div>"
            f"<div class='meta'>child_assets: {len(child_assets)}</div>"
            f"<ul>{child_html}</ul>"
            f"<img src='{rel}' loading='lazy'>"
            "</section>"
        )
    overlay_links = []
    for layer_name, layer_paths in overlays.items():
        links = " | ".join(
            f"<a href='{path.relative_to(out_dir).as_posix()}'>page {page}</a>" for page, path in sorted(layer_paths.items())
        )
        overlay_links.append(f"<div><b>{html.escape(layer_name)}:</b> {links}</div>")
    overlay_links_html = "".join(overlay_links)
    review = out_dir / "visual_unit_planner_probe_review.html"
    review.write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Visual Unit Planner Probe</title>
<style>
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f5f7fb;color:#172033;margin:24px}}
.summary,.card{{background:white;border:1px solid #dbe4f0;border-radius:14px;padding:14px;margin-bottom:16px;box-shadow:0 4px 16px rgba(20,40,80,.06)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:18px}}
h2 span{{font-size:14px;color:#3864a8}}
.meta,.reason{{color:#5b6470;margin:6px 0}}
img{{max-width:100%;height:auto;border:1px solid #e1e7ef;background:white}}
pre{{white-space:pre-wrap;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:10px;max-height:320px;overflow:auto}}
</style></head><body>
<h1>Visual Unit Planner Probe</h1>
<section class="summary">
<div><b>真实状态：</b>这是 VLM 直接看整页图输出的探针结果，不是主链路正式接入。</div>
<div><b>model_judgement：</b>{html.escape(str(parsed.get('model_judgement','')))}</div>
<div><b>unit_count：</b>{len(parsed.get('units', []))}</div>
<div><b>latency_seconds：</b>{html.escape(str(meta.get('latency_seconds','')))}</div>
<div><b>usage：</b>{html.escape(json.dumps(meta.get('usage', {}), ensure_ascii=False))}</div>
<div>{overlay_links_html}</div>
<pre>{html.escape(json.dumps(parsed, ensure_ascii=False, indent=2))}</pre>
</section>
<div class="grid">{''.join(cards)}</div>
</body></html>""",
        encoding="utf-8",
    )
    return review


def write_layered_page_review(page_paths: dict[int, Path], overlays: dict[str, dict[int, Path]], out_dir: Path) -> Path:
    cards = []
    for page, page_path in sorted(page_paths.items()):
        parent = overlays.get("parent_only", {}).get(page)
        child = overlays.get("child_assets", {}).get(page)
        combined = overlays.get("combined", {}).get(page)
        cards.append(
            "<section class='page-card'>"
            f"<h2>page {page}</h2>"
            "<div class='grid'>"
            f"<div><h3>Original</h3><img src='{page_path.relative_to(out_dir).as_posix()}'></div>"
            f"<div><h3>Parent modules</h3><img src='{parent.relative_to(out_dir).as_posix() if parent else ''}'></div>"
            f"<div><h3>Child assets</h3><img src='{child.relative_to(out_dir).as_posix() if child else ''}'></div>"
            f"<div><h3>Combined debug</h3><img src='{combined.relative_to(out_dir).as_posix() if combined else ''}'></div>"
            "</div>"
            "</section>"
        )
    review = out_dir / "original_pages_vs_layered_overlay.html"
    review.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>Layered Visual Planner Review</title>
<style>
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f6f8fc;color:#172033;margin:24px}}
.page-card{{background:white;border:1px solid #dbe4f0;border-radius:14px;padding:16px;margin-bottom:20px;box-shadow:0 4px 16px rgba(20,40,80,.06)}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(260px,1fr));gap:14px;align-items:start}}
img{{max-width:100%;border:1px solid #d7deea;background:white}}
h1{{margin-top:0}}
h3{{margin:8px 0;color:#475569;font-size:15px}}
.note{{background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:10px;margin:12px 0;color:#9a3412}}
</style></head><body>
<h1>Layered Visual Planner Review</h1>
<div class="note">Use Parent modules to judge business-unit splitting. Child assets shows internal tables/figures/answers. Combined debug is not the final crop contract.</div>
{''.join(cards)}
</body></html>""",
        encoding="utf-8",
    )
    return review


def main() -> None:
    pdf_path = Path(os.environ["PDF_TEACHER"])
    out_dir = Path(os.environ.get("VISUAL_UNIT_PLANNER_OUT", "out/visual_unit_planner_probe")).resolve()
    page_text = os.environ.get("VISUAL_UNIT_PLANNER_PAGES", "1,2")
    pages = [int(item.strip()) for item in page_text.split(",") if item.strip()]
    api_key = os.environ.get("ARK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ARK_API_KEY is required for model probe")
    model = os.environ.get("VISUAL_UNIT_PLANNER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    out_dir.mkdir(parents=True, exist_ok=True)
    page_paths = render_pdf_pages(pdf_path, pages, out_dir / "rendered_pages_120dpi")
    try:
        parsed, meta = call_model(page_paths, api_key=api_key, model=model, error_dir=out_dir)
    except Exception as exc:
        (out_dir / "visual_unit_planner_error.txt").write_text(str(exc), encoding="utf-8")
        raise
    parsed = enforce_parent_child_containment(parsed)
    (out_dir / "visual_unit_planner_response.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "visual_unit_planner_raw_response.json").write_text(json.dumps(meta["raw_response"], ensure_ascii=False, indent=2), encoding="utf-8")
    overlays = draw_overlays(parsed, page_paths, out_dir / "overlays")
    rows = crop_units(parsed, page_paths, out_dir)
    review = write_review(parsed, meta, rows, overlays, out_dir)
    layered_review = write_layered_page_review(page_paths, overlays, out_dir)
    print(json.dumps({
        "out_dir": str(out_dir),
        "review": str(review),
        "layered_review": str(layered_review),
        "response": str(out_dir / "visual_unit_planner_response.json"),
        "unit_count": len(parsed.get("units", [])),
        "usage": meta.get("usage", {}),
        "latency_seconds": meta.get("latency_seconds"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
