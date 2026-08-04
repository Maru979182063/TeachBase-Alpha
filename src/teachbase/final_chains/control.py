from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from teachbase.core.errors import ConfigurationError
from teachbase.core.run_context import generate_run_id, utc_now_iso
from teachbase.infrastructure.artifact_store import write_json
from .jobs import attach_job_record_validation, build_job_lifecycle, validate_job_record

PlanStatus = Literal["ready", "blocked"]


@dataclass(frozen=True)
class FinalChainDefinition:
    chain_id: str
    display_name: str
    input_format: str
    subject: str
    protection_status: str
    registry_readiness: str
    confidence: str
    canonical_entrypoint: str
    canonical_config_paths: tuple[str, ...] = ()
    smoke_status: str = ""
    runtime_import_default_enabled: bool = False
    database_write_default_enabled: bool = False
    model_calls_default_enabled: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalChainRegistry:
    schema_version: str
    selection_policy: dict[str, Any]
    chains: tuple[FinalChainDefinition, ...]

    def get(self, chain_id: str) -> FinalChainDefinition:
        for chain in self.chains:
            if chain.chain_id == chain_id:
                return chain
        raise ConfigurationError("unknown_final_chain", f"Unknown final chain: {chain_id}")


@dataclass(frozen=True)
class EnvironmentPolicy:
    name: str = "local_dry_run"
    allow_model_calls: bool = False
    allow_database_writes: bool = False
    allow_runtime_import: bool = False


@dataclass(frozen=True)
class ChainRunRequest:
    chain_id: str
    input_path: str
    output_root: str
    dry_run: bool = True
    environment: EnvironmentPolicy = field(default_factory=EnvironmentPolicy)


def _load_json_compatible_yaml(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            "final_chain_registry_not_json_compatible_yaml",
            f"Final chain registry must stay JSON-compatible YAML: {path}",
        ) from exc


def _chain_from_raw(raw: dict[str, Any]) -> FinalChainDefinition:
    runtime_policy = raw.get("runtime_import_policy") if isinstance(raw.get("runtime_import_policy"), dict) else {}
    database_policy = raw.get("database_write_policy") if isinstance(raw.get("database_write_policy"), dict) else {}
    smoke_status = raw.get("smoke_status") if isinstance(raw.get("smoke_status"), dict) else {}
    return FinalChainDefinition(
        chain_id=str(raw.get("chain_id") or ""),
        display_name=str(raw.get("display_name") or ""),
        input_format=str(raw.get("input_format") or ""),
        subject=str(raw.get("subject") or ""),
        protection_status=str(raw.get("protection_status") or ""),
        registry_readiness=str(raw.get("registry_readiness") or ""),
        confidence=str(raw.get("confidence") or ""),
        canonical_entrypoint=str(raw.get("canonical_entrypoint") or ""),
        canonical_config_paths=tuple(str(path) for path in raw.get("canonical_config_paths") or ()),
        smoke_status=str(smoke_status.get("status") or ""),
        runtime_import_default_enabled=runtime_policy.get("default_enabled") is True,
        database_write_default_enabled=database_policy.get("default_enabled") is True,
        model_calls_default_enabled=raw.get("model_calls_default_enabled") is True,
        raw=dict(raw),
    )


def load_final_chain_registry(path: Path) -> FinalChainRegistry:
    payload = _load_json_compatible_yaml(path)
    chains = payload.get("chains")
    if not isinstance(chains, list):
        raise ConfigurationError("final_chain_registry_missing_chains", f"Missing chains in {path}")
    return FinalChainRegistry(
        schema_version=str(payload.get("schema_version") or ""),
        selection_policy=payload.get("selection_policy") if isinstance(payload.get("selection_policy"), dict) else {},
        chains=tuple(_chain_from_raw(chain) for chain in chains if isinstance(chain, dict)),
    )


