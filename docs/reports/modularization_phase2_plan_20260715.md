# Modularization Phase 2 Plan - 2026-07-15

This is a plan only. No large-scale module move was performed in Phase 1.

## Current Responsibilities

- `tools/run_question_ingest_skill.py`: runtime-facing ingest orchestration and output packaging.
- `tools/semantic_role_adapter.py`: deterministic semantic role shadow observations.
- `tools/run_semantic_role_effectiveness_eval.py`: evaluation case loading, prediction execution, candidate manifest handling, report writing.
- `tools/english_text_first_sidecar_graph_v01.py`: English sidecar graph construction and projection report.
- `tools/english_text_first_v05_pipeline.py`: English exact-source packet candidate generation and rough asset materialization.
- `tools/english_text_first_verifier_projector_v02.py`: verifier projection and asset coverage normalization.
- `tools/docx_native_formula_token_stream_v01.py`: DOCX paragraph stream extraction, OMML/MTEF tokenization, asset placeholders.
- `tools/docx_native_text_repair_model_node_v01.py`: model repair orchestration and validation.

## Hidden Dependencies

- Several tools still assume workspace-relative paths.
- Some config files are JSON stored with `.yaml` names.
- English v0.5 reads upstream VLM/unit/reference roots from config.
- DOCX text repair requires external API credentials for live model repair; Phase 1 tests use recorded/mock paths only.

## Proposed Boundaries

- `semantic_eval.contracts`: schemas, tier validation, real Gold checks.
- `semantic_eval.runner`: prediction execution and report writing.
- `semantic_eval.discovery`: explicit roots to candidate manifest.
- `english_text_first.fixtures`: portable fixture contracts.
- `english_text_first.pipeline`: exact-copy packet generation.
- `english_text_first.sidecar`: semantic graph and projection-only logic.
- `docx_native.formula`: OMML/MTEF providers and token stream.
- `docx_native.repair`: model IO, parser, validator, retry policy.

## Extraction Order

1. Freeze current integration gate as a Golden Master.
2. Extract pure schema/validation helpers first.
3. Extract discovery logic behind manifest-only tests.
4. Extract English fixture builders after keeping current portable tests green.
5. Extract DOCX provider/token helpers before touching model repair orchestration.
6. Move CLI wrappers last.

## Compatibility Shell Strategy

- Keep existing script entrypoints in `tools/`.
- Move internals behind imported modules only after tests pass.
- Preserve current output schemas and status labels.
- Do not change route enums, confidence thresholds, prompt policy, Runtime import behavior, DB behavior, or release gate semantics during Phase 2 extraction.

## Rollback Points

- After each extraction step, run `npm run test:repository-rescue-phase1`.
- If output schemas change, stop and add explicit compatibility adapters instead of continuing the move.
- If any test needs local `outputs/...` to pass, rollback the extraction.

## Must Not Touch Before Real Evidence Improves

- Semantic Role production readiness labels.
- Real Gold effectiveness thresholds.
- Runtime/DB write semantics.
- DOCX export main chain.
- Release gate promotion language.
