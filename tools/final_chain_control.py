from __future__ import annotations

import argparse
import json
from pathlib import Path

from teachbase.core.errors import TeachBaseError
from teachbase.final_chains import (
    ChainRunRequest,
    EnvironmentPolicy,
    build_final_chain_adapters,
    build_final_chain_control_dashboard,
    build_chain_run_plan,
    build_readiness_matrix,
    describe_adapters,
    inspect_adapter_contracts,
    inspect_job_record_path,
    inspect_registry_environments,
    load_final_chain_registry,
    schedule_chain_run,
    transition_job_record_path,
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


def build_adapter_descriptions(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    report = describe_adapters(registry, workspace_root=ROOT)
    if args.chain_id:
        report = {
            **report,
            "descriptions": [item for item in report["descriptions"] if item["chain_id"] == args.chain_id],
        }
        report["chain_count"] = len(report["descriptions"])
    return report


def build_adapter_dry_run(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    adapters = build_final_chain_adapters(registry, workspace_root=ROOT)
    adapter = adapters[args.chain_id]
    request = ChainRunRequest(
        chain_id=args.chain_id,
        input_path=args.input,
        output_root=args.output_root,
        dry_run=True,
        environment=EnvironmentPolicy(name=args.environment),
    )
    return adapter.dry_run(request)


def build_readiness(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    sample_inputs = {}
    for item in args.sample_input or []:
        chain_id, sep, value = item.partition("=")
        if sep:
            sample_inputs[chain_id] = value
    report = build_readiness_matrix(registry, workspace_root=ROOT, sample_inputs=sample_inputs)
    if args.chain_id:
        report = {
            **report,
            "rows": [item for item in report["rows"] if item["chain_id"] == args.chain_id],
        }
        report["chain_count"] = len(report["rows"])
        tier_counts: dict[str, int] = {}
        for row in report["rows"]:
            tier_counts[row["readiness_tier"]] = tier_counts.get(row["readiness_tier"], 0) + 1
        report["tier_counts"] = tier_counts
        report["ready_for_adapter_dry_run_count"] = tier_counts.get("ready_for_adapter_dry_run", 0)
    return report


def build_dashboard(args: argparse.Namespace) -> dict:
    registry = load_final_chain_registry(Path(args.registry))
    sample_inputs = {}
    for item in args.sample_input or []:
        chain_id, sep, value = item.partition("=")
        if sep:
            sample_inputs[chain_id] = value
    report = build_final_chain_control_dashboard(registry, workspace_root=ROOT, sample_inputs=sample_inputs)
    if args.chain_id:
        report = {
            **report,
            "rows": [item for item in report["rows"] if item["chain_id"] == args.chain_id],
        }
        report["chain_count"] = len(report["rows"])
        lane_counts: dict[str, int] = {}
        for row in report["rows"]:
            lane_counts[row["lane"]] = lane_counts.get(row["lane"], 0) + 1
        report["lane_counts"] = lane_counts
    return report


def inspect_job(args: argparse.Namespace) -> dict:
    return inspect_job_record_path(ROOT / args.record)


def transition_job(args: argparse.Namespace) -> dict:
    checkpoint = {"source": "final_chain_control_cli"} if args.with_checkpoint else None
    return transition_job_record_path(
        ROOT / args.record,
        args.status,
        reason=args.reason,
        checkpoint=checkpoint,
        workspace_root=ROOT,
    )


def add_json_flag(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--json", action="store_true", help="Emit JSON output; this is the default and stable contract.")
    return parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and plan protected TeachBase final-chain runs.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY.relative_to(ROOT)))
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_json_flag(subparsers.add_parser("list", help="List registered protected final chains."))

    plan_parser = add_json_flag(subparsers.add_parser("plan", help="Build a dry-run execution plan for one final chain."))
    plan_parser.add_argument("--chain-id", required=True)
    plan_parser.add_argument("--input", required=True)
    plan_parser.add_argument("--output-root", default="outputs/final_chain_runs")
    plan_parser.add_argument("--environment", default="local_dry_run")
    plan_parser.add_argument("--execute", action="store_true", help="Only marks intent; this tool still does not execute chains.")
    plan_parser.add_argument("--allow-model-calls", action="store_true")
    plan_parser.add_argument("--allow-database-writes", action="store_true")
    plan_parser.add_argument("--allow-runtime-import", action="store_true")

    schedule_parser = add_json_flag(
        subparsers.add_parser("schedule", help="Record a non-executing final-chain job plan.")
    )
    schedule_parser.add_argument("--chain-id", required=True)
    schedule_parser.add_argument("--input", required=True)
    schedule_parser.add_argument("--output-root", default="outputs/final_chain_runs")
    schedule_parser.add_argument("--environment", default="local_dry_run")

    env_parser = add_json_flag(
        subparsers.add_parser("env-check", help="Inspect cleanroom environment readiness for final chains.")
    )
    env_parser.add_argument("--chain-id", default="")

    adapter_parser = add_json_flag(
        subparsers.add_parser("adapter-contracts", help="Print adapter contracts for protected final chains.")
    )
    adapter_parser.add_argument("--chain-id", default="")

    adapter_describe_parser = add_json_flag(
        subparsers.add_parser("adapter-describe", help="Describe protected final-chain adapters.")
    )
    adapter_describe_parser.add_argument("--chain-id", default="")

    adapter_dry_run_parser = add_json_flag(
        subparsers.add_parser("adapter-dry-run", help="Run adapter dry-run checks without executing chains.")
    )
    adapter_dry_run_parser.add_argument("--chain-id", required=True)
    adapter_dry_run_parser.add_argument("--input", required=True)
    adapter_dry_run_parser.add_argument("--output-root", default="outputs/final_chain_runs")
    adapter_dry_run_parser.add_argument("--environment", default="local_dry_run")

    readiness_parser = add_json_flag(
        subparsers.add_parser("readiness-matrix", help="Summarize final-chain adapter readiness.")
    )
    readiness_parser.add_argument("--chain-id", default="")
    readiness_parser.add_argument(
        "--sample-input",
        action="append",
        help="Optional chain_id=path sample input used for adapter dry-run readiness.",
    )

    job_inspect_parser = add_json_flag(
        subparsers.add_parser("job-inspect", help="Inspect a recorded final-chain job lifecycle.")
    )
    job_inspect_parser.add_argument("--record", required=True)

    job_transition_parser = add_json_flag(
        subparsers.add_parser(
            "job-transition", help="Apply a guarded lifecycle transition to a recorded final-chain job."
        )
    )
    job_transition_parser.add_argument("--record", required=True)
    job_transition_parser.add_argument("--status", required=True)
    job_transition_parser.add_argument("--reason", required=True)
    job_transition_parser.add_argument("--with-checkpoint", action="store_true")

    dashboard_parser = add_json_flag(
        subparsers.add_parser("dashboard", help="Summarize final-chain scheduling readiness.")
    )
    dashboard_parser.add_argument("--chain-id", default="")
    dashboard_parser.add_argument("--sample-input", action="append")

    args = parser.parse_args()
    try:
        if args.command == "list":
            result = list_chains(Path(args.registry))
        elif args.command == "schedule":
            result = build_schedule(args)
        elif args.command == "env-check":
            result = build_env_check(args)
        elif args.command == "adapter-contracts":
            result = build_adapter_contracts(args)
        elif args.command == "adapter-describe":
            result = build_adapter_descriptions(args)
        elif args.command == "adapter-dry-run":
            result = build_adapter_dry_run(args)
        elif args.command == "readiness-matrix":
            result = build_readiness(args)
        elif args.command == "job-inspect":
            result = inspect_job(args)
        elif args.command == "job-transition":
            result = transition_job(args)
        elif args.command == "dashboard":
            result = build_dashboard(args)
        else:
            result = build_plan(args)
    except TeachBaseError as exc:
        result = {
            "schema_version": "final_chain_control_error.v0.1",
            "status": "error",
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "retryable": exc.retryable,
                "evidence": exc.evidence,
            },
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command in {
        "list",
        "adapter-contracts",
        "adapter-describe",
        "readiness-matrix",
        "job-inspect",
        "dashboard",
    }:
        return 0
    if args.command == "adapter-dry-run":
        return 0 if result.get("status") == "dry_run_ready" else 2
    if args.command == "env-check":
        return 0 if result.get("blocked_count") == 0 else 2
    status = result.get("status")
    if status in {"blocked", "rejected", "scheduled_blocked"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
