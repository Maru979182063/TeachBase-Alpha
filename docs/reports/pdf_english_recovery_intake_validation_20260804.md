# PDF English Recovery Intake Validation 2026-08-04

Status: `blocked_missing_or_invalid_recovery_candidate`
Candidate: `current_cleanroom_workspace`

## Checks

- `pass` `candidate_root_exists`
- `fail` `active_manifest_present`
- `fail` `active_manifest_json_object`
- `fail` `pipeline_name_matches`
- `fail` `allow_only_manifest_runs_enabled`
- `fail` `timestamp_latest_selection_forbidden`
- `fail` `four_branch_runs_declared`
- `fail` `manifest_checker_present`
- `fail` `prior_smoke_zip_present`
- `fail` `prior_smoke_zip_valid`
- `fail` `prior_smoke_dir_present`
- `fail` `prior_smoke_dir_nonempty`

## Safe Next Actions

- `stage_recovered_artifacts_under_a_candidate_root`
- `preserve_relative_paths_from_config_tools_outputs`
- `rerun_this_intake_gate_before_copying_into_protected_paths`

## Unsafe Actions

- `do_not_copy_candidate_into_config_until_this_report_is_ready`
- `do_not_create_synthetic_active_manifest`
- `do_not_select_latest_directory_by_timestamp`
- `do_not_mark_pdf_english_adapter_ready_without_manifest_check_and_smoke`

Candidate roots outside the workspace are reported by label only; absolute local paths are not a reproducible input contract.
