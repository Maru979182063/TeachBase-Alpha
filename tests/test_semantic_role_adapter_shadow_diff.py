from __future__ import annotations

import json
from pathlib import Path

from tools.run_semantic_role_adapter_shadow import run_shadow


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_shadow_runner_writes_only_sidecar_outputs(tmp_path: Path) -> None:
    doc_dir = tmp_path / "docs" / "fixture"
    _write(
        doc_dir / "semantic_nodes.json",
        {
            "schema": "semantic_nodes_v0.3",
            "nodes": [
                {"node_id": "q001", "node_type": "question", "review_status": "AUDITED_READY", "text_stub": "1. 求函数值", "fragments": [{"page": 1, "bbox_px": [0, 0, 10, 10], "role": "question_body", "block_ids": [], "flags": ["possible_question_start"]}]}
            ],
        },
    )
    _write(doc_dir / "reading_blocks.json", {"schema": "reading_blocks_v0.3", "blocks": []})
    _write(doc_dir / "audit_report.json", {"schema": "audit_report_v0.3", "records": [{"node_id": "q001", "status": "AUDITED_READY", "reasons": []}]})
    _write(doc_dir / "page_manifests.json", {"schema": "page_manifests_v0.3", "pages": []})
    bridge = tmp_path / "legacy_bridge_questions.json"
    repair = tmp_path / "review_repair_pool.json"
    _write(bridge, {"questions": []})
    _write(repair, {"items": []})
    summary = run_shadow(doc_dir=doc_dir, out_dir=tmp_path / "shadow", provider="mock", doc_key="fixture", baseline_files=[doc_dir / "semantic_nodes.json", bridge, repair])
    assert Path(summary["artifacts"]["adapter_results"]).exists()
    assert summary["non_interference"]["all_baseline_hashes_equal"] is True
    diff = json.loads(Path(summary["artifacts"]["diff_report"]).read_text(encoding="utf-8"))
    assert diff["rows"][0]["new_semantic_role"] == "exercise"

