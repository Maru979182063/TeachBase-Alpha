from __future__ import annotations

import json
from pathlib import Path

from tools.page_render_adapter_v03 import PROVIDER_LIMITS
from tools.question_slice_auditor_v03 import audit_nodes_v03
from tools.cross_page_node_accumulator_v03 import NodeFragmentV03, SemanticNodeV03
from tools.semantic_block_assembler_v03 import mock_semantic_assignments_v03
from tools.layout_block_extractor_v03 import _tile_specs
from tools.page_render_adapter_v03 import PageManifestV03
from tools.split_pipeline_v03 import build_legacy_bridge


RECOVERY = Path("out/recovery")


def load_json(path: Path) -> dict:
    assert path.exists(), f"missing {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_visual_reviewed_v02_in_v03_outputs():
    text = (RECOVERY / "nodes" / "semantic_nodes.json").read_text(encoding="utf-8")
    assert "VISUAL_REVIEWED_V02" not in text


def test_no_orphan_merge_outputs():
    text = (RECOVERY / "recovery_report.json").read_text(encoding="utf-8") + (RECOVERY / "nodes" / "semantic_nodes.json").read_text(encoding="utf-8")
    assert "ORPHAN_MERGE" not in text


def test_page_render_adapter_respects_max_pixels():
    data = load_json(RECOVERY / "page_manifests.json")
    assert data["pages"]
    for page in data["pages"]:
        assert page["vlm_width_px"] * page["vlm_height_px"] <= page["max_vlm_pixels"]
        assert page["target_dpi"] >= 300
        assert page["render_scale"] > 1.6


def test_doubao_detail_high_configured():
    assert PROVIDER_LIMITS["doubao"]["detail"] == "high"
    data = load_json(RECOVERY / "page_manifests.json")
    assert all(page["provider_detail"] == "high" for page in data["pages"])


def test_preflight_classifies_english_as_image_pdf():
    data = load_json(RECOVERY / "preflight_report.json")
    english = next(doc for doc in data["documents"] if doc["doc_key"] == "english")
    assert english["classification"] != "good_text_pdf"


def test_block_candidate_schema_complete():
    data = load_json(RECOVERY / "blocks" / "blocks.json")
    assert data["blocks"]
    required = {"block_id", "page", "bbox_px", "bbox_norm", "source", "text_stub", "visual_features", "candidate_flags"}
    for block in data["blocks"][:20]:
        assert required <= set(block)


def test_english_pages_have_ocr_blocks():
    data = load_json(RECOVERY / "blocks" / "blocks.json")
    assert any(block["doc_key"] == "english" and "ocr" in block["source"] for block in data["blocks"])


def test_semantic_assembler_output_has_no_crop_bbox():
    data = load_json(RECOVERY / "nodes" / "semantic_nodes.json")
    dumped = json.dumps(data, ensure_ascii=False)
    assert "crop_bbox" not in dumped
    assert "final_bbox" not in dumped


def test_node_fragment_schema_supports_multi_page():
    data = load_json(RECOVERY / "nodes" / "semantic_nodes.json")
    assert any(len(node["fragments"]) > 1 for node in data["nodes"])
    fragment = next(node["fragments"][0] for node in data["nodes"] if node["fragments"])
    assert {"page", "bbox_px", "role", "block_ids"} <= set(fragment)


def test_accumulator_attaches_top_page_solution_to_open_question():
    data = load_json(RECOVERY / "debug" / "open_node_trace.json")
    assert any(event["event"] == "attach_to_existing" for event in data["events"])


def test_orphan_goes_to_quarantine_not_merge():
    data = load_json(RECOVERY / "nodes" / "semantic_nodes.json")
    assert any(node["node_type"] == "quarantined_orphan" for node in data["nodes"])
    assert "ORPHAN_MERGE" not in json.dumps(data, ensure_ascii=False)


def test_auditor_rejects_only_solution_without_question():
    fake = SemanticNodeV03("fake", "question", "test", [NodeFragmentV03(1, [0, 0, 10, 10], "answer_block", ["b1"])])
    record = audit_nodes_v03([fake])[0]
    assert record.status != "AUDITED_READY"
    assert "missing_stem" in record.reasons or "only_solution_without_question" in record.reasons


def test_auditor_rejects_mixed_next_question():
    fake = SemanticNodeV03("fake", "question", "test", [NodeFragmentV03(1, [0, 0, 10, 10], "question_body", ["b1"])])
    fake.text_stub = "【练1】 A\n【练2】 B"
    record = audit_nodes_v03([fake])[0]
    assert record.status != "AUDITED_READY"
    assert "mixed_next_node" in record.reasons


def test_auditor_rejects_visual_coverage_incomplete():
    fake = SemanticNodeV03(
        "fake",
        "question",
        "test",
        [NodeFragmentV03(1, [0, 0, 100, 120], "question_body", ["b1"], ["visual_coverage_incomplete"])],
    )
    record = audit_nodes_v03([fake])[0]
    assert record.status != "AUDITED_READY"
    assert "visual_coverage_incomplete" in record.reasons


def test_visual_rescan_tiles_target_missing_lower_region():
    manifest = PageManifestV03(
        doc_key="english",
        page=6,
        source_page=6,
        width_px=2480,
        height_px=3507,
        target_dpi=300,
        render_scale=300 / 72,
        provider="doubao",
        provider_detail="high",
        max_vlm_pixels=9_000_000,
        page_image_master="master.png",
        page_image_vlm="vlm.png",
        vlm_width_px=2480,
        vlm_height_px=3507,
    )
    tiles = _tile_specs(
        manifest,
        coverage={
            "max_visual_y": 725,
            "ink": {"max_y": 3196},
        },
    )
    assert 1 <= len(tiles) <= 2
    assert tiles[0]["y0"] > 0
    assert tiles[-1]["y1"] > int(manifest.vlm_height_px * 0.70)


def test_legacy_bridge_only_exports_audited_ready_questions():
    data = load_json(RECOVERY / "legacy_bridge_questions.json")
    assert all(q["review_status"] == "AUDITED_READY" and q["node_type"] == "question" for q in data["questions"])


def test_legacy_bridge_uses_composite_first_question_image():
    nodes = [
        {
            "node_id": "q_demo",
            "node_type": "question",
            "review_status": "AUDITED_READY",
            "fragments": [{"page": 1, "bbox_px": [10, 20, 300, 400], "role": "question_body", "block_ids": ["b1"], "flags": []}],
        }
    ]
    crop_records = {
        "q_demo": {
            "review_canvas": "crops/q_demo/review_canvas.png",
            "question_composite": "crops/q_demo/question_composite.png",
            "fragment_records": [{"path": "crops/q_demo/fragment_01.png", "page": 1, "role": "question_body", "bbox_px": [10, 20, 300, 400]}],
        }
    }
    bridge = build_legacy_bridge(nodes, crop_records)
    question = bridge["questions"][0]
    assert bridge["schema"] == "legacy_bridge_questions_v0.4_composite_first"
    assert question["question_image"] == "crops/q_demo/question_composite.png"
    assert question["stem_image"] == question["question_image"]
    assert question["gating_result"]["image_input_policy"] == "composite_first"
    assert question["staged_visual_assets"][0]["attach_status"] == "evidence_only"
