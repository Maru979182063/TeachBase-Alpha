from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from teachbase.core.errors import ConfigurationError
from teachbase.core.run_context import utc_now_iso
from teachbase.infrastructure.artifact_store import read_json, write_json

SCHEDULED_READY = "scheduled_ready"
SCHEDULED_BLOCKED = "scheduled_blocked"
REJECTED = "rejected"
DRY_RUN_STARTED = "dry_run_started"
DRY_RUN_PASSED = "dry_run_passed"
DRY_RUN_FAILED = "dry_run_failed"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({SCHEDULED_BLOCKED, REJECTED, DRY_RUN_PASSED, DRY_RUN_FAILED, CANCELLED})

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCHEDULED_READY: (DRY_RUN_STARTED, CANCELLED),
    SCHEDULED_BLOCKED: (),
    REJECTED: (),
    DRY_RUN_STARTED: (DRY_RUN_PASSED, DRY_RUN_FAILED, CANCELLED),
    DRY_RUN_PASSED: (),
    DRY_RUN_FAILED: (),
    CANCELLED: (),
}


def build_job_lifecycle(status: str, *, created_at: str, reason: str = "scheduled") -> dict[str, Any]:
    _require_known_status(status)
    return {
        "schema_version": "final_chain_job_lifecycle.v0.1",
        "status": status,
        "state_version": 1,
        "terminal": status in TERMINAL_STATUSES,
        "allowed_next_statuses": list(ALLOWED_TRANSITIONS[status]),
        "updated_at": created_at,
        "history": [
            {
                "version": 1,
                "status": status,
                "at": created_at,
                "reason": reason,
                "checkpoint": None,
            }
        ],
    }


def inspect_job_record(record: dict[str, Any]) -> dict[str, Any]:
    status = str(record.get("status") or "")
    _require_known_status(status)
    lifecycle = record.get("lifecycle")
    lifecycle_status = lifecycle.get("status") if isinstance(lifecycle, dict) else ""
    return {
        "schema_version": "final_chain_job_inspection.v0.1",
        "job_id": str(record.get("job_id") or ""),
        "chain_id": str(record.get("chain_id") or ""),
        "status": status,
        "lifecycle_status": lifecycle_status,
        "status_consistent": lifecycle_status in {"", status},
        "terminal": status in TERMINAL_STATUSES,
        "allowed_next_statuses": list(ALLOWED_TRANSITIONS[status]),
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def transition_job_record(
    record: dict[str, Any],
    target_status: str,
    *,
    reason: str,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_known_status(target_status)
    current_status = str(record.get("status") or "")
    _require_known_status(current_status)
    allowed = ALLOWED_TRANSITIONS[current_status]
    if target_status not in allowed:
        raise ConfigurationError(
            "final_chain_job_invalid_transition",
            f"Cannot transition final-chain job from {current_status} to {target_status}",
        )

    now = utc_now_iso()
    updated = deepcopy(record)
    lifecycle = updated.get("lifecycle")
    if not isinstance(lifecycle, dict):
        lifecycle = build_job_lifecycle(current_status, created_at=str(updated.get("created_at") or now))
    history = lifecycle.get("history")
    if not isinstance(history, list):
        history = []
    version = int(lifecycle.get("state_version") or len(history) or 1) + 1
    event = {
        "version": version,
        "status": target_status,
        "at": now,
        "reason": reason,
        "checkpoint": _portable_checkpoint(checkpoint),
    }
    history.append(event)
    lifecycle.update(
        {
            "status": target_status,
            "state_version": version,
            "terminal": target_status in TERMINAL_STATUSES,
            "allowed_next_statuses": list(ALLOWED_TRANSITIONS[target_status]),
            "updated_at": now,
            "history": history,
        }
    )
    updated["status"] = target_status
    updated["updated_at"] = now
    updated["lifecycle"] = lifecycle
    updated["execution_contract"] = {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    return updated


def load_job_record(path: Path) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except FileNotFoundError as exc:
        raise ConfigurationError("final_chain_job_record_missing", "Job record does not exist") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("final_chain_job_record_not_object", "Job record is not an object")
    return payload


def inspect_job_record_path(path: Path) -> dict[str, Any]:
    return inspect_job_record(load_job_record(path))


def transition_job_record_path(
    path: Path,
    target_status: str,
    *,
    reason: str,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = transition_job_record(load_job_record(path), target_status, reason=reason, checkpoint=checkpoint)
    write_json(path, updated)
    return updated


def _require_known_status(status: str) -> None:
    if status not in ALLOWED_TRANSITIONS:
        raise ConfigurationError("final_chain_job_unknown_status", f"Unknown final-chain job status: {status}")


def _portable_checkpoint(checkpoint: dict[str, Any] | None) -> dict[str, Any] | None:
    if checkpoint is None:
        return None
    portable: dict[str, Any] = {}
    for key, value in checkpoint.items():
        if isinstance(value, Path):
            portable[key] = value.as_posix()
        else:
            portable[key] = value
    return portable
