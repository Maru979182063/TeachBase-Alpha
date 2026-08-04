from __future__ import annotations

import json
from pathlib import Path

from tools.build_cleanup_candidate_report import build_report


class Args:
    classification: str
    target_root: str
    scan_roots: list[str] | None = None
    scan_references = True
    max_reference_hits = 5
    sample_limit = 20
    include_absolute_target_root = False


def test_cleanup_candidates_are_non_destructive_and_reference_aware(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "outputs" / "probe_run").mkdir(parents=True)
    (tmp_path / "tools" / "old_probe.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "docs" / "note.md").write_text("tools/old_probe.py\n", encoding="utf-8")
    classification = {
        "target_root_label": "test",
        "summary": {
            "samples_by_category": {
                "historical_or_probe_surface": [
                    {
                        "path": "tools/old_probe.py",
                        "kind": "file",
                        "category": "historical_or_probe_surface",
                        "chain_id": "",
                        "reason": "name contains historical marker(s): probe",
                    },
                    {
                        "path": "outputs/probe_run",
                        "kind": "directory",
                        "category": "historical_or_probe_surface",
                        "chain_id": "",
                        "reason": "name contains historical marker(s): probe",
                    },
                ],
                "protected_final_chain_surface": [
                    {
                        "path": "tools/run_question_ingest_skill.py",
                        "kind": "file",
                        "category": "protected_final_chain_surface",
                        "chain_id": "pdf_math",
                        "reason": "protected",
                    }
                ],
            }
        },
    }
    classification_path = tmp_path / "classification.json"
    classification_path.write_text(json.dumps(classification), encoding="utf-8")

    args = Args()
    args.classification = str(classification_path)
    args.target_root = str(tmp_path)
    args.scan_roots = ["tools", "docs"]
    report = build_report(args)

    assert report["candidate_count"] == 2
    assert report["counts_by_action"]["needs_review_referenced"] == 1
    assert report["counts_by_action"]["archive_candidate"] == 1
    assert report["target_root_observed"] == ""


def test_cleanup_candidates_treat_finalish_names_as_review(tmp_path: Path) -> None:
    classification = {
        "target_root_label": "test",
        "summary": {
            "samples_by_category": {
                "finalish_name_needs_review": [
                    {
                        "path": "outputs/final_package",
                        "kind": "directory",
                        "category": "finalish_name_needs_review",
                        "chain_id": "",
                        "reason": "name contains final-like marker(s): final",
                    }
                ]
            }
        },
    }
    classification_path = tmp_path / "classification.json"
    classification_path.write_text(json.dumps(classification), encoding="utf-8")

    args = Args()
    args.classification = str(classification_path)
    args.target_root = str(tmp_path)
    args.scan_references = False
    report = build_report(args)

    assert report["candidate_count"] == 1
    assert report["counts_by_action"]["needs_review_finalish_name"] == 1
