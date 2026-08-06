# PDF English Recovery Intake Validation 2026-08-04

Status: `candidate_ready_for_quarantine_import`
Candidate: `current_cleanroom_workspace`

## Checks

- `pass` `candidate_root_exists`
- `pass` `active_manifest_present`
- `pass` `active_manifest_json_object`
- `pass` `pipeline_name_matches`
- `pass` `allow_only_manifest_runs_enabled`
- `pass` `timestamp_latest_selection_forbidden`
- `pass` `four_branch_runs_declared`
- `pass` `manifest_checker_present`
- `pass` `smoke_zip_present`
- `pass` `smoke_zip_valid`
- `pass` `smoke_dir_present`
- `pass` `smoke_dir_nonempty`

## Safe Next Actions

- `copy_candidate_artifacts_with_preserved_relative_paths_into_quarantine_branch`
- `run_python_tools_english_text_first_graph_first_manifest_check`
- `run_small_smoke_before_claiming_pdf_english_ready`

## Unsafe Actions

- `do_not_copy_candidate_into_config_until_this_report_is_ready`
- `do_not_create_synthetic_active_manifest`
- `do_not_select_latest_directory_by_timestamp`
- `do_not_mark_pdf_english_adapter_ready_without_manifest_check_and_smoke`

Candidate roots outside the workspace are reported by label only; absolute local paths are not a reproducible input contract.
