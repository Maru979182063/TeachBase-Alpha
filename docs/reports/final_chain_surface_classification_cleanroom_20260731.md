# Final Chain Surface Classification

Target root label: `cleanroom_partial_project`

This is a non-destructive classification report. It does not authorize deletion.

## Summary

| Category | Count |
| --- | ---: |
| `chain_adjacent_needs_review` | 12 |
| `finalish_name_needs_review` | 20 |
| `historical_or_probe_surface` | 20 |
| `protected_final_chain_surface` | 32 |
| `unclassified_non_chain_surface` | 269 |
| `unregistered_output_surface` | 3 |

## Chain Counts

| Chain | Count |
| --- | ---: |
| `doc_math` | 8 |
| `pdf_english` | 22 |
| `pdf_math` | 14 |

## Samples

### `chain_adjacent_needs_review`

- `config/docx_native_text_repair_system_prompt.md` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `config/docx_native_text_repair_user_template.md` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `docs/reports/math_formula_and_image_ownership_output_audit_v0.1_20260624.md` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `tests/fixtures/docx_native_repair_v01/question_packets_formula_tokens.json` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `tests/fixtures/docx_native_repair_v01/recorded_text_repair_response.json` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `tools/docx_native_formula_providers.py` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `tools/docx_native_formula_token_stream_v01.py` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `tools/docx_native_text_repair_model_node_v01.py` (file) `doc_math`: matches chain naming hints but is not protected by registry
- `tools/english_text_first_model_graph_regression_v01.py` (file) `pdf_english`: matches chain naming hints but is not protected by registry
- `config/teacher_handout_visual_prompts.yaml` (file) `pdf_math`: matches chain naming hints but is not protected by registry
- `docs/reports/run_question_ingest_modularization_v02_plan.md` (file) `pdf_math`: matches chain naming hints but is not protected by registry
- `tests/fixtures/teacher_handout_visual_transcription_testset_10q.json` (file) `pdf_math`: matches chain naming hints but is not protected by registry

### `finalish_name_needs_review`

