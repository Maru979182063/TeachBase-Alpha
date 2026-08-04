# Final Chain Control Dashboard 2026-08-04

This dashboard combines protected final-chain readiness, adapter contracts, and scheduler lifecycle policy.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `needs_artifact_restore_or_smoke`: 1
- `needs_cleanroom_import`: 1
- `needs_sample_input`: 2

## Lifecycle Policy

- `cancelled` -> `terminal`
- `dry_run_failed` -> `terminal`
- `dry_run_passed` -> `terminal`
- `dry_run_started` -> `dry_run_passed`, `dry_run_failed`, `cancelled`
- `rejected` -> `terminal`
- `scheduled_blocked` -> `terminal`
- `scheduled_ready` -> `dry_run_started`, `cancelled`

## Chains

- `doc_math` `needs_sample_input` `environment_ready_input_needed`; blockers: `input_path_present`; actions: `provide_existing_input_file_for_adapter_dry_run`
- `doc_english` `needs_cleanroom_import` `cleanroom_import_required`; blockers: `canonical_configs_present`, `canonical_entrypoint_present`, `input_path_present`, `required_paths_present`; actions: `import_or_restore_canonical_entrypoint_and_configs`
- `pdf_math` `needs_sample_input` `environment_ready_input_needed`; blockers: `input_path_present`; actions: `provide_existing_input_file_for_adapter_dry_run`
- `pdf_english` `needs_artifact_restore_or_smoke` `restore_or_rerun_required`; blockers: `canonical_entrypoint_present`, `input_path_present`, `required_paths_present`; actions: `import_or_restore_canonical_entrypoint_and_configs`, `restore_active_manifest_or_rerun_smoke_artifacts`
