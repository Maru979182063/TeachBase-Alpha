from __future__ import annotations

import argparse
import json
from pathlib import Path

from teachbase.final_chains import ChainRunRequest, EnvironmentPolicy, build_chain_run_plan, load_final_chain_registry


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

    args = parser.parse_args()
    if args.command == "list":
        result = list_chains(Path(args.registry))
    else:
        result = build_plan(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") != "blocked" or args.command == "list" else 2


if __name__ == "__main__":
    raise SystemExit(main())
