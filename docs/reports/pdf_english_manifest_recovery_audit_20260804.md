# PDF English Manifest Recovery Audit 2026-08-04

The protected PDF English chain requires `config/english_text_first_graph_first/active_manifest.json`.

Searches were performed by location label only: `projects_root`, `user_documents`, `user_home`, and `cleanroom_git_history`. The active manifest and `final_chain_smoke_20260728` artifacts were not found.

Status: `blocked_missing_manifest_and_smoke_artifacts`.

Safe next actions:

- `restore_active_manifest_from_original_machine_or_backup`
- `restore_final_chain_smoke_20260728_artifacts_if_available`
- `otherwise_rerun_manifest_check_and_small_smoke_before_claiming_ready`

Unsafe actions:

- `do_not_create_synthetic_active_manifest`
- `do_not_select_latest_directory_by_timestamp`
- `do_not_mark_pdf_english_adapter_ready_without_manifest_check`

All paths are relative git paths or location labels; no local absolute path is part of the reproducible input contract.
