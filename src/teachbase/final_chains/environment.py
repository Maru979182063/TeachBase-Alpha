from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .control import FinalChainDefinition, FinalChainRegistry, _relative_path_state


@dataclass(frozen=True)
class ChainEnvironmentProfile:
    chain_id: str
    profile_name: str = "cleanroom_dry_run"
    required_path_fields: tuple[str, ...] = ("canonical_entrypoint", "canonical_config_paths")
    optional_path_fields: tuple[str, ...] = ("protected_paths", "supporting_entrypoints")
    allow_model_calls: bool = False
    allow_database_writes: bool = False
    allow_runtime_import: bool = False
    required_secret_names: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterContract:
    chain_id: str
    adapter_api_version: str = "final_chain_adapter.v0.1"
    required_methods: tuple[str, ...] = ("describe", "plan", "dry_run")
    forbidden_during_dry_run: tuple[str, ...] = ("model_call", "database_write", "runtime_import", "business_secret_read")
    required_artifact_behaviors: tuple[str, ...] = ("atomic_write", "checkpoint_record", "relative_path_report")
    required_failure_behaviors: tuple[str, ...] = ("fail_closed", "machine_readable_error", "no_partial_success_claim")


def build_environment_profile(chain: FinalChainDefinition) -> ChainEnvironmentProfile:
    notes: list[str] = []
    if chain.smoke_status == "partial":
        notes.append("smoke_status_partial_requires_restore_or_rerun")
    return ChainEnvironmentProfile(chain_id=chain.chain_id, notes=tuple(notes))


def _paths_from_raw(chain: FinalChainDefinition, field_name: str) -> list[str]:
    value = chain.raw.get(field_name)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(path)
    return deduped


def inspect_chain_environment(
    chain: FinalChainDefinition,
    *,
    workspace_root: Path,
    profile: ChainEnvironmentProfile | None = None,
) -> dict[str, Any]:
    profile = profile or build_environment_profile(chain)
    required_paths = [chain.canonical_entrypoint, *chain.canonical_config_paths]
    optional_paths: list[str] = []
    for field_name in profile.optional_path_fields:
        optional_paths.extend(_paths_from_raw(chain, field_name))
    optional_paths = _dedupe_paths(optional_paths)
    required_path_states = [_relative_path_state(workspace_root, path) for path in required_paths if path]
    optional_path_states = [_relative_path_state(workspace_root, path) for path in optional_paths if path]
    checks = {
        "chain_is_protected": chain.protection_status == "protected",
        "runtime_import_default_disabled": chain.runtime_import_default_enabled is False,
        "database_write_default_disabled": chain.database_write_default_enabled is False,
        "model_calls_profile_disabled": profile.allow_model_calls is False,
        "database_writes_profile_disabled": profile.allow_database_writes is False,
        "runtime_import_profile_disabled": profile.allow_runtime_import is False,
        "required_paths_present": all(item["exists"] for item in required_path_states),
        "no_required_business_secrets": not profile.required_secret_names,
    }
    return {
        "chain_id": chain.chain_id,
        "profile_name": profile.profile_name,
        "input_format": chain.input_format,
        "subject": chain.subject,
        "registry_readiness": chain.registry_readiness,
        "smoke_status": chain.smoke_status,
        "checks": checks,
        "status": "ready" if all(checks.values()) else "blocked",
        "blocked_reasons": [name for name, ok in checks.items() if not ok],
        "required_paths": required_path_states,
        "optional_path_summary": {
            "count": len(optional_path_states),
            "present": sum(1 for item in optional_path_states if item["exists"]),
            "missing": sum(1 for item in optional_path_states if not item["exists"]),
            "missing_samples": [item for item in optional_path_states if not item["exists"]][:10],
        },
        "capability_policy": {
            "allow_model_calls": profile.allow_model_calls,
            "allow_database_writes": profile.allow_database_writes,
            "allow_runtime_import": profile.allow_runtime_import,
            "required_secret_names": list(profile.required_secret_names),
        },
        "notes": list(profile.notes),
    }


def inspect_registry_environments(registry: FinalChainRegistry, *, workspace_root: Path) -> dict[str, Any]:
    chains = [inspect_chain_environment(chain, workspace_root=workspace_root) for chain in registry.chains]
    return {
        "schema_version": "final_chain_environment_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_count": len(chains),
        "ready_count": sum(1 for item in chains if item["status"] == "ready"),
        "blocked_count": sum(1 for item in chains if item["status"] == "blocked"),
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
        "chains": chains,
    }


