from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .control import ChainRunRequest, FinalChainDefinition, FinalChainRegistry, build_chain_run_plan
from .environment import build_adapter_contract, inspect_chain_environment


@dataclass(frozen=True)
class FinalChainAdapter:
    chain: FinalChainDefinition
    workspace_root: Path

    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "final_chain_adapter_description.v0.1",
            "chain_id": self.chain.chain_id,
            "display_name": self.chain.display_name,
            "input_format": self.chain.input_format,
            "subject": self.chain.subject,
            "registry_readiness": self.chain.registry_readiness,
            "confidence": self.chain.confidence,
            "smoke_status": self.chain.smoke_status,
            "canonical_entrypoint": self.chain.canonical_entrypoint,
            "contract": build_adapter_contract(self.chain),
            "environment": inspect_chain_environment(self.chain, workspace_root=self.workspace_root),
        }

    def plan(self, request: ChainRunRequest) -> dict[str, Any]:
        if request.chain_id != self.chain.chain_id:
            return {
                "schema_version": "final_chain_run_plan.v0.1",
                "chain_id": request.chain_id,
                "status": "blocked",
                "blocked_reasons": ["adapter_chain_id_mismatch"],
                "execution_contract": _no_side_effect_contract(),
                "checks": [
                    {
                        "name": "adapter_chain_id_matches_request",
                        "ok": False,
                        "adapter_chain_id": self.chain.chain_id,
                        "request_chain_id": request.chain_id,
                    }
                ],
            }
        return build_chain_run_plan(
            FinalChainRegistry(schema_version="", selection_policy={}, chains=(self.chain,)),
            request,
            workspace_root=self.workspace_root,
        )

    def dry_run(self, request: ChainRunRequest) -> dict[str, Any]:
        plan = self.plan(request)
        status = "dry_run_ready" if plan.get("status") == "ready" else "dry_run_blocked"
        return {
            "schema_version": "final_chain_adapter_dry_run.v0.1",
            "chain_id": self.chain.chain_id,
            "status": status,
            "plan": plan,
            "execution_contract": _no_side_effect_contract(),
            "adapter_invoked_entrypoint": False,
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        }


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def build_final_chain_adapters(registry: FinalChainRegistry, *, workspace_root: Path) -> dict[str, FinalChainAdapter]:
    return {chain.chain_id: FinalChainAdapter(chain=chain, workspace_root=workspace_root) for chain in registry.chains}


def describe_adapters(registry: FinalChainRegistry, *, workspace_root: Path) -> dict[str, Any]:
    adapters = build_final_chain_adapters(registry, workspace_root=workspace_root)
    descriptions = [adapter.describe() for adapter in adapters.values()]
    return {
        "schema_version": "final_chain_adapter_description_report.v0.1",
        "chain_count": len(descriptions),
        "descriptions": descriptions,
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
