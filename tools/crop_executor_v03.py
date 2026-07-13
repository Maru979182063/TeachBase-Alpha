from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tools.cross_page_node_accumulator_v03 import SemanticNodeV03
from tools.page_render_adapter_v03 import PageManifestV03


def _union(boxes: list[list[int]]) -> list[int]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def execute_crops_v03(nodes: list[SemanticNodeV03], manifests: list[PageManifestV03], out_dir: Path) -> dict:
    manifest_by_page = {m.page: m for m in manifests}
    crop_root = out_dir / "crops"
    crop_root.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    for node in nodes:
        node_dir = crop_root / node.node_id
        node_dir.mkdir(parents=True, exist_ok=True)
        crops = []
        crop_records = []
        for idx, fragment in enumerate(node.fragments, start=1):
            manifest = manifest_by_page.get(fragment.page)
            if manifest is None:
                continue
            img = Image.open(manifest.page_image_master).convert("RGB")
            x0, y0, x1, y1 = _union([fragment.bbox_px])
            x0 = max(0, min(img.width - 1, x0))
            y0 = max(0, min(img.height - 1, y0))
            x1 = max(x0 + 1, min(img.width, x1))
            y1 = max(y0 + 1, min(img.height, y1))
            out = node_dir / f"fragment_{idx:02d}_p{fragment.page:03d}_{fragment.role}.png"
            img.crop((x0, y0, x1, y1)).save(out, quality=95)
            crops.append(str(out))
            crop_records.append(
                {
                    "path": str(out),
                    "page": fragment.page,
                    "role": fragment.role,
                    "bbox_px": [x0, y0, x1, y1],
                    "page_width": img.width,
                    "page_height": img.height,
                }
            )
        canvas_path = node_dir / "review_canvas.png"
        _write_review_canvas(crops, canvas_path, node.node_id, crop_records)
        records[node.node_id] = {
            "fragment_crops": crops,
            "fragment_records": crop_records,
            "review_canvas": str(canvas_path),
            "question_composite": str(canvas_path),
        }
    (out_dir / "crop_manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def _write_review_canvas(crop_paths: list[str], out_path: Path, title: str, crop_records: list[dict] | None = None) -> None:
    if not crop_paths:
        return
    records = crop_records or [{"path": p} for p in crop_paths]
    loaded = []
    for idx, record in enumerate(records, start=1):
        path = Path(record.get("path", ""))
        if not path.exists():
            continue
        image = Image.open(path).convert("RGB")
        bbox = record.get("bbox_px")
        if not bbox or len(bbox) != 4:
            bbox = [0, 0, image.width, image.height]
        loaded.append(
            {
                **record,
                "index": idx,
                "image": image,
                "bbox_px": [int(v) for v in bbox],
                "role": str(record.get("role") or _role_from_crop_name(path)),
                "page": record.get("page"),
            }
        )
    if not loaded:
        return

    # Preserve the original horizontal composition: fragments from the same
    # question are pasted according to their source x coordinate, not left-stacked.
    x0_min = min(item["bbox_px"][0] for item in loaded)
    x1_max = max(item["bbox_px"][2] for item in loaded)
    content_w = max(x1_max - x0_min, max(item["image"].width for item in loaded))
    margin_x = 42
    margin_y = 34
    title_h = 62
    label_h = 32
    gap = 24
    width = max(720, content_w + margin_x * 2)
    height = title_h + margin_y
    for item in loaded:
        height += label_h + item["image"].height + gap
    height += margin_y

    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 28)
        label_font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 20)
    except Exception:
        title_font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    draw.rectangle((0, 0, width - 1, height - 1), outline=(218, 226, 236), width=2)
    draw.text((margin_x, 18), f"{title}  |  composed question canvas", fill=(20, 40, 70), font=title_font)
    y = title_h
    for item in loaded:
        img = item["image"]
        bbox = item["bbox_px"]
        x = margin_x + max(0, bbox[0] - x0_min)
        x = min(max(margin_x, x), max(margin_x, width - margin_x - img.width))
        page = item.get("page")
        role = item.get("role") or "fragment"
        label = f"fragment {item['index']:02d}"
        if page:
            label += f" | page {int(page):03d}"
        label += f" | {role}"
        draw.rounded_rectangle((margin_x, y, width - margin_x, y + label_h), radius=8, fill=(245, 248, 252), outline=(224, 231, 240))
        draw.text((margin_x + 12, y + 5), label, fill=(72, 91, 118), font=label_font)
        y += label_h
        canvas.paste(img, (x, y))
        draw.rectangle((x, y, x + img.width - 1, y + img.height - 1), outline=(210, 219, 232), width=1)
        y += img.height + gap
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=95)


def _role_from_crop_name(path: Path) -> str:
    stem = path.stem
    if "_p" not in stem:
        return "fragment"
    parts = stem.split("_")
    if len(parts) <= 3:
        return "fragment"
    return "_".join(parts[3:]) or "fragment"