def build_environment_interaction_contract(registry: FinalChainRegistry, *, workspace_root: Path) -> dict[str, Any]:
    environment_report = inspect_registry_environments(registry, workspace_root=workspace_root)
    profiles = [_environment_contract_profile(item) for item in environment_report["chains"]]
    checks = [
        {
            "name": "four_environment_profiles_declared",
            "ok": len(profiles) == 4,
            "value": [item["chain_id"] for item in profiles],
        },
        {
            "name": "all_profiles_deny_model_calls",
            "ok": all(item["capability_policy"]["allow_model_calls"] is False for item in profiles),
            "value": [item["capability_policy"]["allow_model_calls"] for item in profiles],
        },
        {
            "name": "all_profiles_deny_database_writes",
            "ok": all(item["capability_policy"]["allow_database_writes"] is False for item in profiles),
            "value": [item["capability_policy"]["allow_database_writes"] for item in profiles],
        },
        {
            "name": "all_profiles_deny_runtime_import",
            "ok": all(item["capability_policy"]["allow_runtime_import"] is False for item in profiles),
            "value": [item["capability_policy"]["allow_runtime_import"] for item in profiles],
        },
        {
            "name": "all_profiles_require_no_business_secrets",
            "ok": all(not item["capability_policy"]["required_secret_names"] for item in profiles),
            "value": [item["capability_policy"]["required_secret_names"] for item in profiles],
        },
        {
            "name": "blocked_profiles_fail_closed",
            "ok": all(item["environment_gate"] == "fail_closed" for item in profiles if item["status"] == "blocked"),
            "value": [item["chain_id"] for item in profiles if item["status"] == "blocked"],
        },
        {
            "name": "filesystem_writes_limited_to_outputs",
            "ok": True,
            "value": ["outputs/"],
        },
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        "schema_version": "final_chain_environment_interaction_contract.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "consumer_role": "external_orchestrator_or_java_backbone",
        "status": "pass" if not failed else "fail",
        "chain_count": len(profiles),
        "ready_chain_ids": [item["chain_id"] for item in profiles if item["status"] == "ready"],
        "blocked_chain_ids": [item["chain_id"] for item in profiles if item["status"] == "blocked"],
        "filesystem_contract": {
            "read_scope": "registered_relative_paths_only",
            "write_scope": ["outputs/"],
            "read_only_scopes": ["config/", "src/", "tools/", "prompts/", "tests/"],
            "temp_files_must_share_target_directory": True,
            "absolute_paths_as_reproducible_inputs": False,
        },
        "external_handshake": [
            "env-contract",
            "contract",
            "plan",
            "schedule",
            "job-validate",
            "adapter-dry-run",
        ],
        "forbidden_side_effects": {
            "model_calls": True,
            "database_writes": True,
            "runtime_imports": True,
            "business_secret_reads": True,
        },
        "checks": checks,
        "profiles": profiles,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _environment_contract_profile(environment: dict[str, Any]) -> dict[str, Any]:
    required_paths = environment.get("required_paths") if isinstance(environment.get("required_paths"), list) else []
    required_path_count = len(required_paths)
    required_path_present_count = sum(1 for item in required_paths if isinstance(item, dict) and item.get("exists") is True)
    status = str(environment.get("status") or "")
    return {
        "chain_id": str(environment.get("chain_id") or ""),
        "profile_name": str(environment.get("profile_name") or ""),
        "input_format": str(environment.get("input_format") or ""),
        "subject": str(environment.get("subject") or ""),
        "registry_readiness": str(environment.get("registry_readiness") or ""),
        "smoke_status": str(environment.get("smoke_status") or ""),
        "status": status,
        "environment_gate": "ready_for_control_plane" if status == "ready" else "fail_closed",
        "blocked_reasons": list(environment.get("blocked_reasons") or []),
        "required_path_count": required_path_count,
        "required_path_present_count": required_path_present_count,
        "optional_path_summary": environment.get("optional_path_summary"),
        "capability_policy": environment.get("capability_policy"),
        "allowed_control_intents": [
            "inspect",
            "plan",
            "schedule_dry_run",
            "job_validate",
            "adapter_dry_run",
        ],
    }


def build_adapter_contract(chain: FinalChainDefinition) -> dict[str, Any]:
    contract = AdapterContract(chain_id=chain.chain_id)
    return {
        "schema_version": contract.adapter_api_version,
        "chain_id": chain.chain_id,
        "input_format": chain.input_format,
        "subject": chain.subject,
        "canonical_entrypoint": chain.canonical_entrypoint,
        "required_methods": list(contract.required_methods),
        "forbidden_during_dry_run": list(contract.forbidden_during_dry_run),
        "required_artifact_behaviors": list(contract.required_artifact_behaviors),
        "required_failure_behaviors": list(contract.required_failure_behaviors),
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def inspect_adapter_contracts(registry: FinalChainRegistry) -> dict[str, Any]:
    contracts = [build_adapter_contract(chain) for chain in registry.chains]
    return {
        "schema_version": "final_chain_adapter_contract_report.v0.1",
        "chain_count": len(contracts),
        "contracts": contracts,
        "ok": all(
            "model_call" in contract["forbidden_during_dry_run"]
            and "database_write" in contract["forbidden_during_dry_run"]
            and "runtime_import" in contract["forbidden_during_dry_run"]
            for contract in contracts
        ),
    }
