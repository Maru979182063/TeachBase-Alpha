# PDF English Recovery Validation 2026-08-04

Status: `blocked_missing_or_invalid_manifest`

## Checks

- `fail` `active_manifest_exists`
- `fail` `active_manifest_json_object`
- `fail` `pipeline_name_matches`
- `fail` `allow_only_manifest_runs_enabled`
- `fail` `timestamp_latest_selection_forbidden`
- `fail` `four_branch_runs_declared`
- `fail` `prior_smoke_zip_present`
- `fail` `prior_smoke_dir_present`

## Safe Next Actions

- `restore_active_manifest_from_original_machine_or_backup`
- `restore_or_rerun_small_smoke_artifacts`
- `do_not_create_synthetic_active_manifest`
