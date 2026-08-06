from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_CHAIN_IDS = {"doc_math", "doc_english", "pdf_math", "pdf_english"}
REQUIRED_CHAIN_FIELDS = {
    "chain_id",
    "display_name",
    "input_format",
    "subject",
    "protection_status",
    "registry_readiness",
    "confidence",
    "source_state",
    "canonical_entrypoint",
    "smoke_status",
    "runtime_import_policy",
    "database_write_policy",
}
ALLOWED_INPUT_FORMATS = {"docx", "pdf"}
ALLOWED_SUBJECTS = {"math", "english"}
ALLOWED_CONFIDENCE = {"low", "medium", "medium_high", "high"}
ALLOWED_SMOKE_STATUS = {"pass", "partial", "blocked"}
REQUIRED_EXCLUSION_PATTERNS = {"backup", "probe", "smoke", "plain_full", "badcase"}


def _load_json_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must be JSON-compatible YAML in this no-new-dependency validator: {exc}") from exc


def _as_bool(value: Any) -> bool:
    return value is True


def _path_exists(workspace: Path, value: str) -> bool:
    path = Path(value)
    return path.is_absolute() and path.exists() or (workspace / path).exists()


def validate_final_chain_registry(registry_path: Path, workspace: Path | None = None) -> dict[str, Any]:
    workspace = workspace or Path.cwd()
    registry = _load_json_yaml(registry_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if registry.get("schema_version") != "final_chain_registry.v0.1":
        errors.append({"code": "invalid_schema_version", "schema_version": registry.get("schema_version")})

    selection_policy = registry.get("selection_policy")
    if not isinstance(selection_policy, dict):
        errors.append({"code": "missing_selection_policy"})
        selection_policy = {}
    if selection_policy.get("do_not_guess_latest_directory") is not True:
        errors.append({"code": "latest_directory_guessing_not_forbidden"})
    patterns = {str(item) for item in selection_policy.get("exclude_name_patterns_as_final") or []}
    missing_patterns = sorted(REQUIRED_EXCLUSION_PATTERNS - patterns)
    if missing_patterns:
        errors.append({"code": "missing_required_exclusion_patterns", "patterns": missing_patterns})
    if selection_policy.get("runtime_import_default_enabled") is not False:
        errors.append({"code": "selection_policy_runtime_default_enabled"})
    if selection_policy.get("database_write_default_enabled") is not False:
        errors.append({"code": "selection_policy_database_default_enabled"})

    chains = registry.get("chains")
    if not isinstance(chains, list) or not chains:
        errors.append({"code": "missing_chains"})
        chains = []

    ids: list[str] = []
    for idx, chain in enumerate(chains):
        if not isinstance(chain, dict):
            errors.append({"code": "invalid_chain_entry", "index": idx})
            continue
        chain_id = str(chain.get("chain_id") or "")
        ids.append(chain_id)

        missing = sorted(field for field in REQUIRED_CHAIN_FIELDS if field not in chain)
        if missing:
            errors.append({"code": "missing_required_fields", "chain_id": chain_id, "fields": missing})

        if chain.get("input_format") not in ALLOWED_INPUT_FORMATS:
            errors.append({"code": "invalid_input_format", "chain_id": chain_id, "input_format": chain.get("input_format")})
        if chain.get("subject") not in ALLOWED_SUBJECTS:
            errors.append({"code": "invalid_subject", "chain_id": chain_id, "subject": chain.get("subject")})
        if chain.get("protection_status") != "protected":
            errors.append({"code": "chain_not_protected", "chain_id": chain_id})
        if chain.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append({"code": "invalid_confidence", "chain_id": chain_id, "confidence": chain.get("confidence")})

        smoke_status = chain.get("smoke_status") if isinstance(chain.get("smoke_status"), dict) else {}
        smoke_state = smoke_status.get("status")
        if smoke_state not in ALLOWED_SMOKE_STATUS:
            errors.append({"code": "invalid_smoke_status", "chain_id": chain_id, "status": smoke_state})
        if chain.get("confidence") == "high" and smoke_state != "pass":
            errors.append({"code": "high_confidence_without_passing_smoke", "chain_id": chain_id})
        if smoke_state == "partial" and not smoke_status.get("blocking_checks"):
            errors.append({"code": "partial_smoke_without_blocking_checks", "chain_id": chain_id})

        runtime_policy = chain.get("runtime_import_policy") if isinstance(chain.get("runtime_import_policy"), dict) else {}
        database_policy = chain.get("database_write_policy") if isinstance(chain.get("database_write_policy"), dict) else {}
        if runtime_policy.get("default_enabled") is not False:
            errors.append({"code": "runtime_import_default_enabled", "chain_id": chain_id})
        if database_policy.get("default_enabled") is not False:
            errors.append({"code": "database_write_default_enabled", "chain_id": chain_id})

        entrypoint = str(chain.get("canonical_entrypoint") or "")
        if not entrypoint:
            errors.append({"code": "missing_canonical_entrypoint", "chain_id": chain_id})
        elif not _path_exists(workspace, entrypoint):
            warnings.append({"code": "canonical_entrypoint_not_in_workspace", "chain_id": chain_id, "path": entrypoint})

        for path_value in chain.get("canonical_config_paths") or []:
            if not _path_exists(workspace, str(path_value)):
                warnings.append({"code": "canonical_config_not_in_workspace", "chain_id": chain_id, "path": str(path_value)})

    duplicates = sorted({chain_id for chain_id in ids if ids.count(chain_id) > 1})
    for chain_id in duplicates:
        errors.append({"code": "duplicate_chain_id", "chain_id": chain_id})

    present_ids = set(ids)
    missing_required = sorted(REQUIRED_CHAIN_IDS - present_ids)
    extra_ids = sorted(present_ids - REQUIRED_CHAIN_IDS)
    if missing_required:
        errors.append({"code": "missing_required_chain_ids", "chain_ids": missing_required})
    if extra_ids:
        errors.append({"code": "unexpected_chain_ids", "chain_ids": extra_ids})

    chains_by_id = {chain.get("chain_id"): chain for chain in chains if isinstance(chain, dict)}
    pdf_english = chains_by_id.get("pdf_english")
    if isinstance(pdf_english, dict):
        readiness = str(pdf_english.get("registry_readiness") or "")
        if readiness != "ready_for_java_shell_admission":
            errors.append({"code": "pdf_english_missing_java_shell_admission_marker", "value": readiness})
        if pdf_english.get("canonical_pipeline_name") != "english_text_first_graph_first":
            errors.append({"code": "pdf_english_wrong_pipeline_name", "value": pdf_english.get("canonical_pipeline_name")})
        if pdf_english.get("canonical_entrypoint") != "config/english_text_first_graph_first/active_manifest.json":
            errors.append({"code": "pdf_english_wrong_canonical_entrypoint", "value": pdf_english.get("canonical_entrypoint")})
        smoke_status = pdf_english.get("smoke_status") if isinstance(pdf_english.get("smoke_status"), dict) else {}
        if smoke_status.get("status") != "pass":
            errors.append({"code": "pdf_english_smoke_not_promoted", "value": smoke_status.get("status")})
        admission = (
            pdf_english.get("java_shell_admission")
            if isinstance(pdf_english.get("java_shell_admission"), dict)
            else {}
        )
        model_policy = (
            pdf_english.get("production_model_execution_policy")
            if isinstance(pdf_english.get("production_model_execution_policy"), dict)
            else {}
        )
        if admission.get("allowed") is not True:
            errors.append({"code": "pdf_english_java_shell_admission_not_allowed"})
        if admission.get("not_a_model_execution_claim") is not True:
            errors.append({"code": "pdf_english_java_shell_admission_blurs_model_execution"})
        if not _path_exists(workspace, str(admission.get("source_report") or "")):
            errors.append({"code": "pdf_english_raw_promotion_report_missing", "path": admission.get("source_report")})
        if model_policy.get("model_calls_default_enabled") is not False:
            errors.append({"code": "pdf_english_model_calls_default_enabled"})

    return {
        "schema_version": "final_chain_registry_validation_result.v0.1",
        "registry_path": str(registry_path),
        "chain_count": len(chains),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "ok": len(errors) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the TeachBase protected final-chain registry.")
    parser.add_argument("--registry", default="config/final_chain_registry.yaml")
    parser.add_argument("--json", action="store_true", help="Print the full validation result as JSON.")
    args = parser.parse_args()
    result = validate_final_chain_registry(Path(args.registry), Path.cwd())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(f"final_chain_registry_valid chains={result['chain_count']} warnings={result['warning_count']}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