- `config/final_chain_registry.yaml` (file): name contains final-like marker(s): final
- `config/migrations/20260624_three_track_final_review_hardening.sql` (file): name contains final-like marker(s): final
- `docs/production_readiness_final_report.md` (file): name contains final-like marker(s): final
- `docs/reports/final_chain_inventory_20260731.json` (file): name contains final-like marker(s): final
- `docs/reports/final_chain_inventory_20260731.md` (file): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_cleanroom_20260731.json` (file): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_cleanroom_20260731.md` (file): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_old_local_20260731.json` (file): name contains final-like marker(s): final
- `docs/reports/final_chain_surface_classification_old_local_20260731.md` (file): name contains final-like marker(s): final
- `docs/reports/modularization_phase2a_final_20260715.md` (file): name contains final-like marker(s): final
- `docs/reports/repository_rescue_phase1_final_20260715.md` (file): name contains final-like marker(s): final
- `tests/postgres-sole-source/runtime_postgres_sole_source_full.mjs` (file): name contains final-like marker(s): full
- `tests/test_final_chain_registry.py` (file): name contains final-like marker(s): final
- `tests/test_final_chain_surface_classifier.py` (file): name contains final-like marker(s): final
- `tools/classify_final_chain_surface.py` (file): name contains final-like marker(s): final
- `tools/run_split_v03_full_doc.py` (file): name contains final-like marker(s): full
- `tools/run_teacher_handout_full_flow.ps1` (file): name contains final-like marker(s): full
- `tools/run_teacher_handout_full_flow.py` (file): name contains final-like marker(s): full
- `tools/runtime_baseline_final_review.mjs` (file): name contains final-like marker(s): final
- `tools/validate_final_chain_registry.py` (file): name contains final-like marker(s): final

### `historical_or_probe_surface`

- `config/ngrok.demo.yml` (file): name contains historical marker(s): demo
- `docs/backup_restore_runbook.md` (file): name contains historical marker(s): backup
- `docs/reports/visual_pipeline_and_manual_transcription_demo_v0.1_20260624.md` (file): name contains historical marker(s): demo
- `tests/backup-restore/runtime_backup_restore.mjs` (file): name contains historical marker(s): backup
- `tests/performance/runtime_smoke_load.mjs` (file): name contains historical marker(s): smoke
- `tests/release_gate/02_backup_restore.test.mjs` (file): name contains historical marker(s): backup
- `tests/release_gate/15_legacy_regression.test.mjs` (file): name contains historical marker(s): legacy
- `tests/release_gate/16_performance_smoke.test.mjs` (file): name contains historical marker(s): smoke
- `tools/compose_legacy_stem_md.py` (file): name contains historical marker(s): legacy
- `tools/package_leader_demo.mjs` (file): name contains historical marker(s): demo
- `tools/probe_ark_auth.ps1` (file): name contains historical marker(s): probe
- `tools/runtime_backbone_backup_restore.mjs` (file): name contains historical marker(s): backup
- `tools/runtime_backbone_load_smoke.mjs` (file): name contains historical marker(s): smoke
- `tools/semantic_role_eval_legacy_predictor.py` (file): name contains historical marker(s): legacy
- `tools/split_v03_recovery_smoke.py` (file): name contains historical marker(s): smoke
- `tools/start_demo_stack.ps1` (file): name contains historical marker(s): demo
- `tools/start_runtime_backbone_demo.ps1` (file): name contains historical marker(s): demo
- `tools/stop_demo_stack.ps1` (file): name contains historical marker(s): demo
- `tools/stop_runtime_backbone_demo.ps1` (file): name contains historical marker(s): demo
- `tools/visual_unit_planner_probe.py` (file): name contains historical marker(s): probe

### `protected_final_chain_surface`

- `config/english_text_first_v05.yaml` (file) `pdf_english`: matches protected path config/english_text_first_v05.yaml
- `tests/fixtures/english_text_first_v05/english_text_first_v05.fixture_config.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/human_acceptance_review/human_acceptance_review.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/page_images/reading_portable_p001.png` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/page_images/writing_portable_p001.png` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/semantic_reference_v03b/reading_portable/question_packets.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/semantic_reference_v03b/writing_portable/question_packets.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/unit_and_v04c/reading_portable/evidence_bundle.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/unit_and_v04c/reading_portable/question_packets.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/unit_and_v04c/reading_portable/unit_bundle.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/unit_and_v04c/writing_portable/evidence_bundle.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/unit_and_v04c/writing_portable/question_packets.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/unit_and_v04c/writing_portable/unit_bundle.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/vlm_transcriber/reading_portable/page_001/meta.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/fixtures/english_text_first_v05/vlm_transcriber/writing_portable/page_001/meta.json` (file) `pdf_english`: matches protected path tests/fixtures/english_text_first_v05
- `tests/test_english_text_first_sidecar_graph_v01.py` (file) `pdf_english`: matches protected path tests/test_english_text_first_sidecar_graph_v01.py
- `tests/test_english_text_first_v05_pipeline.py` (file) `pdf_english`: matches protected path tests/test_english_text_first_v05_pipeline.py
- `tools/english_text_first_sidecar_graph_v01.py` (file) `pdf_english`: matches protected path tools/english_text_first_sidecar_graph_v01.py
- `tools/english_text_first_v05_model_gate.py` (file) `pdf_english`: matches protected path tools/english_text_first_v05_model_gate.py
- `tools/english_text_first_v05_pipeline.py` (file) `pdf_english`: matches protected path tools/english_text_first_v05_pipeline.py
- `tools/english_text_first_verifier_projector_v02.py` (file) `pdf_english`: matches protected path tools/english_text_first_verifier_projector_v02.py
- `tools/apply_format_normalize_existing_results.py` (file) `pdf_math`: matches protected path tools/apply_format_normalize_existing_results.py
- `tools/assetize_question_images.py` (file) `pdf_math`: matches protected path tools/assetize_question_images.py
- `tools/audit_question_asset_package.py` (file) `pdf_math`: matches protected path tools/audit_question_asset_package.py
- `tools/build_figure_candidate_source.py` (file) `pdf_math`: matches protected path tools/build_figure_candidate_source.py

### `unclassified_non_chain_surface`

- `config/migrations/20260623_postgres_sole_source.sql` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/migrations/20260623_runtime_backbone_validation.sql` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/migrations/20260624_three_track_validation_alignment.sql` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/pipeline_feature_flags.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/pipeline_registry.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/runtime_observability.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/biology.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/common.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/content_blocks.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/document_types.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/english.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/math.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/route_availability.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/semantic_profiles/thresholds.yaml` (file): no protected, legacy, historical, or chain-adjacent signal
- `config/subject_tracks.json` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/README.md` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/architecture/teachbase_python_architecture_v01.md` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/artifact_lineage.md` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/db/后端数据库草案_v0.1.sql` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/diagrams/项目开发管理工作流图.svg` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/mermaid-render-config.json` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/pipeline_maintenance_and_isolation.md` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/planning/后端处理结构设计_v0.2.md` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/planning/后端处理结构设计_v0.3.md` (file): no protected, legacy, historical, or chain-adjacent signal
- `docs/planning/后端实施清单_v0.1.md` (file): no protected, legacy, historical, or chain-adjacent signal

### `unregistered_output_surface`

- `outputs/pipeline_baseline_snapshot` (directory): output surface not protected by final-chain registry
- `outputs/pipeline_baseline_snapshot/control_plane_20260714_v02` (directory): output surface not protected by final-chain registry
- `outputs/pipeline_baseline_snapshot/semantic_shadow_review_path_20260714_v01` (directory): output surface not protected by final-chain registry
