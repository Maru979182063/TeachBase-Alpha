from __future__ import annotations

import json
from pathlib import Path


RECOVERY = Path("out/recovery")


def load_json(path: Path) -> dict:
    assert path.exists(), f"missing {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def english_page(page: int) -> dict:
    return load_json(RECOVERY / "debug" / "coordinate_spaces" / f"english_p{page:03d}_coordinate_audit.json")


def raw_blocks(page: int) -> list[dict]:
    blocks = load_json(RECOVERY / "blocks" / "blocks.json")["blocks"]
    return [block for block in blocks if block["doc_key"] == "english" and block["page"] == page]


def reading_blocks(page: int) -> list[dict]:
    blocks = load_json(RECOVERY / "reading_blocks" / "reading_blocks.json")["blocks"]
    return [block for block in blocks if block["doc_key"] == "english" and block["page"] == page]


def semantic_fragments(page: int) -> list[dict]:
    nodes = load_json(RECOVERY / "nodes" / "semantic_nodes.json")["nodes"]
    return [
        fragment
        for node in nodes
        if node["node_type"] == "question" and node["node_id"].startswith("english_")
        for fragment in node.get("fragments", [])
        if fragment["page"] == page
    ]


def test_bbox_has_declared_coordinate_space():
    manifests = load_json(RECOVERY / "page_manifests.json")["pages"]
    assert manifests
    assert all(page["coordinate_space"] == "master_px" for page in manifests)
    for block in reading_blocks(6):
        assert block["visual_features"]["coordinate_space"] == "master_px"


def test_vlm_to_master_roundtrip_iou():
    audit = english_page(6)
    samples = audit["roundtrip_iou_samples"]
    assert samples
    assert min(samples) >= 0.98


def test_page_window_y_offset_for_page6():
    audit = english_page(6)
    assert audit["page_window_y_offset_px"] == 0
    assert audit["coordinate_space"] == "master_px"


def test_crop_band_offset_restored():
    audit = english_page(6)
    assert audit["crop_band_offset_restored"] is True
    height = audit["manifest"]["height_px"]
    for fragment in semantic_fragments(6):
        y0, y1 = fragment["bbox_px"][1], fragment["bbox_px"][3]
        assert 0 <= y0 < y1 <= height


def test_no_width_scale_used_for_y():
    audit = english_page(6)
    assert audit["no_width_scale_used_for_y"] is True
    assert audit["x_scale_source"] == "width"
    assert audit["y_scale_source"] == "height"


def test_pdf_origin_converted_to_image_origin():
    audit = english_page(6)
    assert audit["origin"] == "top_left_image_px"
    assert audit["pdf_origin_converted_to_image_origin"] is True


def test_page6_blocks_vertical_coverage():
    audit = english_page(6)
    centers = audit["reading_y_centers"]
    height = audit["manifest"]["height_px"]
    assert len(centers) >= 4
    assert min(centers) < height * 0.25
    assert max(centers) > height * 0.50
    occupied_bands = {min(3, int(center / height * 4)) for center in centers}
    assert len(occupied_bands) >= 3
    assert audit["reading_block_count"] < audit["raw_block_count"]


def test_reading_blocks_are_not_raw_line_boxes():
    raw = raw_blocks(6)
    reading = reading_blocks(6)
    assert len(raw) > len(reading)
    raw_heights = sorted(block["bbox_px"][3] - block["bbox_px"][1] for block in raw)
    assert raw_heights
    median_raw_height = raw_heights[len(raw_heights) // 2]
    for block in reading:
        height = block["bbox_px"][3] - block["bbox_px"][1]
        assert height >= median_raw_height * 1.5
    for fragment in semantic_fragments(6):
        height = fragment["bbox_px"][3] - fragment["bbox_px"][1]
        assert height >= median_raw_height * 1.5


def test_legacy_bridge_questions_are_audited_ready_only():
    bridge = load_json(RECOVERY / "legacy_bridge_questions.json")
    assert bridge["questions"]
    assert all(item["review_status"] == "AUDITED_READY" and item["node_type"] == "question" for item in bridge["questions"])
