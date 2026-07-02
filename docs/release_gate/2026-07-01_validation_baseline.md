# 2026-07-01 Validation Baseline

## Current Branch

- branch: `codex/release-gate-gap-closure-20260701`
- branch role: `validation_baseline`
- this is not the production promotion branch

## Scope Closed In This Round

The backend now keeps the validated input boundary at `LessonDraftBundle`, while moving the core Postgres business writes off the full-runtime replay bridge.

Core paths now using scoped Postgres table writes:

- `importLessonDraftBundle`
- `approveReviewTask`
- `requestReviewChanges`
- `publishLesson`
- `createQuestionBankItem`
- `createMaterialBuild`
- `addMaterialBuildItems`
- `exportMaterialBuild`
- `registerExportRun`

Runtime health now reports:

- `releaseChannel = validation_baseline`
- `architectureMode = scoped_table_write`

## Remaining Explicit Non-Core Bridge Paths

The following paths are still intentionally outside this round's closure scope:

- `rerunLesson`
- `rerunComponent`
- `acceptComponentPatch`
- `rejectComponentPatch`
- `recoverJobs`
- `rebuildTaskProjections`
- bootstrap / debug helpers

## Release Gate Positioning

- `ARCH-001`: should remain green
- `POLICY-001`: should now pass naturally because the core write path is no longer the full state replay bridge
- `runtime_state_snapshot`: retained only for debug / migration support

## Latest Release Gate Run

- command: `node tests/release_gate/run_release_gate.mjs --full --report-json --report-md`
- run id: `release_gate_2026-07-01T08-12-53-055Z_dba9ef61`
- result: `GO WITH WARNINGS`
- pass/fail/skip: `62 / 0 / 0`
- warnings:
  - embedded Postgres fallback was used because `DATABASE_URL_TEST` was not preset
  - local `pg_dump` / `pg_restore` were used because Docker was not available
- report directory: `outputs/test_runs/release_gate/release_gate_2026-07-01T08-12-53-055Z_dba9ef61`

## Important Boundary

This document does not declare:

- OCR / PDF decomposition quality
- full-discipline capacity planning
- final production promotion approval

It documents the current backend validation baseline only.
