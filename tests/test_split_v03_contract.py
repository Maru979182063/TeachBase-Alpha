from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = WORKSPACE_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from tools.page_render_adapter_v03 import PROVIDER_LIMITS
from tools.question_slice_auditor_v03 import audit_nodes_v03
from tools.cross_page_node_accumulator_v03 import NodeFragmentV03, SemanticNodeV03
from tools.semantic_block_assembler_v03 import mock_semantic_assignments_v03
from tools.layout_block_extractor_v03 import _tile_specs
from tools.page_render_adapter_v03 import PageManifestV03
from tools.split_pipeline_v03 import build_legacy_bridge, build_review_repair_pool
from tools.assetize_question_images import build_records


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


def test_auditor_rejects_question_swallowing_next_section():
    question = SemanticNodeV03(
        "q1",
        "question",
        "test",
        [NodeFragmentV03(1, [100, 100, 900, 600], "question_body", ["b1"], ["possible_question_start"])],
    )
    section = SemanticNodeV03(
        "section",
        "knowledge_block",
        "test",
        [NodeFragmentV03(1, [120, 560, 880, 720], "section_heading", ["b2"], ["possible_section_heading"])],
    )
    records = audit_nodes_v03([question, section])
    q_record = next(record for record in records if record.node_id == "q1")
    assert q_record.status != "AUDITED_READY"
    assert "swallows_next_section" in q_record.reasons


def test_auditor_rejects_short_question_without_solution_evidence():
    question = SemanticNodeV03(
        "q_short",
        "question",
        "test",
        [NodeFragmentV03(1, [100, 1000, 900, 1280], "question_body", ["b1"], ["possible_question_start", "visible_question_number"])],
    )
    record = audit_nodes_v03([question])[0]
    assert record.status != "AUDITED_READY"
    assert "short_question_without_solution_evidence" in record.reasons


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


def test_review_repair_pool_preserves_non_ready_questions():
    nodes = [
        {
            "node_id": "q_ready",
            "node_type": "question",
            "review_status": "AUDITED_READY",
            "fragments": [{"page": 1, "bbox_px": [0, 0, 100, 100], "role": "question_body", "block_ids": ["b1"], "flags": []}],
        },
        {
            "node_id": "q_needs_review",
            "node_type": "question",
            "review_status": "NEEDS_REVIEW",
            "fragments": [{"page": 1, "bbox_px": [0, 120, 100, 220], "role": "question_body", "block_ids": ["b2"], "flags": []}],
        },
    ]
    crop_records = {
        "q_ready": {"question_composite": "crops/q_ready/question_composite.png"},
        "q_needs_review": {"question_composite": "crops/q_needs_review/question_composite.png"},
    }
    audit_records = [{"node_id": "q_needs_review", "status": "NEEDS_REVIEW", "reasons": ["swallows_next_section"]}]
    bridge = build_legacy_bridge(nodes, crop_records)
    repair_pool = build_review_repair_pool(nodes, crop_records, audit_records)
    assert [q["question_id"] for q in bridge["questions"]] == ["q_ready"]
    assert [item["question_id"] for item in repair_pool["items"]] == ["q_needs_review"]
    item = repair_pool["items"][0]
    assert item["auto_ingest_allowed"] is False
    assert item["gating_result"]["decision"] == "review_required"
    assert item["review_reasons"] == ["swallows_next_section"]


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
    assert bridge["schema"] == "legacy_bridge_questions_v0.5_composite_plus_fragments"
    assert question["question_image"].replace("\\", "/") == "crops/q_demo/question_composite.png"
    assert question["transcription_image"] == question["question_image"]
    assert question["stem_image"] == question["question_image"]
    assert question["bridge_contract"]["asset_source"] == "bridge_fragments"
    assert question["gating_result"]["image_input_policy"] == "composite_first"
    assert question["gating_result"]["asset_detection_source"] == "bridge_fragments"
    assert question["staged_visual_assets"] == []
    assert question["bridge_fragments"][0]["placement_scope"] == "evidence_only"
    assert question["bridge_fragments"][0]["coordinate_space"] == "page_master_px"


def test_assetize_copies_bridge_fragments_as_evidence_only(tmp_path):
    from PIL import Image

    composite = tmp_path / "composite.png"
    fragment = tmp_path / "fragment.png"
    Image.new("RGB", (80, 50), "white").save(composite)
    Image.new("RGB", (40, 30), "white").save(fragment)
    source_json = tmp_path / "source.json"
    source_json.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question_id": "q_demo",
                        "question_uid": "q_demo",
                        "question_image": str(composite),
                        "stem_image": str(composite),
                        "bridge_fragments": [
                            {
                                "fragment_id": "q_demo_fragment_01",
                                "fragment_image": str(fragment),
                                "role": "question_body",
                                "page": 1,
                                "bbox_px": [10, 20, 40, 30],
                                "coordinate_space": "page_master_px",
                                "placement_scope": "evidence_only",
                            }
                        ],
                        "staged_visual_assets": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    records = build_records(source_json, None, tmp_path / "asset_out", include_debug_paths=True)
    assets = records[0]["assets"]
    fragment_assets = [asset for asset in assets if asset.get("asset_role") == "question_fragment_evidence"]
    assert len(fragment_assets) == 1
    assert fragment_assets[0]["placement_scope"] == "evidence_only"
    assert fragment_assets[0]["file_status"] == "materialized"
    assert (tmp_path / "asset_out" / fragment_assets[0]["storage_key"]).exists()
