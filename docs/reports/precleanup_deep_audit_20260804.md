# Precleanup Deep Audit 2026-08-04

This is a pre-execution authorization snapshot, not a post-archive state report.
It authorizes only `archive_allowed` roots, and the archive executor must revalidate them before moving files.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Summary

- precleanup safety ok: `True`
- archive candidate source count: `5`
- effective archive roots: `3`
- archive allowed: `0`
- blocked needs review: `3`
- review candidates not in scope: `38`

## Allowed Archive Roots

- None

## Blocked Roots

- `docs/backup_restore_runbook.md`: blockers=['path_missing']
  - ref: `docs/reports/cleanup_candidates_cleanroom_20260731.json:41:        "path": "docs/backup_restore_runbook.md",`
  - ref: `tools/build_worktree_compartment_report.py:77:    "docs/backup_restore_runbook.md",`
  - ref: `docs/reports/cleanup_candidates_old_local_20260731.md:28:- `docs/backup_restore_runbook.md` (historical_or_probe_surface): name contains historical marker(s): backup`
  - ref: `docs/reports/cleanup_candidates_cleanroom_20260731.md:26:- `docs/backup_restore_runbook.md` (historical_or_probe_surface): name contains historical marker(s): backup`
  - ref: `docs/reports/final_chain_surface_classification_cleanroom_20260731.json:258:      "path": "docs/backup_restore_runbook.md",`
  - generated report refs ignored: `13`
  - guard metadata refs ignored: `1`
- `outputs/pipeline_baseline_snapshot`: blockers=['referenced_by_repo']
  - ref: `tests/test_precleanup_post_archive_report.py:48:            {"path": "outputs/pipeline_baseline_snapshot", "blockers": ["referenced_by_repo"]},`
  - ref: `tests/test_precleanup_post_archive_report.py:94:            {"path": "outputs/pipeline_baseline_snapshot", "blockers": ["referenced_by_repo"]},`
  - ref: `tests/test_precleanup_post_archive_report.py:137:            {"path": "outputs/pipeline_baseline_snapshot", "blockers": ["referenced_by_repo"]},`
  - ref: `config/pipeline_registry.yaml:128:        "outputs/pipeline_baseline_snapshot"`
  - ref: `config/pipeline_registry.yaml:182:        "outputs/pipeline_baseline_snapshot"`
- `docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md`: blockers=['path_missing']
  - ref: `tools/build_worktree_compartment_report.py:78:    "docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md",`
  - ref: `docs/reports/cleanup_candidates_cleanroom_20260731.json:54:        "path": "docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md",`
  - ref: `docs/reports/cleanup_candidates_cleanroom_20260731.md:27:- `docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md` (historical_or_probe_surface): name contains historical marker(s): demo`
  - ref: `docs/reports/cleanup_candidates_old_local_20260731.md:29:- `docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md` (historical_or_probe_surface): name contains historical marker(s): demo`
  - ref: `docs/reports/cleanup_candidates_old_local_20260731.json:57:        "path": "docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md",`
  - generated report refs ignored: `13`
  - guard metadata refs ignored: `1`

## Rules

- only archive_candidate + low risk entries may be considered
- parent directories absorb child candidates; duplicate child moves are suppressed
- any repository reference blocks archive
- any protected final-chain overlap blocks archive
- missing paths or paths outside workspace block archive
- blocked_needs_review entries are not moved, archived, or deleted
- allowed entries are revalidated by the archive executor before any filesystem move
- reference counts ending in _capped are sample counts, not total repository counts
- generated reports and cleanup guard metadata are classified separately from blocking repository references
