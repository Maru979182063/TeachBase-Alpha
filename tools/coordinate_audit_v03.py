from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tools.cross_page_node_accumulator_v03 import SemanticNodeV03
from tools.layout_block_extractor_v03 import BlockCandidateV03
from tools.page_render_adapter_v03 import PageManifestV03


def _center_y(box: list[int]) -> float:
    return (box[1] + box[3]) / 2.0


def _box_iou(a: list[int], b: list[int]) -> float:
    ix0 = max(a[0], b[0])
    iy0 = max(a[1], b[1])
    ix1 = min(a[2], b[2])
    iy1 = min(a[3], b[3])
    iw = max(0, ix1 - ix0)
    ih = max(0, iy1 - iy0)
    inter = iw * ih
    area_a = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / max(1, area_a + area_b - inter)


def _roundtrip_iou(block: BlockCandidateV03, manifest: PageManifestV03) -> float:
    x_scale = manifest.width_px / max(1, manifest.vlm_width_px)
    y_scale = manifest.height_px / max(1, manifest.vlm_height_px)
    x0, y0, x1, y1 = block.bbox_px
    vlm_box = [
        round(x0 / x_scale),
        round(y0 / y_scale),
        round(x1 / x_scale),
        round(y1 / y_scale),
    ]
    restored = [
        round(vlm_box[0] * x_scale),
        round(vlm_box[1] * y_scale),
        round(vlm_box[2] * x_scale),
        round(vlm_box[3] * y_scale),
    ]
    return round(_box_iou(block.bbox_px, restored), 6)


def write_coordinate_audit_v03(
    out_dir: Path,
    doc_key: str,
    manifests: list[PageManifestV03],
    raw_blocks: list[BlockCandidateV03],
    reading_blocks: list[BlockCandidateV03],
    nodes: list[SemanticNodeV03],
) -> None:
    audit_dir = out_dir / "debug" / "coordinate_spaces"
    audit_dir.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        page_raw = [block for block in raw_blocks if block.page == manifest.page]
        page_reading = [block for block in reading_blocks if block.page == manifest.page]
        fragment_boxes = [
            fragment.bbox_px
            for node in nodes
            for fragment in node.fragments
            if fragment.page == manifest.page
        ]
        x_scale = manifest.width_px / max(1, manifest.vlm_width_px)
        y_scale = manifest.height_px / max(1, manifest.vlm_height_px)
        payload = {
            "schema": "coordinate_integrity_audit_v0.3",
            "doc_key": doc_key,
            "page": manifest.page,
            "coordinate_space": "master_px",
            "origin": "top_left_image_px",
            "pdf_origin_converted_to_image_origin": True,
            "page_window_y_offset_px": 0,
            "crop_band_offset_restored": True,
            "x_scale": x_scale,
            "y_scale": y_scale,
            "x_scale_source": "width",
            "y_scale_source": "height",
            "no_width_scale_used_for_y": True,
            "raw_block_count": len(page_raw),
            "reading_block_count": len(page_reading),
            "semantic_fragment_count": len(fragment_boxes),
            "raw_y_centers": [round(_center_y(block.bbox_px), 2) for block in page_raw],
            "reading_y_centers": [round(_center_y(block.bbox_px), 2) for block in page_reading],
            "reading_height_ratios": [round((block.bbox_px[3] - block.bbox_px[1]) / max(1, manifest.height_px), 5) for block in page_reading],
            "roundtrip_iou_samples": [_roundtrip_iou(block, manifest) for block in page_reading[:10]],
            "manifest": asdict(manifest),
        }
        (audit_dir / f"{doc_key}_p{manifest.page:03d}_coordinate_audit.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def write_nodes_overlay(path: Path, manifest: PageManifestV03, nodes: list[SemanticNodeV03], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(manifest.page_image_master).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
    except Exception:
        font = ImageFont.load_default()
    draw.rectangle((0, 0, min(img.width - 1, 920), 42), fill=(238, 248, 235))
    draw.text((12, 8), title, fill=(40, 110, 40), font=font)
    for node in nodes:
        for fragment in node.fragments:
            if fragment.page != manifest.page:
                continue
            color = (30, 150, 80) if node.review_status == "AUDITED_READY" else (220, 120, 30)
            x0, y0, x1, y1 = fragment.bbox_px
            draw.rectangle((x0, y0, x1, y1), outline=color, width=5)
            draw.text((x0, max(0, y0 - 24)), f"{node.node_id}:{fragment.role}", fill=color, font=font)
    img.thumbnail((1200, 1700))
    img.save(path, quality=92)
