from tools.cross_page_node_accumulator_v03 import NodeFragmentV03, SemanticNodeV03
from tools.layout_block_extractor_v03 import BlockCandidateV03
from tools.page_render_adapter_v03 import PageManifestV03
import tools.split_v03_refine_review_nodes as refine_nodes
from PIL import Image
from tools.split_v03_refine_review_nodes import attach_continuation_candidates


def _manifest(page: int) -> PageManifestV03:
    return PageManifestV03(
        doc_key="demo",
        page=page,
        source_page=page,
        width_px=1000,
        height_px=2000,
        target_dpi=300,
        render_scale=1.0,
        provider="test",
        provider_detail="high",
        max_vlm_pixels=9_000_000,
        page_image_master=f"p{page}.png",
        page_image_vlm=f"p{page}_vlm.png",
        vlm_width_px=1000,
        vlm_height_px=2000,
        coordinate_space="master_px",
    )


def _block(block_id: str, page: int, box: list[int], flags: list[str]) -> BlockCandidateV03:
    return BlockCandidateV03(
        block_id=block_id,
        doc_key="demo",
        page=page,
        bbox_px=box,
        bbox_norm=[box[0] / 1000, box[1] / 2000, box[2] / 1000, box[3] / 2000],
        source="reading_block",
        text_stub=block_id,
        visual_features={},
        candidate_flags=flags,
    )


def test_continuation_finder_attaches_when_model_judges_attach(monkeypatch, tmp_path):
    node = SemanticNodeV03(
        node_id="demo_q_001",
        node_type="question",
        source="semantic_v03",
        fragments=[
            NodeFragmentV03(
                page=1,
                bbox_px=[100, 1700, 900, 1950],
                role="question_body",
                block_ids=["b1"],
                flags=["possible_question_start", "near_page_bottom"],
            )
        ],
        text_stub="question",
    )
    continuation = _block("b2", 2, [100, 120, 900, 360], ["page_top_continuation", "reading_block"])
    monkeypatch.setattr(refine_nodes, "_make_judge_image", lambda **kwargs: Image.new("RGB", (10, 10), "white"))
    monkeypatch.setattr(
        refine_nodes,
        "_call_continuation_judge",
        lambda **kwargs: {"decision": "attach", "role": "body_continuation", "confidence": 0.9, "reason": "same question"},
    )

    actions, calls, conflict_calls = attach_continuation_candidates(
        nodes=[node],
        reading_blocks=[continuation],
        reasons_by_node={"demo_q_001": ["page_bottom_may_continue"]},
        manifest_by_page={1: _manifest(1), 2: _manifest(2)},
        api_key="fake",
        model="fake",
        prompt_bundle={"system_prompt": "", "user_template": ""},
        conflict_prompt_bundle={"system_prompt": "", "user_template": ""},
        out_dir=tmp_path,
        max_calls=3,
    )

    assert actions[0]["action"] == "continuation_judge_attached"
    assert actions[0]["attached_block_ids"] == ["b2"]
    assert calls == 1
    assert conflict_calls == 0
    assert len(node.fragments) == 2
    assert node.fragments[1].role == "body_continuation"
    assert "continues_previous_page" in node.fragments[1].flags


def test_continuation_finder_does_not_attach_when_model_rejects(monkeypatch, tmp_path):
    node = SemanticNodeV03(
        node_id="demo_q_001",
        node_type="question",
        source="semantic_v03",
        fragments=[
            NodeFragmentV03(
                page=1,
                bbox_px=[100, 1700, 900, 1950],
                role="question_body",
                block_ids=["b1"],
                flags=["possible_question_start", "near_page_bottom"],
            )
        ],
        text_stub="question",
    )
    next_question = _block("b2", 2, [100, 120, 900, 360], ["possible_question_start", "reading_block"])
    monkeypatch.setattr(refine_nodes, "_make_judge_image", lambda **kwargs: Image.new("RGB", (10, 10), "white"))
    monkeypatch.setattr(
        refine_nodes,
        "_call_continuation_judge",
        lambda **kwargs: {"decision": "reject", "role": "body_continuation", "confidence": 0.9, "reason": "new question"},
    )

    actions, calls, conflict_calls = attach_continuation_candidates(
        nodes=[node],
        reading_blocks=[next_question],
        reasons_by_node={"demo_q_001": ["page_bottom_may_continue"]},
        manifest_by_page={1: _manifest(1), 2: _manifest(2)},
        api_key="fake",
        model="fake",
        prompt_bundle={"system_prompt": "", "user_template": ""},
        conflict_prompt_bundle={"system_prompt": "", "user_template": ""},
        out_dir=tmp_path,
        max_calls=3,
    )

    assert actions[0]["action"] == "continuation_judge_not_attached"
    assert actions[0]["search_reason"] == "next_page_candidates_found"
    assert calls == 1
    assert conflict_calls == 0
    assert len(node.fragments) == 1


def test_continuation_conflict_can_move_question_owned_candidate(monkeypatch, tmp_path):
    claimant = SemanticNodeV03(
        node_id="demo_q_001",
        node_type="question",
        source="semantic_v03",
        fragments=[
            NodeFragmentV03(
                page=1,
                bbox_px=[100, 1700, 900, 1950],
                role="question_body",
                block_ids=["b1"],
                flags=["possible_question_start", "near_page_bottom"],
            )
        ],
        text_stub="question tail",
    )
    original_owner = SemanticNodeV03(
        node_id="demo_q_002",
        node_type="question",
        source="semantic_v03",
        fragments=[
            NodeFragmentV03(
                page=2,
                bbox_px=[100, 120, 900, 520],
                role="question_body",
                block_ids=["b2"],
                flags=["no_visible_question_number", "reading_block"],
            )
        ],
        text_stub="headless question",
    )
    candidate = _block("b2", 2, [100, 120, 900, 520], ["no_visible_question_number", "reading_block"])
    monkeypatch.setattr(refine_nodes, "_make_judge_image", lambda **kwargs: Image.new("RGB", (10, 10), "white"))
    monkeypatch.setattr(refine_nodes, "_make_conflict_image", lambda **kwargs: Image.new("RGB", (10, 30), "white"))
    monkeypatch.setattr(
        refine_nodes,
        "_call_continuation_judge",
        lambda **kwargs: {"decision": "attach", "role": "body_continuation", "confidence": 0.95, "reason": "same question"},
    )
    monkeypatch.setattr(
        refine_nodes,
        "_call_ownership_conflict_judge",
        lambda **kwargs: {"decision": "move_to_claimant", "confidence": 0.95, "reason": "owner is headless duplicate"},
    )

    actions, calls, conflict_calls = attach_continuation_candidates(
        nodes=[claimant, original_owner],
        reading_blocks=[candidate],
        reasons_by_node={"demo_q_001": ["page_bottom_may_continue"]},
        manifest_by_page={1: _manifest(1), 2: _manifest(2)},
        api_key="fake",
        model="fake",
        prompt_bundle={"system_prompt": "", "user_template": ""},
        conflict_prompt_bundle={"system_prompt": "", "user_template": ""},
        out_dir=tmp_path,
        max_calls=3,
    )

    assert actions[0]["action"] == "continuation_judge_attached"
    assert actions[0]["attached_block_ids"] == ["b2"]
    assert calls == 1
    assert conflict_calls == 1
    assert len(claimant.fragments) == 2
    assert original_owner.fragments == []
