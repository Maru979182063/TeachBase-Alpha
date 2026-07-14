from __future__ import annotations

from tools.semantic_role_adapter import adapt_semantic_roles
from tools.semantic_profile_config import load_semantic_profile_configs


def _profile() -> dict:
    return {
        "document_profile_id": "profile_fixture",
        "source_run_id": "run_fixture",
        "effective_profile": {"subject": "math"},
        "confidence": 0.9,
    }


def _payload(node: dict, status: str = "AUDITED_READY") -> tuple[dict, dict, dict]:
    semantic_nodes = {"schema": "semantic_nodes_v0.3", "nodes": [node]}
    reading_blocks = {"schema": "reading_blocks_v0.3", "blocks": []}
    audit_report = {"schema": "audit_report_v0.3", "records": [{"node_id": node["node_id"], "status": status, "reasons": []}]}
    return semantic_nodes, reading_blocks, audit_report


def test_legal_enum_and_question_splitter() -> None:
    node = {"node_id": "q001", "node_type": "question", "review_status": "AUDITED_READY", "text_stub": "1. 求函数值", "fragments": [{"role": "question_body", "flags": ["possible_question_start"], "block_ids": []}]}
    semantic_nodes, reading_blocks, audit_report = _payload(node)
    result, _ = adapt_semantic_roles(semantic_nodes=semantic_nodes, reading_blocks=reading_blocks, audit_report=audit_report, document_profile=_profile(), provider="mock")
    row = result["results"][0]
    assert row["semantic_role"] == "exercise"
    assert row["effective_route"] == "question_splitter"
    assert row["disposition"] == "processable"


def test_split_audit_non_ready_forces_structurally_blocked() -> None:
    node = {"node_id": "q002", "node_type": "question", "review_status": "NEEDS_REVIEW", "text_stub": "1. 求函数值", "fragments": [{"role": "question_body", "flags": ["possible_question_start"], "block_ids": []}]}
    semantic_nodes, reading_blocks, audit_report = _payload(node, status="NEEDS_REVIEW")
    result, _ = adapt_semantic_roles(semantic_nodes=semantic_nodes, reading_blocks=reading_blocks, audit_report=audit_report, document_profile=_profile(), provider="mock")
    row = result["results"][0]
    assert row["disposition"] == "structurally_blocked"
    assert row["effective_route"] == "review_only"


def test_answer_target_missing_forces_review() -> None:
    node = {"node_id": "a001", "node_type": "question", "review_status": "AUDITED_READY", "text_stub": "【答案】A 【解析】略", "fragments": [{"role": "answer_block", "flags": ["answer_like"], "block_ids": []}]}
    semantic_nodes, reading_blocks, audit_report = _payload(node)
    result, _ = adapt_semantic_roles(semantic_nodes=semantic_nodes, reading_blocks=reading_blocks, audit_report=audit_report, document_profile=_profile(), provider="mock")
    row = result["results"][0]
    assert row["semantic_role"] == "answer_explanation"
    assert row["effective_route"] == "review_only"
    assert row["needs_role_review"] is True


def test_planned_route_falls_back_to_review_only() -> None:
    node = {"node_id": "k001", "node_type": "knowledge_block", "review_status": "AUDITED_READY", "text_stub": "知识梳理：函数概念", "fragments": [{"role": "knowledge_body", "flags": ["knowledge_like"], "block_ids": []}]}
    semantic_nodes, reading_blocks, audit_report = _payload(node)
    result, _ = adapt_semantic_roles(semantic_nodes=semantic_nodes, reading_blocks=reading_blocks, audit_report=audit_report, document_profile=_profile(), provider="mock")
    row = result["results"][0]
    assert row["semantic_role"] == "knowledge"
    assert row["route_availability"] == "shadow_only"
    assert row["effective_route"] == "review_only"


def test_unknown_config_enum_guard() -> None:
    configs = load_semantic_profile_configs()
    assert "exercise" in configs["content_blocks.yaml"]["semantic_roles"]

