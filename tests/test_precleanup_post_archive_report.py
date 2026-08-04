from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from tools import build_precleanup_post_archive_report as post_archive


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _args(execution: Path, deep: Path) -> SimpleNamespace:
    return SimpleNamespace(execution_report=str(execution), deep_audit_report=str(deep))


def test_post_archive_report_verifies_moved_file_and_current_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_archive, "ROOT", tmp_path)
    payload = b"archived payload\n"
    target = tmp_path / "_archive" / "precleanup_20260804" / "docs" / "old.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    execution = {
        "ok": True,
        "dry_run": False,
        "moves": [
            {
                "source": "docs/old.md",
                "target": "_archive/precleanup_20260804/docs/old.md",
                "status": "moved",
                "before": {"kind": "file", "file_count": 1, "total_bytes": len(payload), "sha256": _sha256(payload)},
                "after": {"kind": "file", "file_count": 1, "total_bytes": len(payload), "sha256": _sha256(payload)},
            }
        ],
    }
    deep = {
        "archive_root": "_archive/precleanup_20260804",
        "ok_to_execute_allowed_archive_roots": False,
        "allowed_archive_roots": [],
        "blocked_roots": [
            {"path": "docs/old.md", "blockers": ["path_missing"]},
            {"path": "outputs/pipeline_baseline_snapshot", "blockers": ["referenced_by_repo"]},
        ],
    }
    execution_path = tmp_path / "execution.json"
    deep_path = tmp_path / "deep.json"
    _write_json(execution_path, execution)
    _write_json(deep_path, deep)

    report = post_archive.build_report(_args(execution_path, deep_path))

    assert report["ok"] is True
    assert report["report_phase"] == "post_archive_state_inspection"
    assert report["checks"]["all_move_inspections_ok"] is True
    assert report["checks"]["moved_sources_blocked_as_missing"] is True
    assert report["checks"]["baseline_snapshot_still_blocked_by_reference"] is True
    assert report["unexpected_archive_files"] == []
    assert report["missing_archive_files"] == []


def test_post_archive_report_fails_on_unexpected_archive_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_archive, "ROOT", tmp_path)
    target = tmp_path / "_archive" / "precleanup_20260804" / "docs" / "old.md"
    extra = tmp_path / "_archive" / "precleanup_20260804" / "docs" / "extra.md"
    target.parent.mkdir(parents=True)
    target.write_text("old\n", encoding="utf-8")
    extra.write_text("extra\n", encoding="utf-8")
    payload = b"old\n"
    execution = {
        "ok": True,
        "dry_run": False,
        "moves": [
            {
                "source": "docs/old.md",
                "target": "_archive/precleanup_20260804/docs/old.md",
                "status": "moved",
                "before": {"kind": "file", "file_count": 1, "total_bytes": len(payload), "sha256": _sha256(payload)},
                "after": {"kind": "file", "file_count": 1, "total_bytes": len(payload), "sha256": _sha256(payload)},
            }
        ],
    }
    deep = {
        "archive_root": "_archive/precleanup_20260804",
        "ok_to_execute_allowed_archive_roots": False,
        "allowed_archive_roots": [],
        "blocked_roots": [
            {"path": "docs/old.md", "blockers": ["path_missing"]},
            {"path": "outputs/pipeline_baseline_snapshot", "blockers": ["referenced_by_repo"]},
        ],
    }
    execution_path = tmp_path / "execution.json"
    deep_path = tmp_path / "deep.json"
    _write_json(execution_path, execution)
    _write_json(deep_path, deep)

    report = post_archive.build_report(_args(execution_path, deep_path))

    assert report["ok"] is False
    assert report["checks"]["no_unexpected_archive_files"] is False
    assert report["unexpected_archive_files"] == ["_archive/precleanup_20260804/docs/extra.md"]


def test_post_archive_report_fails_if_source_still_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(post_archive, "ROOT", tmp_path)
    source = tmp_path / "docs" / "old.md"
    target = tmp_path / "_archive" / "precleanup_20260804" / "docs" / "old.md"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("old\n", encoding="utf-8")
    target.write_text("old\n", encoding="utf-8")
    payload = b"old\n"
    execution = {
        "ok": True,
        "dry_run": False,
        "moves": [
            {
                "source": "docs/old.md",
                "target": "_archive/precleanup_20260804/docs/old.md",
                "status": "moved",
                "before": {"kind": "file", "file_count": 1, "total_bytes": len(payload), "sha256": _sha256(payload)},
                "after": {"kind": "file", "file_count": 1, "total_bytes": len(payload), "sha256": _sha256(payload)},
            }
        ],
    }
    deep = {
        "archive_root": "_archive/precleanup_20260804",
        "ok_to_execute_allowed_archive_roots": False,
        "allowed_archive_roots": [],
        "blocked_roots": [
            {"path": "docs/old.md", "blockers": ["path_missing"]},
            {"path": "outputs/pipeline_baseline_snapshot", "blockers": ["referenced_by_repo"]},
        ],
    }
    execution_path = tmp_path / "execution.json"
    deep_path = tmp_path / "deep.json"
    _write_json(execution_path, execution)
    _write_json(deep_path, deep)

    report = post_archive.build_report(_args(execution_path, deep_path))

    assert report["ok"] is False
    assert report["move_inspections"][0]["checks"]["source_missing_after_archive"] is False
