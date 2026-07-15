# Semantic Role Effectiveness Evaluation v0.1

## Real Status

Status: `SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED`

This run built an evaluation harness and produced a local evaluation artifact set, but it did not satisfy the VERIFIED dataset coverage gate. The result is not a production-readiness claim and not an effective-route-readiness claim.

## Start Commit

`6747169c0ed405844e6822dbef51057561ed5e5c`

## Current Code Actually Added

- `tests/fixtures/semantic_role_effectiveness_v01/schema.json`
- `tests/fixtures/semantic_role_effectiveness_v01/fixture_cases.json`
- `tools/semantic_role_eval_metrics.py`
- `tools/run_semantic_role_effectiveness_eval.py`
- `tests/test_semantic_role_eval_schema.py`
- `tests/test_semantic_role_eval_metrics.py`
- `tests/test_semantic_role_gold_leakage.py`
- `tests/test_semantic_role_effectiveness_run.py`

The evaluation runner calls the existing deterministic Semantic Role Shadow adapter. It does not modify Semantic Role rules, route enums, confidence thresholds, prompts, Runtime, database schema, DOCX Native, or English Text-first code.

## Actual Evaluation Run

Command:

```powershell
python tools\run_semantic_role_effectiveness_eval.py --run-id semantic_role_effectiveness_eval_20260715_v01 --candidate-target 40
```

Output directory:

`outputs/semantic_role_effectiveness_eval/semantic_role_effectiveness_eval_20260715_v01/`

Reported run summary:

- candidate cases: 40
- VERIFIED cases used for formal metrics: 12
- REVIEW_REQUIRED candidates: 28
- paid model invoked: false
- database write attempted: false
- Runtime import attempted: false
- Hard Safety Gate: passed
- Dataset Coverage Gate: failed

The process returned a non-zero status because the run status was intentionally gated as `SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED`.

## Metrics From This Run

These metrics are computed only from the 12 `VERIFIED` fixture-contract cases. They are useful for exercising the evaluator and exposing deterministic-rule behavior, but they are not enough to claim real business effectiveness.

- role exact match accuracy: 0.5833333333333334
- macro F1: 0.3363095238095238
- presentation kind accuracy: 1.0
- disposition accuracy: 0.75
- route candidate accuracy: 0.6666666666666666
- relation accuracy: 0.0
- critical misroute rate: 0.0
- false-safe rate: 0.0
- error capture rate: 1.0
- safe automation coverage: 0.25
- review rate across all predictions: 0.925

Per-subject role exact match:

- math: 0.8333333333333334 on 6 VERIFIED cases
- english: 0.3333333333333333 on 6 VERIFIED cases

## Dataset Coverage Gate

Failed conditions:

- VERIFIED total >= 24: false, actual 12
- VERIFIED math >= 10: false, actual 6
- VERIFIED english >= 10: false, actual 6

Passed conditions:

- edge cases >= 4
- at least 6 semantic roles covered
- at least one review path exists
- at least one relation case exists

No biology effectiveness conclusion is made because no verified biology Gold sample was established in this run.

## Bad Case Categories Observed

The evaluator reported 6 bad cases among the 12 VERIFIED fixture cases. Categories included:

- role_error
- route_error
- disposition_error
- relation_error
- mixed_not_detected
- current_node_type_bias

Important observations:

- Current deterministic rules caught all fixture errors behind `needs_role_review=true`, so `false_safe_rate=0.0` for this limited set.
- The English fixture set exposed weaker role distinction for answer explanation, method or strategy, question group, and source-material-like text.
- Relation handling is not yet reliable in this one-case runner shape, so relation accuracy is currently 0.0 on the fixture relation cases.

## Shadow Non-interference Recheck

Commands actually run:

```powershell
python tools\validate_pipeline_registry.py --json
python tests\test_pipeline_registry.py
python tests\test_semantic_role_shadow_isolation.py
python tools\run_semantic_shadow_real_rerun_validation.py --out-root outputs\semantic_role_shadow_effectiveness_validation_20260715_eval_recheck
```

Results:

- registry validator: ok, errors=0, warnings=0
- pipeline registry tests: 3 tests OK
- semantic shadow isolation tests: 8 tests OK
- ready-path real rerun non-interference: equality=true, compared artifacts=5
- review-path real rerun non-interference: equality=true, compared artifacts=5
- paid model invoked: false

## Generated Local Artifacts

The evaluation run produced:

- `evaluation_manifest.json`
- `verified_cases_snapshot.json`
- `predictions.json`
- `case_level_results.json`
- `metrics_summary.json`
- `per_role_metrics.json`
- `per_subject_metrics.json`
- `confusion_matrix.json`
- `critical_misroutes.json`
- `false_safe_cases.json`
- `review_capture_report.json`
- `confidence_calibration.json`
- `bad_cases.json`
- `dataset_coverage.json`
- `review_pack/index.html`
- `review_pack/cases/*.html`
- `review_pack/review_decisions.json`
- `run_summary.json`

These local artifacts are intentionally not used as proof of a production-ready semantic router.

## Remaining Gaps

- Need at least 24 VERIFIED real Gold cases before formal effectiveness baseline can be accepted.
- Need at least 10 VERIFIED math cases and 10 VERIFIED English cases from human-auditable business evidence.
- REVIEW_REQUIRED candidate pool needs manual labeling; current candidate discovery does not promote cases to Gold.
- Relation evaluation needs multi-node context cases rather than one-node fixture projections.
- The current deterministic rules appear conservative on the fixture set, but that is not enough to prove real-world accuracy.

## Current Conclusion

`SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED`