def _relative_path_state(workspace_root: Path, path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    absolute = path if path.is_absolute() else workspace_root / path
    return {
        "path": path_value,
        "exists": absolute.exists(),
        "kind": "directory" if absolute.is_dir() else "file" if absolute.is_file() else "missing",
    }


def _input_matches_format(input_path: str, input_format: str) -> bool:
    suffix = Path(input_path).suffix.lower().lstrip(".")
    return suffix == input_format.lower()


def _resolve_under_workspace(workspace_root: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else workspace_root / path


def _is_inside(path: Path, parent: Path) -> bool:
    resolved = path.resolve()
    parent_resolved = parent.resolve()
    return resolved == parent_resolved or parent_resolved in resolved.parents


def _is_under_outputs(workspace_root: Path, path: Path) -> bool:
    return _is_inside(path, workspace_root / "outputs")


def _portable_path(workspace_root: Path, path: Path) -> str:
    try:
        if _is_inside(path, workspace_root):
            return str(path.resolve().relative_to(workspace_root.resolve())).replace("\\", "/")
    except OSError:
        pass
    return "<outside-workspace>"


def _file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "exists": False,
            "kind": "missing",
            "size_bytes": 0,
            "sha256": "",
        }
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "exists": True,
        "kind": "file",
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def build_request_snapshot(request: ChainRunRequest, *, workspace_root: Path) -> dict[str, Any]:
    input_path = _resolve_under_workspace(workspace_root, request.input_path)
    output_root = _resolve_under_workspace(workspace_root, request.output_root)
    return {
        "schema_version": "final_chain_request_snapshot.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": request.chain_id,
        "dry_run": request.dry_run,
        "input": {
            "path": _portable_path(workspace_root, input_path),
            **_file_fingerprint(input_path),
        },
        "output_root": {
            "path": _portable_path(workspace_root, output_root),
            "inside_workspace": _is_inside(output_root, workspace_root),
        },
    }


def build_environment_snapshot(request: ChainRunRequest) -> dict[str, Any]:
    return {
        "schema_version": "final_chain_environment_snapshot.v0.1",
        "profile_name": request.environment.name,
        "allow_model_calls": request.environment.allow_model_calls,
        "allow_database_writes": request.environment.allow_database_writes,
        "allow_runtime_import": request.environment.allow_runtime_import,
        "isolation_checks": {
            "model_calls_disabled": request.environment.allow_model_calls is False,
            "database_writes_disabled": request.environment.allow_database_writes is False,
            "runtime_import_disabled": request.environment.allow_runtime_import is False,
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _portable_record_value(value: Any, *, workspace_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _portable_record_value(item, workspace_root=workspace_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_record_value(item, workspace_root=workspace_root) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            return _portable_path(workspace_root, path)
    return value


def build_portable_plan_snapshot(plan: dict[str, Any], *, workspace_root: Path) -> dict[str, Any]:
    snapshot = _portable_record_value(plan, workspace_root=workspace_root)
    if isinstance(snapshot, dict):
        snapshot["workspace_contract"] = "relative_git_paths_only"
        snapshot["absolute_paths_as_inputs"] = False
    return snapshot


def build_chain_run_plan(
    registry: FinalChainRegistry,
    request: ChainRunRequest,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    chain = registry.get(request.chain_id)
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, **extra: Any) -> None:
        checks.append({"name": name, "ok": ok, **extra})

    add_check("chain_is_protected", chain.protection_status == "protected", value=chain.protection_status)
    add_check("control_plane_dry_run_only", request.dry_run is True, dry_run=request.dry_run)
    add_check(
        "input_format_matches_chain",
        _input_matches_format(request.input_path, chain.input_format),
        expected=chain.input_format,
        input_path=request.input_path,
    )
    input_path = _resolve_under_workspace(workspace_root, request.input_path)
    add_check("input_path_present", input_path.is_file(), input_path=request.input_path)
    output_root = _resolve_under_workspace(workspace_root, request.output_root)
    add_check("output_root_inside_workspace", _is_inside(output_root, workspace_root), output_root=request.output_root)
    add_check("output_root_under_outputs", _is_under_outputs(workspace_root, output_root), output_root=request.output_root)
    add_check("runtime_import_disabled_by_default", chain.runtime_import_default_enabled is False)
    add_check("database_write_disabled_by_default", chain.database_write_default_enabled is False)
    add_check("environment_blocks_runtime_import", request.environment.allow_runtime_import is False)
    add_check("environment_blocks_database_writes", request.environment.allow_database_writes is False)
    add_check("environment_blocks_model_calls", request.environment.allow_model_calls is False)

    entrypoint_state = _relative_path_state(workspace_root, chain.canonical_entrypoint)
    add_check("canonical_entrypoint_present", bool(entrypoint_state["exists"]), **entrypoint_state)

    config_states = [_relative_path_state(workspace_root, path) for path in chain.canonical_config_paths]
    add_check(
        "canonical_configs_present",
        all(state["exists"] for state in config_states),
        paths=config_states,
    )

    can_execute = all(check["ok"] for check in checks)
    status: PlanStatus = "ready" if can_execute else "blocked"
    return {
        "schema_version": "final_chain_run_plan.v0.1",
        "chain_id": chain.chain_id,
        "display_name": chain.display_name,
        "input_format": chain.input_format,
        "subject": chain.subject,
        "registry_readiness": chain.registry_readiness,
        "confidence": chain.confidence,
        "smoke_status": chain.smoke_status,
        "dry_run": request.dry_run,
        "environment": {
            "name": request.environment.name,
            "allow_model_calls": request.environment.allow_model_calls,
            "allow_database_writes": request.environment.allow_database_writes,
            "allow_runtime_import": request.environment.allow_runtime_import,
        },
        "input_path": request.input_path,
        "output_root": request.output_root,
        "status": status,
        "checks": checks,
        "blocked_reasons": [check["name"] for check in checks if not check["ok"]],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def schedule_chain_run(
    registry: FinalChainRegistry,
    request: ChainRunRequest,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    plan = build_chain_run_plan(registry, request, workspace_root=workspace_root)
    portable_plan = build_portable_plan_snapshot(plan, workspace_root=workspace_root)
    output_check = next((check for check in plan["checks"] if check["name"] == "output_root_inside_workspace"), None)
    if output_check is None or not output_check["ok"]:
        created_at = utc_now_iso()
        return attach_job_record_validation({
            "schema_version": "final_chain_job_record.v0.1",
            "job_id": "",
            "created_at": created_at,
            "status": "rejected",
            "chain_id": request.chain_id,
            "record_path": "",
            "plan": portable_plan,
            "request_snapshot": build_request_snapshot(request, workspace_root=workspace_root),
            "environment_snapshot": build_environment_snapshot(request),
            "lifecycle": build_job_lifecycle("rejected", created_at=created_at, reason="output_root_outside_workspace"),
            "execution_contract": plan["execution_contract"],
            "errors": [{"code": "output_root_outside_workspace"}],
        })
    output_root_check = next((check for check in plan["checks"] if check["name"] == "output_root_under_outputs"), None)
    if output_root_check is None or not output_root_check["ok"]:
        created_at = utc_now_iso()
        return attach_job_record_validation({
            "schema_version": "final_chain_job_record.v0.1",
            "job_id": "",
            "created_at": created_at,
            "status": "rejected",
            "chain_id": request.chain_id,
            "record_path": "",
            "plan": portable_plan,
            "request_snapshot": build_request_snapshot(request, workspace_root=workspace_root),
            "environment_snapshot": build_environment_snapshot(request),
            "lifecycle": build_job_lifecycle("rejected", created_at=created_at, reason="output_root_not_under_outputs"),
            "execution_contract": plan["execution_contract"],
            "errors": [{"code": "output_root_not_under_outputs"}],
        })

    job_id = generate_run_id(f"final_chain_{request.chain_id}")
    record_root = _resolve_under_workspace(workspace_root, request.output_root) / "_control" / "jobs" / job_id
    record_path = record_root / "job_record.json"
    status = "scheduled_ready" if plan["status"] == "ready" else "scheduled_blocked"
    created_at = utc_now_iso()
    record = {
        "schema_version": "final_chain_job_record.v0.1",
        "job_id": job_id,
        "created_at": created_at,
        "status": status,
        "chain_id": request.chain_id,
        "record_path": str(record_path.relative_to(workspace_root)).replace("\\", "/"),
        "plan": portable_plan,
        "request_snapshot": build_request_snapshot(request, workspace_root=workspace_root),
        "environment_snapshot": build_environment_snapshot(request),
        "lifecycle": build_job_lifecycle(status, created_at=created_at),
        "execution_contract": plan["execution_contract"],
        "errors": [],
    }
    record = attach_job_record_validation(record)
    write_json(record_path, record)
    return record


def schedule_registry_batch(
    registry: FinalChainRegistry,
    sample_inputs: dict[str, str],
    *,
    output_root: str,
    workspace_root: Path,
    environment: EnvironmentPolicy | None = None,
) -> dict[str, Any]:
    environment = environment or EnvironmentPolicy()
    rows: list[dict[str, Any]] = []
    for chain in registry.chains:
        input_path = sample_inputs.get(chain.chain_id) or _default_missing_sample_path(chain)
        request = ChainRunRequest(
            chain_id=chain.chain_id,
            input_path=input_path,
            output_root=output_root,
            dry_run=True,
            environment=environment,
        )
        record = schedule_chain_run(registry, request, workspace_root=workspace_root)
        validation = validate_job_record(record)
        rows.append(
            {
                "chain_id": chain.chain_id,
                "input_path": input_path,
                "schedule_status": record["status"],
                "plan_status": record["plan"]["status"],
                "record_path": record.get("record_path", ""),
                "record_validation_ok": validation["ok"],
                "record_validation_error_count": validation["error_count"],
                "self_validation_ok": record["record_validation"]["ok"],
                "self_validation_error_count": record["record_validation"]["error_count"],
                "blocked_reasons": record["plan"]["blocked_reasons"],
                "execution_contract": record["execution_contract"],
            }
        )
    ready_count = sum(1 for row in rows if row["schedule_status"] == "scheduled_ready")
    blocked_count = sum(1 for row in rows if row["schedule_status"] == "scheduled_blocked")
    rejected_count = sum(1 for row in rows if row["schedule_status"] == "rejected")
    all_valid = all(row["record_validation_ok"] and row["self_validation_ok"] for row in rows)
    no_side_effects = all(row["execution_contract"] == _no_side_effect_contract() for row in rows)
    return {
        "schema_version": "final_chain_batch_queue_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if all_valid and no_side_effects and rejected_count == 0 else "fail",
        "chain_count": len(rows),
        "scheduled_ready_count": ready_count,
        "scheduled_blocked_count": blocked_count,
        "rejected_count": rejected_count,
        "output_root": _portable_path(workspace_root, _resolve_under_workspace(workspace_root, output_root)),
        "rows": rows,
        "execution_contract": _no_side_effect_contract(),
    }


def _default_missing_sample_path(chain: FinalChainDefinition) -> str:
    suffix = chain.input_format.lower().lstrip(".") or "input"
    return f"tests/fixtures/final_chain_samples/{chain.chain_id}_sample.{suffix}"


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
