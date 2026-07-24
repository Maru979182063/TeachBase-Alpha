# Semantic Role Shadow Isolation Audit 2026-07-14

## Real status

Status candidate: `SEMANTIC_ROLE_SHADOW_ISOLATION_READY`.

Current branch: `feat/semantic-role-shadow-v01-isolated`.

Base commit requested by user: `878ad4a9`.

No paid model call was made in this round.

## Implemented

- Added deterministic review-path baseline at `outputs/pipeline_baseline_snapshot/semantic_shadow_review_path_20260714_v01`.
- Kept existing ready-path v02 baseline at `outputs/pipeline_baseline_snapshot/control_plane_20260714_v02`.
- Added isolated sidecar entrypoint: `tools/run_semantic_role_adapter_shadow.py`.
- Added deterministic sidecar resolver/adapter helpers:
  - `tools/document_profile_resolver.py`
  - `tools/semantic_role_adapter.py`
- Added canonical compare helper: `tools/semantic_shadow_compare.py`.
- Added registry entry `semantic_role_shadow` with:
  - `status: shadow`
  - `owned_output_roots: ["outputs/semantic_role_shadow"]`
  - `database_write_policy.policy: forbidden`
  - `runtime_import_policy.policy: forbidden`
  - `release_gate_policy: no_effect`
  - feature flag `semantic_role_adapter_shadow`, default false.

## Not implemented

- No DOCX Native change.
- No English Text-first change.
- No prompt business-content change.
- No confidence threshold change.
- No effective profile merge change.
- No DDL or dependency change.
- No Golden Dataset expansion.
- No Semantic Shadow writes to Runtime or database.

## Baselines

Ready-path deterministic baseline:

- Path: `outputs/pipeline_baseline_snapshot/control_plane_20260714_v02`
- Core path: `outputs/pipeline_baseline_snapshot/control_plane_20260714_v02/deterministic_english_mock_p5_6`
- Metrics: `nodes=8`, `ready=8`, `needs_review=0`, `quarantined=0`, `review_repair_pool_count=0`
- Provider: `mock`
- Paid model: `false`

Review-path deterministic baseline:

- Path: `outputs/pipeline_baseline_snapshot/semantic_shadow_review_path_20260714_v01`
- Input fixture: `outputs/pipeline_baseline_snapshot/semantic_shadow_review_path_20260714_v01/input/synthetic_review_path_fixture.json`
- Metrics: `nodes=3`, `ready=1`, `needs_review=1`, `quarantined=1`, `review_repair_pool_count=2`
- Review reasons: `page_bottom_may_continue`, `orphan_unresolved`
- Provider: `deterministic_fixture`
- Paid model: `false`

## Actually run

Registry validator:

```text
python tools\validate_pipeline_registry.py --json
ok=true pipeline_count=3 error_count=0 warning_count=0
```

Registry tests:

```text
python tests\test_pipeline_registry.py
Ran 3 tests OK
```

Semantic Shadow contract tests:

```text
python tests\test_semantic_role_shadow_isolation.py
Ran 6 tests OK
```

Ready-path experiments-off compare:

```text
python tools\run_semantic_role_adapter_shadow.py --stable-root outputs\pipeline_baseline_snapshot\control_plane_20260714_v02\deterministic_english_mock_p5_6 --doc-root outputs\pipeline_baseline_snapshot\control_plane_20260714_v02\deterministic_english_mock_p5_6\docs\english
equality=true compared_artifact_count=5 ignored_field_count=0
```

Review-path experiments-off compare:

```text
python tools\run_semantic_role_adapter_shadow.py --stable-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01 --doc-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01\docs\synthetic_review
equality=true compared_artifact_count=5 ignored_field_count=0
```

Shadow-on sidecar-only smoke:

```text
python tools\run_semantic_role_adapter_shadow.py --stable-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01 --doc-root outputs\pipeline_baseline_snapshot\semantic_shadow_review_path_20260714_v01\docs\synthetic_review --out-root outputs\semantic_role_shadow --run-id semantic_shadow_review_path_smoke_20260714 --enable-shadow
equality=true compared_artifact_count=5 ignored_field_count=0
```

## Artifacts

Ready-path off report:

- `outputs/semantic_role_shadow_validation_20260714/ready_path_experiments_off_non_interference_report.json`
- `baseline_hash=ea5ab7d60a99e4b01dff872d652c906a7a5614a34db400c954618acc8b2bd9b9`
- `current_hash=ea5ab7d60a99e4b01dff872d652c906a7a5614a34db400c954618acc8b2bd9b9`
- `equality=true`

Review-path off report:

- `outputs/semantic_role_shadow_validation_20260714/review_path_experiments_off_non_interference_report.json`
- `baseline_hash=f245deeab170f06ba24575d4ae40d99138be48ef01041223b11db5beb4f8e7c0`
- `current_hash=f245deeab170f06ba24575d4ae40d99138be48ef01041223b11db5beb4f8e7c0`
- `equality=true`

Shadow sidecar output:

- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/document_profile.json`
- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/semantic_role_adapter_results.json`
- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/semantic_role_adapter_diff_report.json`
- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/semantic_role_adapter_metrics.json`
- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/semantic_role_adapter_prompt_trace.json`
- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/semantic_role_adapter_review_samples.html`
- `outputs/semantic_role_shadow/semantic_shadow_review_path_smoke_20260714/semantic_role_shadow_non_interference_report.json`

Shadow sidecar metrics:

- `model_invoked=false`
- `paid_model_invoked=false`
- `semantic_node_count=3`
- `review_repair_pool_count=2`
- `diff_count=0`

## Risks

- Ready-path v02 still references the prior mock PDF command and external local input path in its historical manifest. It is retained as requested, but the new review-path baseline is fully synthetic and repo-local.
- The Semantic Role Adapter implementation in this round is intentionally sidecar-only and deterministic. It does not implement production role-improvement behavior.
