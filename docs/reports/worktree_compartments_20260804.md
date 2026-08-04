# Worktree Compartments 2026-08-04

This report separates current dirty worktree changes into review compartments.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `doc_english_code_import`: 23
- `final_chain_registry`: 8
- `worktree_compartment_report`: 1

## Commit Handling

- commit final_chain_registry files separately from foundation_hardening files
- do not include validation_report_refresh files unless intentionally updating generated reports
- review mixed_control_file changes line-by-line before staging

## Records

- ` M` `final_chain_registry` `docs/reports/final_chain_cleanroom_import_audit_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_cleanroom_import_audit_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_control_dashboard_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_control_dashboard_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tests/test_final_chain_control.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `worktree_compartment_report` `tools/build_worktree_compartment_report.py`: review compartment documentation and report generator
- `??` `doc_english_code_import` `config/english_docx_native_md/`: copied from DOCX English protected code/config/prompt paths
- `??` `final_chain_registry` `docs/reports/doc_english_code_import_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/doc_english_code_import_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `doc_english_code_import` `prompts/english_docx_cloze_child_skill_tagger_v01.system.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_cloze_child_skill_tagger_v01.user.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_grammar_child_formatter_v01.system.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_grammar_child_formatter_v01.user.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_reading_child_enhancer_v01.system.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_reading_child_enhancer_v01.user.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_seven_choice_child_formatter_v01.system.md`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `prompts/english_docx_seven_choice_child_formatter_v01.user.md`: copied from DOCX English protected code/config/prompt paths
- `??` `final_chain_registry` `tools/build_doc_english_code_import_report.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `doc_english_code_import` `tools/english_docx_child_skill_tagger_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_cloze_child_skill_tagger_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_grammar_child_formatter_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_group_boundary_cutter_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_group_field_normalizer_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_group_itemizer_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_group_repair_gate_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_integrated_chain_runner_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_native_md_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_optimized_review_renderer_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_parent_child_projection_v02.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_parent_only_review_pack_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_reading_child_enhancer_v01.py`: copied from DOCX English protected code/config/prompt paths
- `??` `doc_english_code_import` `tools/english_docx_seven_choice_child_formatter_v01.py`: copied from DOCX English protected code/config/prompt paths
