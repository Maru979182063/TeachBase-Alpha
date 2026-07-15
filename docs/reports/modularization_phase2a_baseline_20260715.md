# Modularization Phase 2A Baseline 20260715

## Real Status

Baseline was captured from isolated worktree:

`C:\Users\EDY\Documents\TeachBase-Alpha-modularization-phase2a`

Branch:

`refactor/pipeline-modularization-phase2a-semantic-eval`

Base commit:

`c2d874a487a5dfaefa4ba76b7634ab883d2d2e24`

## Actually Run

Command:

`python tools/run_semantic_role_effectiveness_eval.py --run-id phase2a_baseline --out-root outputs/modularization_phase2a_golden/baseline`

Exit code:

`20`

Output directory:

`outputs/modularization_phase2a_golden/baseline/phase2a_baseline`

## Baseline Result

- status: `SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED`
- verified_real_gold_case_count: `0`
- contract_fixture_count: `12`
- candidate_case_count: `12`
- hard_safety_gate_passed: `true`
- dataset_coverage_gate_passed: `false`
- model_invoked: `false`
- paid_model_invoked: `false`
- database_write_attempted: `false`
- runtime_import_attempted: `false`

This is intentionally not a production-ready state. The current real Gold count is still zero, so the correct behavior remains exit code `20`.
