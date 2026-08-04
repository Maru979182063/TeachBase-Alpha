from __future__ import annotations

from typing import Any

from .control import FinalChainRegistry
from .jobs import ALLOWED_TRANSITIONS, TERMINAL_STATUSES


def build_final_chain_control_contract(registry: FinalChainRegistry) -> dict[str, Any]:
    return {
        "schema_version": "final_chain_control_contract.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "consumer_role": "external_orchestrator_or_java_backbone",
        "chain_count": len(registry.chains),
        "chain_ids": [chain.chain_id for chain in registry.chains],
        "control_plane_contract": {
            "dry_run_only": True,
            "execute_intent_blocked": True,
            "scheduler_writes_only_under": "outputs/",
            "adapter_dry_run_invokes_entrypoint": False,
            "requires_existing_input_file": True,
            "requires_protected_chain_registry": True,
            "portable_record_snapshots_required": True,
        },
        "forbidden_side_effects": {
            "model_calls": True,
            "database_writes": True,
            "runtime_imports": True,
            "business_secret_reads": True,
        },
        "required_job_record_sections": [
            "plan",
            "request_snapshot",
            "environment_snapshot",
            "lifecycle",
            "execution_contract",
        ],
        "commands": {
            "contract": "tools/final_chain_control.py contract --json",
            "env_contract": "tools/final_chain_control.py env-contract --json",
            "list": "tools/final_chain_control.py list --json",
            "plan": "tools/final_chain_control.py plan --chain-id <chain_id> --input <path> --json",
            "schedule": "tools/final_chain_control.py schedule --chain-id <chain_id> --input <path>",
            "queue": "tools/final_chain_control.py queue --sample-input <chain_id=path> --json",
            "adapter_dry_run": "tools/final_chain_control.py adapter-dry-run --chain-id <chain_id> --input <path> --json",
            "job_inspect": "tools/final_chain_control.py job-inspect --record <relative_record_path> --json",
            "job_validate": "tools/final_chain_control.py job-validate --record <relative_record_path> --json",
            "job_transition": (
                "tools/final_chain_control.py job-transition --record <relative_record_path> "
                "--status <status> --reason <reason> --json"
            ),
        },
        "job_lifecycle_policy": {
            "schema_version": "final_chain_job_lifecycle.v0.1",
            "terminal_statuses": sorted(TERMINAL_STATUSES),
            "allowed_transitions": {key: list(value) for key, value in sorted(ALLOWED_TRANSITIONS.items())},
        },
        "chain_contracts": [_chain_contract(chain.raw) for chain in registry.chains],
        "execution_contract": _no_side_effect_contract(),
    }


def _chain_contract(chain: dict[str, Any]) -> dict[str, Any]:
    return {
        "chain_id": str(chain.get("chain_id") or ""),
        "input_format": str(chain.get("input_format") or ""),
        "subject": str(chain.get("subject") or ""),
        "registry_readiness": str(chain.get("registry_readiness") or ""),
        "protection_status": str(chain.get("protection_status") or ""),
        "canonical_entrypoint": str(chain.get("canonical_entrypoint") or ""),
        "runtime_import_default_enabled": _policy_default_enabled(chain, "runtime_import_policy"),
        "database_write_default_enabled": _policy_default_enabled(chain, "database_write_policy"),
    }


def _policy_default_enabled(chain: dict[str, Any], key: str) -> bool:
    policy = chain.get(key)
    return isinstance(policy, dict) and policy.get("default_enabled") is True


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
