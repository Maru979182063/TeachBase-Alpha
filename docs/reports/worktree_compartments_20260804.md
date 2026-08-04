# Worktree Compartments 2026-08-04

This report separates current dirty worktree changes into review compartments.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `final_chain_registry`: 2
- `worktree_compartment_report`: 1

## Commit Handling

- commit final_chain_registry files separately from foundation_hardening files
- do not include validation_report_refresh files unless intentionally updating generated reports
- review mixed_control_file changes line-by-line before staging

## Records

- ` M` `worktree_compartment_report` `tools/build_worktree_compartment_report.py`: review compartment documentation and report generator
- `??` `final_chain_registry` `docs/reports/pdf_english_manifest_recovery_audit_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_manifest_recovery_audit_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
