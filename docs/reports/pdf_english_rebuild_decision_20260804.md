# PDF English Rebuild Decision 2026-08-04

Status: `rebuild_track_allowed`
Rebuild track allowed: `true`
Ready claim allowed: `false`

## Checks

- `pass` `legacy_artifact_recovery_is_not_ready`
- `pass` `cleanroom_v05_rebuild_scaffold_present`
- `pass` `old_local_graph_first_source_code_available_if_present`
- `pass` `portable_regression_passes_without_model_or_runtime`

## Required Promotion Evidence

- `cleanroom_import_of_required_graph_first_source_files`
- `new_active_manifest_generated_from_fresh_rebuild_outputs`
- `english_text_first_graph_first_manifest_check_passes`
- `new_small_pdf_smoke_package_zip_testzip_is_none`
- `final_chain_registry_pdf_english_readiness_updated_only_after_smoke`

## Unsafe Actions

- `do_not_synthesize_old_active_manifest`
- `do_not_claim_20260728_smoke_recovered_without_artifacts`
- `do_not_mark_pdf_english_ready_from_v05_fixture_tests_only`
- `do_not_select_latest_outputs_by_timestamp`

All source roots are recorded by label only; no local absolute path is part of the reproducible input contract.
