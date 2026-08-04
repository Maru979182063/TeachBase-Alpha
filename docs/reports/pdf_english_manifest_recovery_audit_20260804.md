# PDF English Manifest Recovery Audit 2026-08-04

Status: `blocked_missing_manifest_and_smoke_artifacts`
Source audit status: `no_importable_source_found`

## Sources

- `cleanroom_current`: `1/4` required artifacts
- `old_local_d_projects_jiaoyan`: `1/4` required artifacts
- `handoff_package_user_documents`: `0/4` required artifacts

## Safe Next Actions

- `restore_active_manifest_from_original_machine_or_backup`
- `restore_final_chain_smoke_20260728_artifacts_if_available`
- `otherwise_rerun_manifest_check_and_small_smoke_before_claiming_ready`

## Unsafe Actions

- `do_not_create_synthetic_active_manifest`
- `do_not_select_latest_directory_by_timestamp`
- `do_not_mark_pdf_english_adapter_ready_without_manifest_check`

All paths are relative git paths or location labels; no local absolute path is part of the reproducible input contract.
