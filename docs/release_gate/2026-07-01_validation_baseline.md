# 2026-07-01 Validation Baseline

## Current Position

- branch: `validation/backend-runtime-20260706`
- branch role: `validation_baseline`
- this branch is still not a production promotion branch

## Current Backend Boundary

- official runtime entry: `8790`
- deprecated compat entry: `8792`
- authoritative ingest boundary: `LessonDraftBundle`
- formal English ingest adapter:
  `tools/runtime_manifest_to_lesson_bundle_adapter.mjs`
- visual ingest boundary:
  `source_refs_json.question_visual_structure`

## Current Truth Source Position

- core Postgres business writes are on normalized tables
- `runtime_state_snapshot` remains present only as debug / migration support
- validation baseline must still report `NOT_READY` while `releaseChannel = validation_baseline`

## Latest Real Validation Artifacts

- staging validation:
  `outputs/staging_validation/staging_validation_2026-07-06T06-44-50-675Z_f551bfff/staging_report.json`
- release gate:
  `outputs/test_runs/release_gate/release_gate_2026-07-06T06-45-41-072Z_facea6b2/report.json`
- production readiness:
  `outputs/production_readiness/production_readiness_2026-07-06T06-51-32-596Z_c7c440ff/production_readiness_report.json`

## Latest Release Gate

- command:
  `node tests/release_gate/run_release_gate.mjs --fast --skip-performance --report-json --report-md`
- run id:
  `release_gate_2026-07-06T06-45-41-072Z_facea6b2`
- result:
  - total: `57`
  - passed: `57`
  - failed: `0`
  - verdict: `GO WITH WARNINGS`

Warnings are still environment-level only:

- `DATABASE_URL_TEST` absent; embedded Postgres fallback was used
- Docker not available; backup / restore used local `pg_dump` / `pg_restore`

## Latest Production Readiness

- command:
  `npm run test:production-readiness`
- run id:
  `production_readiness_2026-07-06T06-51-32-596Z_c7c440ff`
- result:
  - total: `41`
  - passed: `41`
  - failed: `0`
  - finalStatus: `NOT_READY`

This is expected because the branch still reports `releaseChannel = validation_baseline`.

## Important Boundary

This document does not claim:

- production promotion approval
- raw OCR / PDF decomposition as authoritative backend facts
- shared team DB validation

It documents the current validated backend baseline only.
