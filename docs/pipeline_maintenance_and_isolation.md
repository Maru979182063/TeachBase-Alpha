# Pipeline Maintenance And Isolation

## Real Status

This first-round control-plane branch only adds metadata, discovery artifacts, and registry validation.
It does not modify split_v03, Semantic Role, DOCX Native, English Text-first, model settings, prompts, dependencies, DDL, or Runtime behavior.

Current branch: `chore/pipeline-isolation-control-plane`

Stable source branch: `validation/backend-runtime-20260706`

Safety backup branch: `backup/pre-pipeline-isolation-20260714`

## Implemented In This Round

- Safety records under `outputs/pipeline_isolation_safety_20260714/`.
- Baseline candidate discovery under `outputs/pipeline_baseline_discovery_20260714/`.
- First deterministic baseline snapshot under `outputs/pipeline_baseline_snapshot/control_plane_20260714_v01/`.
- Pipeline registry skeleton in `config/pipeline_registry.yaml`.
- Feature flag skeleton in `config/pipeline_feature_flags.yaml`.
- Registry validator in `tools/validate_pipeline_registry.py`.
- Minimal run manifest helper in `tools/pipeline_run_context.py`.
- Registry tests in `tests/test_pipeline_registry.py`.

## Not Implemented

- Semantic Shadow sidecar isolation.
- DOCX Native branch isolation.
- English Text-first branch isolation.
- Baseline non-interference rerun.
- Output ownership enforcement.
- Confidence threshold or effective profile fixes.
- Any paid model rerun.

## Baseline Types

Deterministic baseline is the only first-round hard gate. It uses existing mock artifacts and is suitable for strict hash comparison within its limited scope.

Live model references are existing paid-model artifacts only. They are recorded for business reference and are not CI hash gates.

## Canonical Normalization

The first-round allow-list is limited to:

- absolute path prefix
- `created_at`
- `started_at`
- `finished_at`
- `run_id`
- temporary output directory
- explicit random `request_id`

Everything else is strict by default, including node counts, node types, fragment page and bbox, review status, audit reasons, bridge count, repair pool content, asset ownership, release decision, and Runtime import business fields.

## Registry Scope

This branch registers only pipelines that exist on `validation/backend-runtime-20260706`:

- `split_v03`
- `runtime_backend`

Semantic Role Adapter, DOCX Native Ingest, and English Text-first are intentionally not registered as implemented pipelines on this branch, because their code/config lives on the mixed experimental branch and must be migrated later through isolated branches.
