# Final Chain Control Contract 2026-08-04

Schema: `final_chain_control_contract.v0.1`
Consumer: `external_orchestrator_or_java_backbone`
Chains: `doc_math, doc_english, pdf_math, pdf_english`

## Control Plane

- `dry_run_only`: `True`
- `execute_intent_blocked`: `True`
- `scheduler_writes_only_under`: `outputs/`
- `adapter_dry_run_invokes_entrypoint`: `False`
- `requires_existing_input_file`: `True`
- `requires_protected_chain_registry`: `True`
- `portable_record_snapshots_required`: `True`

## Forbidden Side Effects

- `model_calls`: `True`
- `database_writes`: `True`
- `runtime_imports`: `True`
- `business_secret_reads`: `True`

## Commands

- `contract`: `tools/final_chain_control.py contract --json`
- `env_contract`: `tools/final_chain_control.py env-contract --json`
- `list`: `tools/final_chain_control.py list --json`
- `plan`: `tools/final_chain_control.py plan --chain-id <chain_id> --input <path> --json`
- `schedule`: `tools/final_chain_control.py schedule --chain-id <chain_id> --input <path>`
- `queue`: `tools/final_chain_control.py queue --sample-input <chain_id=path> --json`
- `adapter_dry_run`: `tools/final_chain_control.py adapter-dry-run --chain-id <chain_id> --input <path> --json`
- `job_inspect`: `tools/final_chain_control.py job-inspect --record <relative_record_path> --json`
- `job_validate`: `tools/final_chain_control.py job-validate --record <relative_record_path> --json`
- `job_transition`: `tools/final_chain_control.py job-transition --record <relative_record_path> --status <status> --reason <reason> --json`

All paths are relative git paths; no local absolute path is part of the reproducible input contract.
