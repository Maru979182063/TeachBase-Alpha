from __future__ import annotations

import json
from pathlib import Path

from tools.classify_final_chain_surface import build_report


ROOT = Path(__file__).resolve().parents[1]


class Args:
    target_root: str
    target_root_label = "test"
    registry = str(ROOT / "config" / "final_chain_registry.yaml")
    docx_math_inventory = ""
    file_roots: list[str] | None = None
    directory_roots: list[str] | None = None
    directory_depth = 2
    sample_limit = 50


def test_surface_classifier_marks_protected_and_legacy_paths(tmp_path: Path) -> None:
    for rel in [
        "tools/run_question_ingest_skill.py",
        "tools/docx_math_pipeline_orchestrator_v01.py",
        "tools/english_text_first_probe_runner.py",
        "outputs/random_experiment",
    ]:
        path = tmp_path / rel
        if "." in path.name:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)

    args = Args()
    args.target_root = str(tmp_path)
    args.file_roots = ["tools"]
    args.directory_roots = ["outputs"]
    report = build_report(args)
    samples = [
        record
        for records in report["summary"]["samples_by_category"].values()
        for record in records
    ]
    by_path = {record["path"]: record for record in samples}
    assert by_path["tools/run_question_ingest_skill.py"]["category"] == "protected_final_chain_surface"
    assert by_path["tools/docx_math_pipeline_orchestrator_v01.py"]["category"] == "known_non_final_legacy"
    assert by_path["tools/english_text_first_probe_runner.py"]["category"] == "historical_or_probe_surface"
    assert by_path["outputs/random_experiment"]["category"] == "unregistered_output_surface"


def test_surface_classifier_can_use_docx_math_inventory(tmp_path: Path) -> None:
    protected_file = tmp_path / "tools" / "docx_math_extra_from_inventory.py"
    protected_file.parent.mkdir(parents=True)
    protected_file.write_text("x", encoding="utf-8")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"files": [{"path": "tools/docx_math_extra_from_inventory.py"}]}),
        encoding="utf-8",
    )

    args = Args()
    args.target_root = str(tmp_path)
    args.docx_math_inventory = str(inventory)
    args.file_roots = ["tools"]
    args.directory_roots = []
    report = build_report(args)
    samples = report["summary"]["samples_by_category"]["protected_final_chain_surface"]
    assert samples[0]["path"] == "tools/docx_math_extra_from_inventory.py"
    assert samples[0]["chain_id"] == "doc_math"
