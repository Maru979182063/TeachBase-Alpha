from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools import build_precleanup_deep_audit as deep_audit
from tools import execute_precleanup_archive as archive


def _candidate(path: str) -> dict[str, str]:
    return {
        "path": path,
        "kind": "file",
        "category": "historical_or_probe_surface",
        "reason": "test cleanup candidate",
        "risk": "low",
        "proposed_action": "archive_candidate",
    }


def _audit_report(items: list[dict[str, str]]) -> dict[str, object]:
    return {
        "ok_to_execute_allowed_archive_roots": True,
        "archive_root": "_archive/precleanup_20260804",
        "allowed_archive_roots": items,
    }


def test_deep_audit_marks_authorization_snapshot_and_capped_reference_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(deep_audit, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "reports").mkdir(parents=True)
    (tmp_path / "docs" / "old_note.md").write_text("old content\n", encoding="utf-8")
    cleanup_report = {
        "samples_by_action": {"archive_candidate": [_candidate("docs/old_note.md")]},
        "counts_by_risk": {"review": 0},
    }
    classification = {"records": []}
    safety = {"ok": True}
    (tmp_path / "cleanup.json").write_text(json.dumps(cleanup_report), encoding="utf-8")
    (tmp_path / "classification.json").write_text(json.dumps(classification), encoding="utf-8")
    (tmp_path / "safety.json").write_text(json.dumps(safety), encoding="utf-8")
    (tmp_path / "docs" / "reports" / "cleanup_candidates_test.json").write_text(
        "docs/old_note.md\n",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        cleanup_report="cleanup.json",
        classification_report="classification.json",
        safety_report="safety.json",
        scan_roots=["docs"],
        max_reference_hits=1,
    )

    report = deep_audit.build_report(args)
    item = report["allowed_archive_roots"][0]

    assert report["report_phase"] == "pre_execution_authorization_snapshot"
    assert report["post_execution_state_report"] is False
    assert item["reference_count_capped"] == 1
    assert item["reference_scan_hit_limit"] == 1
    assert item["reference_scan_truncated"] is True
    assert item["blocking_reference_count_capped"] == 0
    assert item["generated_report_reference_count_capped"] == 1


def test_deep_audit_without_safety_report_remains_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(deep_audit, "ROOT", tmp_path)
    cleanup = tmp_path / "cleanup.json"
    classification = tmp_path / "classification.json"
    _missing_safety = tmp_path / "missing-safety.json"
    cleanup.write_text(json.dumps({"samples_by_action": {}, "counts_by_risk": {}}), encoding="utf-8")
    classification.write_text(json.dumps({"records": []}), encoding="utf-8")

    args = SimpleNamespace(
        cleanup_report=str(cleanup),
        classification_report=str(classification),
        safety_report=str(_missing_safety),
        scan_roots=[],
        max_reference_hits=1,
    )

    report = deep_audit.build_report(args)

    assert report["precleanup_safety_ok"] is False
    assert report["ok_to_execute_allowed_archive_roots"] is False
    assert report["allowed_archive_roots"] == []


def test_deep_audit_blocks_regular_repository_references(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(deep_audit, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "old_note.md").write_text("old content\n", encoding="utf-8")
    (tmp_path / "docs" / "live_runbook.md").write_text("keep docs/old_note.md wired\n", encoding="utf-8")

    item = deep_audit.audit_candidate(_candidate("docs/old_note.md"), [], ["docs"], 5)

    assert item["decision"] == "blocked_needs_review"
    assert item["blocking_reference_count_capped"] == 1
    assert item["blockers"] == ["referenced_by_repo"]


def test_archive_prevalidation_blocks_all_moves_before_filesystem_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "safe.md").write_text("safe\n", encoding="utf-8")
    valid = {
        **_candidate("docs/safe.md"),
        "decision": "archive_allowed",
        "archive_target": "_archive/precleanup_20260804/docs/safe.md",
    }
    missing = {
        **_candidate("docs/missing.md"),
        "decision": "archive_allowed",
        "archive_target": "_archive/precleanup_20260804/docs/missing.md",
    }

    result = archive.execute_archive(_audit_report([valid, missing]), dry_run=False)

    assert result["ok"] is False
    assert result["error"] == "prevalidation_failed"
    assert result["errors"][0]["source"] == "docs/missing.md"
    assert (tmp_path / "docs" / "safe.md").exists()
    assert not (tmp_path / "_archive" / "precleanup_20260804" / "docs" / "safe.md").exists()
    assert result["moves"][0]["status"] == "not_started_due_to_prevalidation_error"


def test_archive_rejects_targets_outside_declared_archive_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "safe.md").write_text("safe\n", encoding="utf-8")
    item = {
        **_candidate("docs/safe.md"),
        "decision": "archive_allowed",
        "archive_target": "_archive/other/docs/safe.md",
    }

    result = archive.execute_archive(_audit_report([item]), dry_run=True)

    assert result["ok"] is False
    assert result["errors"][0]["validation_errors"] == ["target_outside_archive_root"]


def test_archive_rolls_back_completed_moves_after_later_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "first.md").write_text("first\n", encoding="utf-8")
    (tmp_path / "docs" / "second.md").write_text("second\n", encoding="utf-8")
    first = {
        **_candidate("docs/first.md"),
        "decision": "archive_allowed",
        "archive_target": "_archive/precleanup_20260804/docs/first.md",
    }
    second = {
        **_candidate("docs/second.md"),
        "decision": "archive_allowed",
        "archive_target": "_archive/precleanup_20260804/docs/second.md",
    }
    real_move = archive.shutil.move
    calls = {"count": 0}

    def flaky_move(source: str, target: str) -> str:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("synthetic move failure")
        return real_move(source, target)

    monkeypatch.setattr(archive.shutil, "move", flaky_move)

    result = archive.execute_archive(_audit_report([first, second]), dry_run=False)

    assert result["ok"] is False
    assert result["rollback_attempted"] is True
    assert (tmp_path / "docs" / "first.md").exists()
    assert (tmp_path / "docs" / "second.md").exists()
    assert not (tmp_path / "_archive" / "precleanup_20260804" / "docs" / "first.md").exists()
    assert result["moves"][0]["rollback_status"] == "restored_source"
    assert result["moves"][1]["status"] == "move_failed"
