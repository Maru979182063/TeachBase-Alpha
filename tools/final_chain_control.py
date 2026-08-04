from __future__ import annotations

import argparse
import json
from pathlib import Path

from teachbase.final_chains import (
    ChainRunRequest,
    EnvironmentPolicy,
    build_chain_run_plan,
    inspect_adapter_contracts,
    inspect_registry_environments,
    load_final_chain_registry,
    schedule_chain_run,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "final_chain_registry.yaml"


def list_chains(registry_path: Path) -> dict:
    registry = load_final_chain_registry(registry_path)
    return {
        "schema_version": "final_chain_control_list.v0.1",
        "chain_count": len(registry.chains),
        "chains": [
            {
                "chain_id": chain.chain_id,
                "display_name": chain.display_name,
                "input_format": chain.input_format,
                "subject": chain.subject,
                "registry_readiness": chain.registry_readiness,
                "confidence": chain.confidence,
                "smoke_status": chain.smoke_status,
            }
            for chain in registry.chains
        ],
    }


def build_plan(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    request = ChainRunRequest(
        chain_id=args.chain_id,
        input_path=args.input,
        output_root=args.output_root,
        dry_run=not args.execute,
        environment=EnvironmentPolicy(
            name=args.environment,
            allow_model_calls=args.allow_model_calls,
            allow_database_writes=args.allow_database_writes,
            allow_runtime_import=args.allow_runtime_import,
        ),
    )
    return build_chain_run_plan(registry, request, workspace_root=ROOT)


def build_schedule(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    request = ChainRunRequest(
        chain_id=args.chain_id,
        input_path=args.input,
        output_root=args.output_root,
        dry_run=True,
        environment=EnvironmentPolicy(name=args.environment),
    )
    return schedule_chain_run(registry, request, workspace_root=ROOT)


def build_env_check(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    report = inspect_registry_environments(registry, workspace_root=ROOT)
    if args.chain_id:
        report = {
            **report,
            "chains": [item for item in report["chains"] if item["chain_id"] == args.chain_id],
        }
        report["chain_count"] = len(report["chains"])
        report["ready_count"] = sum(1 for item in report["chains"] if item["status"] == "ready")
        report["blocked_count"] = sum(1 for item in report["chains"] if item["status"] == "blocked")
    return report


def build_adapter_contracts(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    report = inspect_adapter_contracts(registry)
    if args.chain_id:
        report = {
            **report,
            "contracts": [item for item in report["contracts"] if item["chain_id"] == args.chain_id],
        }
        report["chain_count"] = len(report["contracts"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and plan protected TeachBase final-chain runs.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY.relative_to(ROOT)))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered protected final chains.")

    plan_parser = subparsers.add_parser("plan", help="Build a dry-run execution plan for one final chain.")
    plan_parser.add_argument("--chain-id", required=True)
    plan_parser.add_argument("--input", required=True)
    plan_parser.add_argument("--output-root", default="outputs/final_chain_runs")
    plan_parser.add_argument("--environment", default="local_dry_run")
    plan_parser.add_argument("--execute", action="store_true", help="Only marks intent; this tool still does not execute chains.")
    plan_parser.add_argument("--allow-model-calls", action="store_true")
    plan_parser.add_argument("--allow-database-writes", action="store_true")
    plan_parser.add_argument("--allow-runtime-import", action="store_true")

    schedule_parser = subparsers.add_parser("schedule", help="Record a non-executing final-chain job plan.")
    schedule_parser.add_argument("--chain-id", required=True)
    schedule_parser.add_argument("--input", required=True)
    schedule_parser.add_argument("--output-root", default="outputs/final_chain_runs")
    schedule_parser.add_argument("--environment", default="local_dry_run")

    env_parser = subparsers.add_parser("env-check", help="Inspect cleanroom environment readiness for final chains.")
    env_parser.add_argument("--chain-id", default="")

    adapter_parser = subparsers.add_parser("adapter-contracts", help="Print adapter contracts for protected final chains.")
    adapter_parser.add_argument("--chain-id", default="")

    args = parser.parse_args()
    if args.command == "list":
        result = list_chains(Path(args.registry))
    elif args.command == "schedule":
        result = build_schedule(args)
    elif args.command == "env-check":
        result = build_env_check(args)
    elif args.command == "adapter-contracts":
        result = build_adapter_contracts(args)
    else:
        result = build_plan(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command in {"list", "adapter-contracts"}:
        return 0
    if args.command == "env-check":
        return 0 if result.get("blocked_count") == 0 else 2
    status = result.get("status")
    if status in {"blocked", "rejected", "scheduled_blocked"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
