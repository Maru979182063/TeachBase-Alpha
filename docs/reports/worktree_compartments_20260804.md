# Worktree Compartments 2026-08-04

This report separates current dirty worktree changes into review compartments.
All paths are relative git paths; no local absolute path is part of the reproducible input contract.

## Counts

- `final_chain_registry`: 73
- `foundation_hardening`: 1
- `mixed_control_file`: 1
- `precleanup_safety_gate`: 1
- `worktree_compartment_report`: 3

## Commit Handling

- commit final_chain_registry files separately from foundation_hardening files
- do not include validation_report_refresh files unless intentionally updating generated reports
- review mixed_control_file changes line-by-line before staging

## Records

- ` M` `final_chain_registry` `config/final_chain_registry.yaml`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_goal_gap_audit_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_goal_gap_audit_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_hardening_manifest_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_hardening_manifest_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_hardening_manifest_validation_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_hardening_manifest_validation_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_hardening_status_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/cleanroom_hardening_status_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_batch_queue_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_batch_queue_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_batch_queue_validation_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_batch_queue_validation_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_control_contract_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_control_contract_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_environment_contract_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_environment_contract_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ops_gate_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ops_gate_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ops_health_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ops_health_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_orchestrator_handshake_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_orchestrator_handshake_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_orchestrator_handshake_validation_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_orchestrator_handshake_validation_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ready_sample_dry_run_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/final_chain_ready_sample_dry_run_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `foundation_hardening` `docs/reports/foundation_hardening_test_report_20260803.json`: artifact atomicity or model retry/checkpoint hardening
- ` M` `final_chain_registry` `docs/reports/pdf_english_manifest_recovery_audit_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_manifest_recovery_audit_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_rebuild_decision_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_rebuild_decision_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_recovery_intake_validation_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_recovery_intake_validation_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_recovery_validation_20260804.json`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `docs/reports/pdf_english_recovery_validation_20260804.md`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `precleanup_safety_gate` `docs/reports/precleanup_safety_gate_20260804.json`: combined guard for protected-chain cleanup work
- ` M` `worktree_compartment_report` `docs/reports/worktree_compartments_20260804.json`: review compartment documentation and report generator
- ` M` `worktree_compartment_report` `docs/reports/worktree_compartments_20260804.md`: review compartment documentation and report generator
- ` M` `mixed_control_file` `package.json`: foundation_hardening npm script; final_chain_registry npm scripts; precleanup_archive npm scripts; precleanup_deep_audit npm script; precleanup_safety npm script; cleanroom_goal_gap audit npm script; pdf_english_recovery_intake audit npm script; pdf_english_rebuild_decision audit npm script; pdf_english_rebuild_smoke audit npm script; pdf_english_raw_pdf_promotion audit npm script; final_chain_ops_health audit npm script; final_chain_execution_gap audit npm script
- ` M` `final_chain_registry` `src/teachbase/final_chains/__init__.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `src/teachbase/final_chains/adapters.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `src/teachbase/final_chains/control.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `src/teachbase/final_chains/control_contract.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `src/teachbase/final_chains/environment.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `src/teachbase/final_chains/readiness.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tests/test_cleanroom_goal_gap_audit.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tests/test_final_chain_control.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tests/test_final_chain_registry.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_cleanroom_goal_gap_audit.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_cleanroom_hardening_manifest.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_final_chain_batch_queue_report.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_final_chain_ops_health.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_final_chain_orchestrator_handshake.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_final_chain_ready_sample_report.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_pdf_english_rebuild_decision.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/build_pdf_english_recovery_source_audit.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `worktree_compartment_report` `tools/build_worktree_compartment_report.py`: review compartment documentation and report generator
- ` M` `final_chain_registry` `tools/final_chain_control.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/run_cleanroom_hardening_status_gate.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/run_final_chain_ops_gate.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/validate_cleanroom_hardening_manifest.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/validate_final_chain_batch_queue_report.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/validate_final_chain_orchestrator_handshake.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/validate_final_chain_registry.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/validate_pdf_english_recovery.py`: protected-chain inventory, classifier, or cleanup candidate audit
- ` M` `final_chain_registry` `tools/validate_pdf_english_recovery_intake.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `config/english_text_first_graph_first/`: PDF English graph-first manifest and smoke evidence
- `??` `final_chain_registry` `docs/reports/final_chain_execution_gap_20260806.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/final_chain_execution_gap_20260806.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_graph_first_rebuild_smoke_20260806.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_graph_first_rebuild_smoke_20260806.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_raw_pdf_promotion_20260806.json`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `docs/reports/pdf_english_raw_pdf_promotion_20260806.md`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `src/teachbase/final_chains/execution.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tests/fixtures/final_chain_samples/pdf_english_sample.pdf`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tools/build_final_chain_execution_gap_report.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tools/build_pdf_english_graph_first_rebuild_smoke.py`: protected-chain inventory, classifier, or cleanup candidate audit
- `??` `final_chain_registry` `tools/build_pdf_english_raw_pdf_promotion_gate.py`: protected-chain inventory, classifier, or cleanup candidate audit
