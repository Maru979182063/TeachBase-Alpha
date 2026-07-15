# TeachBase Python Architecture v0.1

Status: Phase 2A vertical slice only.

## Real Scope

Implemented in this round:

- `src/teachbase/core`: minimal run context, stage result, and typed error contracts.
- `src/teachbase/infrastructure`: JSON/text artifact writes and SHA-256 helpers.
- `src/teachbase/semantic_role`: Semantic Role Eval contracts, metrics, candidate manifest, review pack, evaluator, and CLI facade.

Not implemented in this round:

- English Text-first package migration.
- DOCX Native package migration.
- `run_question_ingest_skill.py` migration.
- Runtime/Postgres migration.
- New model strategy, prompt content, role enum, route enum, or threshold changes.

## Dependency Direction

Legacy CLI wrapper:

`tools/run_semantic_role_effectiveness_eval.py`

calls:

`teachbase.semantic_role.cli`

which calls:

`teachbase.semantic_role.evaluator`

which calls:

`teachbase.semantic_role.metrics`, `candidate_manifest`, `review_pack`, and `teachbase.infrastructure`.

The new package does not import `tools`, Runtime, DB code, or environment variables. The legacy deterministic predictor remains in `tools/semantic_role_eval_legacy_predictor.py` so Phase 2A does not accidentally migrate the broader Semantic Role Shadow pipeline.

## Compatibility

The old CLI path is retained:

`python tools/run_semantic_role_effectiveness_eval.py`

The wrapper preserves CLI argument names and defaults. Direct script execution and package import execution are both supported without adding a new `sys.path` hack.
