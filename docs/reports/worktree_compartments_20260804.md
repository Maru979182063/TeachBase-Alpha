# Worktree Compartments 2026-08-04

This report separates current dirty worktree changes into review compartments.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `docx_math_final_import`: 36
- `final_chain_registry`: 8
- `worktree_compartment_report`: 3

## Commit Handling

- commit final_chain_registry files separately from foundation_hardening files
- do not include validation_report_refresh files unless intentionally updating generated reports
- review mixed_control_file changes line-by-line before staging

## Records

- ` M` `final_chain_registry` `docs/reports/final_chain_cleanroom_import_audit_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_cleanroom_import_audit_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_control_dashboard_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_control_dashboard_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `worktree_compartment_report` `docs/reports/worktree_compartments_20260804.json`: review compartment documentation and report generator
- ` M` `worktree_compartment_report` `docs/reports/worktree_compartments_20260804.md`: review compartment documentation and report generator
- ` M` `final_chain_registry` `tests/test_final_chain_control.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `worktree_compartment_report` `tools/build_worktree_compartment_report.py`: review compartment documentation and report generator
- `??` `docx_math_final_import` `config/docx_asset_role_visual_tagger_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_math_long_packet_assembler_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_math_pipeline_final_active_manifest.json`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_math_pipeline_final_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_native_block_tagger_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_native_stage0_router_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_question_boundary_cutter_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_question_complexity_router_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_question_part_long_normalizer_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_question_part_normalizer_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `config/docx_question_part_twostage_probe_v01.yaml`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `docs/docx_math_pipeline_final_repro.md`: copied from verified DOCX math final-chain handoff inventory
- `??` `final_chain_registry` `docs/reports/docx_math_final_import_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/docx_math_final_import_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `docx_math_final_import` `prompts/`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `schemas/`: copied from verified DOCX math final-chain handoff inventory
- `??` `final_chain_registry` `tools/build_docx_math_final_import_report.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `docx_math_final_import` `tools/docx_asset_role_visual_tagger_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_legacy_formula_recovery_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_build_side_by_side_review_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_fullchain_orchestrator_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_long_composite_refiner_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_long_packet_assembler_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_pipeline_final_orchestrator_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_question_refiner_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_refine_gate_repair_orchestrator_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_math_source_backed_draft_builder_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_native_block_tagger_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_native_stage0_router_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_native_transcription_package_builder_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_question_boundary_cutter_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_question_complexity_router_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_question_part_long_normalizer_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_question_part_normalizer_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_question_part_twostage_probe_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/docx_run_math_normalizer_v01.py`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/katex_validate_math.cjs`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/mathml_to_latex_batch.cjs`: copied from verified DOCX math final-chain handoff inventory
- `??` `docx_math_final_import` `tools/ruby_mtef_to_mathml_batch.rb`: copied from verified DOCX math final-chain handoff inventory
