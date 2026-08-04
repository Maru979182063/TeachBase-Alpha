# Worktree Compartments 2026-08-04

This report separates current dirty worktree changes into review compartments.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `final_chain_registry`: 7
- `mixed_control_file`: 1
- `worktree_compartment_report`: 1

## Commit Handling

- commit final_chain_registry files separately from foundation_hardening files
- do not include validation_report_refresh files unless intentionally updating generated reports
- review mixed_control_file changes line-by-line before staging

## Records

- ` M` `final_chain_registry` `docs/reports/final_chain_ops_gate_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ops_gate_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `mixed_control_file` `package.json`: foundation_hardening npm script; final_chain_registry npm scripts; precleanup_archive npm scripts; precleanup_deep_audit npm script; precleanup_safety npm script
- ` M` `final_chain_registry` `tests/test_final_chain_control.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `worktree_compartment_report` `tools/build_worktree_compartment_report.py`: review compartment documentation and report generator
- ` M` `final_chain_registry` `tools/run_final_chain_ops_gate.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_recovery_validation_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_recovery_validation_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tools/validate_pdf_english_recovery.py`: protected-chain inventory, classifier, or cleanup candidate audit
