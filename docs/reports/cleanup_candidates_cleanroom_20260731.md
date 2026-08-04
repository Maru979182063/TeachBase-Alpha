# Cleanup Candidate Report

Target root label: `cleanroom_partial_project`

Non-destructive candidate report. This does not authorize deletion.

## Action Counts

| Action | Count |
| --- | ---: |
| `archive_candidate` | 5 |
| `needs_review_finalish_name` | 9 |
| `needs_review_historical_code_or_test` | 29 |

## Risk Counts

| Risk | Count |
| --- | ---: |
| `low` | 5 |
| `review` | 38 |

## Samples

### `archive_candidate`

- `docs/backup_restore_runbook.md` (historical_or_probe_surface): name contains historical marker(s): backup
- `docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md` (historical_or_probe_surface): name contains historical marker(s): demo
- `outputs/pipeline_baseline_snapshot` (unregistered_output_surface): output surface not protected by final-chain registry
- `outputs/pipeline_baseline_snapshot/control_plane_20260714_v02` (unregistered_output_surface): output surface not protected by final-chain registry
- `outputs/pipeline_baseline_snapshot/semantic_shadow_review_path_20260714_v01` (unregistered_output_surface): output surface not protected by final-chain registry

### `needs_review_finalish_name`

- `docs/production_readiness_final_report.md` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/final_chain_inventory_20260731.json` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/final_chain_inventory_20260731.md` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_cleanroom_20260731.json` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_cleanroom_20260731.md` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_old_local_20260731.json` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_old_local_20260731.md` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/modularization_phase2a_final_20260715.md` (finalish_name_needs_review): name contains final-like marker(s): final
- `docs/reports/repository_rescue_phase1_final_20260715.md` (finalish_name_needs_review): name contains final-like marker(s): final

### `needs_review_historical_code_or_test`

- `config/final_chain_registry.yaml` (finalish_name_needs_review): name contains final-like marker(s): final
- `config/migrations/20260624_three_track_final_review_hardening.sql` (finalish_name_needs_review): name contains final-like marker(s): final
- `tests/postgres-sole-source/runtime_postgres_sole_source_full.mjs` (finalish_name_needs_review): name contains final-like marker(s): full
- `tests/test_final_chain_registry.py` (finalish_name_needs_review): name contains final-like marker(s): final
- `tests/test_final_chain_surface_classifier.py` (finalish_name_needs_review): name contains final-like marker(s): final
- `tools/classify_final_chain_surface.py` (finalish_name_needs_review): name contains final-like marker(s): final
- `tools/run_split_v03_full_doc.py` (finalish_name_needs_review): name contains final-like marker(s): full
- `tools/run_teacher_handout_full_flow.ps1` (finalish_name_needs_review): name contains final-like marker(s): full
- `tools/run_teacher_handout_full_flow.py` (finalish_name_needs_review): name contains final-like marker(s): full
- `tools/runtime_baseline_final_review.mjs` (finalish_name_needs_review): name contains final-like marker(s): final
- `tools/validate_final_chain_registry.py` (finalish_name_needs_review): name contains final-like marker(s): final
- `config/ngrok.demo.yml` (historical_or_probe_surface): name contains historical marker(s): demo
- `tests/backup-restore/runtime_backup_restore.mjs` (historical_or_probe_surface): name contains historical marker(s): backup
- `tests/performance/runtime_smoke_load.mjs` (historical_or_probe_surface): name contains historical marker(s): smoke
- `tests/release_gate/02_backup_restore.test.mjs` (historical_or_probe_surface): name contains historical marker(s): backup
- `tests/release_gate/15_legacy_regression.test.mjs` (historical_or_probe_surface): name contains historical marker(s): legacy
- `tests/release_gate/16_performance_smoke.test.mjs` (historical_or_probe_surface): name contains historical marker(s): smoke
- `tools/compose_legacy_stem_md.py` (historical_or_probe_surface): name contains historical marker(s): legacy
- `tools/package_leader_demo.mjs` (historical_or_probe_surface): name contains historical marker(s): demo
- `tools/probe_ark_auth.ps1` (historical_or_probe_surface): name contains historical marker(s): probe
- `tools/runtime_backbone_backup_restore.mjs` (historical_or_probe_surface): name contains historical marker(s): backup
- `tools/runtime_backbone_load_smoke.mjs` (historical_or_probe_surface): name contains historical marker(s): smoke
- `tools/semantic_role_eval_legacy_predictor.py` (historical_or_probe_surface): name contains historical marker(s): legacy
- `tools/split_v03_recovery_smoke.py` (historical_or_probe_surface): name contains historical marker(s): smoke
- `tools/start_demo_stack.ps1` (historical_or_probe_surface): name contains historical marker(s): demo
- `tools/start_runtime_backbone_demo.ps1` (historical_or_probe_surface): name contains historical marker(s): demo
- `tools/stop_demo_stack.ps1` (historical_or_probe_surface): name contains historical marker(s): demo
- `tools/stop_runtime_backbone_demo.ps1` (historical_or_probe_surface): name contains historical marker(s): demo
- `tools/visual_unit_planner_probe.py` (historical_or_probe_surface): name contains historical marker(s): probe
