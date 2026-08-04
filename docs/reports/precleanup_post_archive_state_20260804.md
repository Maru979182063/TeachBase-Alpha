# Precleanup Post Archive State 2026-08-04

This report inspects the filesystem after archive execution. It does not move, delete, or restore files.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Summary

- ok: `True`
- archive root: `_archive/precleanup_20260804`
- expected archive files: `2`
- actual archive files: `2`

## Checks

- `execution_report_successful_real_run`: `True`
- `current_deep_audit_not_executable`: `True`
- `current_deep_audit_has_no_allowed_roots`: `True`
- `moved_sources_blocked_as_missing`: `True`
- `baseline_snapshot_still_blocked_by_reference`: `True`
- `all_move_inspections_ok`: `True`
- `no_unexpected_archive_files`: `True`
- `no_missing_archive_files`: `True`

## Moves

- `docs/backup_restore_runbook.md` -> `_archive/precleanup_20260804/docs/backup_restore_runbook.md` ok=`True`
- `docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md` -> `_archive/precleanup_20260804/docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md` ok=`True`
