from __future__ import annotations

import json
from pathlib import Path


RECOVERY = Path("out/recovery")
GOLDEN = Path("tests/fixtures/split_v03_golden_cases.yml")


def load_json(path: Path) -> dict:
    assert path.exists(), f"missing {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def golden_cases() -> list[dict]:
    return load_json(GOLDEN)["cases"]


def nodes() -> list[dict]:
    return load_json(RECOVERY / "nodes" / "semantic_nodes.json")["nodes"]


def blocks() -> list[dict]:
    return load_json(RECOVERY / "blocks" / "blocks.json")["blocks"]


def test_math_golden_cases():
    math_cases = [case for case in golden_cases() if case["doc"] == "math"]
    math_nodes = [node for node in nodes() if node["node_id"].startswith("math_")]
    assert math_cases
    assert any(node["node_type"] == "question" for node in math_nodes)
    assert any(len(node["fragments"]) > 1 for node in math_nodes)


def test_english_golden_cases():
    english_cases = [case for case in golden_cases() if case["doc"] == "english"]
    english_nodes = [node for node in nodes() if node["node_id"].startswith("english_")]
    report = load_json(RECOVERY / "preflight_report.json")
    english_preflight = next(doc for doc in report["documents"] if doc["doc_key"] == "english")
    assert english_cases
    assert english_preflight["classification"] != "good_text_pdf"
    assert any(node["node_type"] == "question" for node in english_nodes)
    assert any(block["doc_key"] == "english" and "ocr" in block["source"] for block in blocks())


def test_biology_golden_cases():
    biology_cases = [case for case in golden_cases() if case["doc"] == "biology"]
    biology_nodes = [node for node in nodes() if node["node_id"].startswith("biology_")]
    assert biology_cases
    assert any(node["node_type"] == "question" for node in biology_nodes)
    assert any(node["node_type"] in {"knowledge_block", "quarantined_orphan"} for node in biology_nodes)


def test_all_golden_cases_have_debug_artifacts():
    overlay_root = RECOVERY / "debug" / "blocks_overlay"
    assert overlay_root.exists()
    for doc in {"math", "english", "biology"}:
        assert list((overlay_root / doc).glob("*_blocks_overlay.png")), f"missing overlay for {doc}"


def test_all_ready_nodes_have_audit_record():
    audit = load_json(RECOVERY / "audit" / "audit_report.json")["records"]
    audit_by_id = {item["node_id"]: item for item in audit}
    for node in nodes():
        if node["review_status"] == "AUDITED_READY":
            assert node["node_id"] in audit_by_id
            assert audit_by_id[node["node_id"]]["status"] == "AUDITED_READY"
