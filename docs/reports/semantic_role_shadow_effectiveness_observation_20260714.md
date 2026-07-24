# Semantic Role Shadow Effectiveness Observation Audit 2026-07-14

## Real Status

Candidate status: `SEMANTIC_ROLE_SHADOW_EFFECTIVENESS_OBSERVATION_READY`.

Start commit: `e17c731e87222e9ae51cc84c5b9979f468508152`.

Branch: `feat/semantic-role-shadow-v01-isolated`.

This round stayed shadow-only. No paid model call, Runtime import, database write, DDL change, dependency upgrade, DOCX Native change, English Text-first change, or prompt-business-content change was made.

## Implemented

- Migrated deterministic Semantic Profile configuration under `config/semantic_profiles/`.
- Added `tools/semantic_profile_config.py`.
- Upgraded `tools/document_profile_resolver.py` from count-only sidecar to deterministic profile inference.
- Upgraded `tools/semantic_role_adapter.py` from identity observation to rule/config-driven shadow observations.
- Kept `adapter_mode = shadow_only` and `business_mutation_allowed = false`.
- Kept Shadow-on output ownership restricted to exactly seven sidecars under `outputs/semantic_role_shadow/<run_id>/`.
- Added `tools/run_semantic_shadow_real_rerun_validation.py` for experiments-off real-rerun validation.
- Extended `tests/test_semantic_role_shadow_isolation.py` for real role diffs and review-path rerun comparison.
- Narrowly updated `tools/semantic_shadow_compare.py` to normalize run-root prefixes in path-like image fields. This preserves asset suffixes, counts, node data, fragment pages/bboxes, review reasons, and repair pool content.

## Not Changed

- No split_v03 business algorithm changes.
- No Semantic Role result is written into `semantic_nodes.json`.
- No `assignments.json`, `audit_report.json`, `legacy_bridge_questions.json`, or `review_repair_pool.json` mutation.
- No release decision or Runtime payload mutation.
- No DOCX Native or English Text-first changes were included.
- No prompt bundle changes were included from the original large branch.
- No visual/model provider path was enabled.

## Actually Run

Safety / setup:

```text
git status --short --branch
git rev-parse HEAD
git stash push -u -m "protect-docx-english-dirty-before-semantic-shadow-effectiveness-20260715" -- <DOCX/English dirty paths>
```

Registry and tests:

```text
python tools\validate_pipeline_registry.py --json
python tests\test_pipeline_registry.py
python tests\test_semantic_role_shadow_isolation.py
```

Results:

- registry validator: `ok=true`, `pipeline_count=3`, `error_count=0`, `warning_count=0`
- registry tests: `Ran 3 tests OK`
- semantic shadow isolation/effectiveness tests: `Ran 8 tests OK`

Copied-artifact compare:

```text
python tools\semantic_shadow_compare.py --baseline-root outputs\pipeline_baseline_snapshot\control_plane_20260714_v02\deterministic_english_mock_p5_6 --current-root outputs\pipeline_baseline_snapshot\control_plane_20260714_v02\deterministic_english_mock_p5_6 --artifact docs/english/assignments.json --artifact docs/english/semantic_nodes.json --artifact docs/english/audit_report.json --artifact legacy_bridge_questions.json --artifact review_repair_pool.json --out outputs\semantic_role_shadow_effectiveness_validation_20260715\ready_path_copied_non_interference_report.json

python tools\semantic_shadow_compare.py --baseline-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01 --current-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01 --artifact docs/synthetic_review/assignments.json --artifact docs/synthetic_review/semantic_nodes.json --artifact docs/synthetic_review/audit_report.json --artifact legacy_bridge_questions.json --artifact review_repair_pool.json --out outputs\semantic_role_shadow_effectiveness_validation_20260715\review_path_copied_non_interference_report.json
```

Shadow-on sidecar example:

```text
python tools\run_semantic_role_adapter_shadow.py --stable-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01 --doc-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01\docs\synthetic_review --out-root outputs\semantic_role_shadow --run-id semantic_shadow_effectiveness_review_path_20260715 --enable-shadow
```

Experiments-off real rerun:

```text
$env:SEMANTIC_ROLE_ADAPTER_SHADOW='false'
$env:SEMANTIC_VISUAL_ASSIGNMENT_EXPERIMENT='false'
python tools\run_semantic_shadow_real_rerun_validation.py --out-root outputs\semantic_role_shadow_effectiveness_validation_20260715_rerun2
```

The first ready-path real-rerun attempt under `outputs/semantic_role_shadow_effectiveness_validation_20260715` failed only on legacy bridge image path prefixes. The business artifacts and core node/audit/repair data matched. The canonical path-like field normalization was then narrowed to run-root prefixes, and the second real rerun passed.

## Shadow Differences Observed

Sidecar output:

- `outputs/semantic_role_shadow/semantic_shadow_effectiveness_review_path_20260715/`

Observed metrics:

- `diff_count=3`
- `needs_role_review_count=2`
- `route_fallback_count=1`
- `shadow_roles=["exercise", "unknown"]`
- `model_invoked=false`
- `paid_model_invoked=false`

Observed examples:

- `synthetic_ready_q_001`: current `question`, shadow role `exercise`, route `question_splitter`, disposition `processable`.
- `synthetic_review_q_002`: current `question`, shadow role `exercise`, route candidate `question_splitter`, effective route fallback `review_only`, reason `page_bottom_may_continue`.
- `synthetic_orphan_003`: current `quarantined_orphan`, shadow role `unknown`, effective route `review_only`, reason `orphan_unresolved`.

## Ready-path Non-Interference

Copied-artifact report:

- `outputs/semantic_role_shadow_effectiveness_validation_20260715/ready_path_copied_non_interference_report.json`
- `equality=true`
- `compared_artifact_count=5`
- `ignored_field_count=0`

Real-rerun report:

- `outputs/semantic_role_shadow_effectiveness_validation_20260715_rerun2/ready_path_real_rerun_non_interference_report.json`
- `equality=true`
- `compared_artifact_count=5`

## Review-path Non-Interference

Copied-artifact report:

- `outputs/semantic_role_shadow_effectiveness_validation_20260715/review_path_copied_non_interference_report.json`
- `equality=true`
- `compared_artifact_count=5`
- `ignored_field_count=0`

Real-rerun report:

- `outputs/semantic_role_shadow_effectiveness_validation_20260715_rerun2/review_path_real_rerun_non_interference_report.json`
- `equality=true`
- `compared_artifact_count=5`

Review reasons and repair pool content remained unchanged:

- review reasons: `page_bottom_may_continue`, `orphan_unresolved`
- repair pool count: `2`

## Output Ownership

Shadow-on wrote exactly:

- `document_profile.json`
- `semantic_role_adapter_results.json`
- `semantic_role_adapter_diff_report.json`
- `semantic_role_adapter_metrics.json`
- `semantic_role_adapter_prompt_trace.json`
- `semantic_role_adapter_review_samples.html`
- `semantic_role_shadow_non_interference_report.json`

No extra sidecar file was written in the Shadow output directory.

## Risks / Remaining Gaps

- This is not effective routing. Shadow role/route/disposition candidates are observations only.
- The migrated logic is deterministic rule/config logic, not a paid-model or visual-provider path.
- Ready-path real rerun still depends on the local PDF path recorded by the existing v02 baseline.
- The original large branch contains unrelated DOCX/English/prompt/split changes and was not merged wholesale.
- Current project state remains validation/shadow observation, not production-ready.
