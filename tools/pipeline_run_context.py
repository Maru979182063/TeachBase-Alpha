from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id(prefix: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in prefix).strip("_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe or 'pipeline'}_{stamp}_{uuid.uuid4().hex[:8]}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def create_output_dir(root: Path, run_id: str) -> Path:
    out_dir = root / run_id
    if out_dir.exists():
        raise FileExistsError(f"pipeline_run_output_exists:{out_dir}")
    out_dir.mkdir(parents=True)
    return out_dir


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def environment_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "pipeline_environment_snapshot.v0.1",
        "captured_at": utc_now_iso(),
        "python_executable": os.sys.executable,
        "environment_variable_names": sorted(os.environ.keys()),
        "secret_values_recorded": False,
    }


def start_manifest(
    *,
    pipeline_id: str,
    pipeline_version: str,
    run_id: str,
    output_root: Path,
    command: list[str],
    config_path: Path | None = None,
    feature_flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    config_hash = sha256_file(config_path) if config_path and config_path.exists() else ""
    return {
        "schema_version": "pipeline_run_manifest.v0.1",
        "pipeline_id": pipeline_id,
        "pipeline_version": pipeline_version,
        "run_id": run_id,
        "parent_run_id": "",
        "started_at": utc_now_iso(),
        "finished_at": "",
        "duration_seconds": None,
        "status": "running",
        "git_commit": _git(["rev-parse", "HEAD"]),
        "git_branch": _git(["branch", "--show-current"]),
        "dirty_worktree": bool(_git(["status", "--porcelain"])),
        "input_files": [],
        "input_sha256": {},
        "entrypoint": command[0] if command else "",
        "command": command,
        "config_path": str(config_path) if config_path else "",
        "config_sha256": config_hash,
        "prompt_bundle": "",
        "prompt_version": "",
        "model_provider": "",
        "model_id": "",
        "model_parameters": {},
        "dependency_snapshot_id": "",
        "environment_snapshot_id": "",
        "feature_flags": feature_flags or {},
        "output_root": str(output_root),
        "output_files": [],
        "output_sha256": {},
        "metrics": {},
        "warnings": [],
        "errors": [],
        "fallback_used": False,
        "fallback_reason": "",
        "downstream_candidates": [],
        "runtime_import_attempted": False,
        "database_write_attempted": False,
        "release_decision": "",
        "created_by": "pipeline_run_context",
    }


def finish_manifest(manifest: dict[str, Any], *, status: str, output_files: list[Path] | None = None, errors: list[str] | None = None) -> dict[str, Any]:
    finished = utc_now_iso()
    manifest["finished_at"] = finished
    manifest["status"] = status
    if errors:
        manifest["errors"] = list(errors)
    files = output_files or []
    manifest["output_files"] = [str(path) for path in files]
    manifest["output_sha256"] = {str(path): sha256_file(path) for path in files if path.exists() and path.is_file()}
    try:
        started = datetime.fromisoformat(str(manifest.get("started_at")))
        done = datetime.fromisoformat(finished)
        manifest["duration_seconds"] = (done - started).total_seconds()
    except Exception:
        manifest["duration_seconds"] = None
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
