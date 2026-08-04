# Final Chain Cleanroom Import Audit 2026-08-04

This report checks canonical final-chain files before importing them into the cleanroom.
All recorded file locations are relative git paths or source labels; local absolute source roots are not part of the reproducible input contract.

## Summary

- chains: `4`
- required rows: `8`
- missing in cleanroom: `4`
- rows with source candidates: `7`

## Rows

- `doc_math` `canonical_entrypoint` `tools/docx_math_pipeline_final_orchestrator_v01.py`: `already_present_in_cleanroom`, candidates: `old_local`
- `doc_math` `canonical_config_1` `config/docx_math_pipeline_final_v01.yaml`: `already_present_in_cleanroom`, candidates: `old_local`
- `doc_math` `canonical_config_2` `config/docx_math_pipeline_final_active_manifest.json`: `already_present_in_cleanroom`, candidates: `old_local`
- `doc_english` `canonical_entrypoint` `tools/english_docx_native_md_v01.py`: `candidate_available_for_reviewed_import`, candidates: `old_local`
- `doc_english` `canonical_config_1` `config/english_docx_native_md/active_manifest.json`: `candidate_available_for_reviewed_import`, candidates: `old_local`
- `doc_english` `canonical_config_2` `config/english_docx_native_md/group_repair_gate_v01.json`: `candidate_available_for_reviewed_import`, candidates: `old_local`
- `pdf_math` `canonical_entrypoint` `tools/run_question_ingest_skill.py`: `already_present_in_cleanroom`, candidates: `old_local`
- `pdf_english` `canonical_entrypoint` `config/english_text_first_graph_first/active_manifest.json`: `source_missing_or_not_provided`, candidates: `none`
