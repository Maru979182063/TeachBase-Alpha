# Worktree Compartments 2026-08-04

This report separates current dirty worktree changes into review compartments.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `final_chain_registry`: 6
- `mixed_control_file`: 1
- `worktree_compartment_report`: 3

## Commit Handling

- commit final_chain_registry files separately from foundation_hardening files
- do not include validation_report_refresh files unless intentionally updating generated reports
- review mixed_control_file changes line-by-line before staging

## Records

- ` M` `worktree_compartment_report` `docs/reports/worktree_compartments_20260804.json`: review compartment documentation and report generator
- ` M` `worktree_compartment_report` `docs/reports/worktree_compartments_20260804.md`: review compartment documentation and report generator
- ` M` `mixed_control_file` `package.json`: foundation_hardening npm script; final_chain_registry npm scripts; precleanup_archive npm scripts; precleanup_deep_audit npm script; precleanup_safety npm script; cleanroom_goal_gap audit npm script; pdf_english_recovery_intake audit npm script; pdf_english_rebuild_decision audit npm script; pdf_english_rebuild_smoke audit npm script; pdf_english_raw_pdf_promotion audit npm script; final_chain_ops_health audit npm script; final_chain_execution_gap audit npm script; java_shell_contract audit and test npm scripts
- ` M` `worktree_compartment_report` `tools/build_worktree_compartment_report.py`: review compartment documentation and report generator
- `??` `final_chain_registry` `config/java_shell_contract_v01.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/java_shell_contract_v01.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/java_shell_contract_validation_20260806.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/java_shell_contract_validation_20260806.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tests/test_java_shell_contract.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tools/validate_java_shell_contract.py`: protected-chain inventory, classifier, or cleanup candidate audit
