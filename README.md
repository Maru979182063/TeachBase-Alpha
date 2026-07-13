# TeachBase Alpha

This repository is the backend validation and tooling workspace for the TeachBase handout-processing project.

The current checked-in baseline focuses on one narrow promise:

- accept structured `LessonDraftBundle` input
- persist core runtime state through Postgres-backed stores
- validate release-gate behavior for import, review, publish, material build, and export flows
- keep teacher-handout visual tooling and question-asset pipelines in the same workspace for audit and refinement

It does **not** claim that OCR / PDF decomposition is production-complete. The upstream visual extraction and model-import layers are still being iterated separately from the backend validation baseline.

## What This Repo Contains

- `runtime/postgres/`: normalized runtime state repositories and scoped Postgres persistence logic
- `tools/`: backend runners, validation scripts, visual asset processing tools, mock runtime helpers, and audit utilities
- `tests/`: release-gate, migration, backup/restore, concurrency, security, projection, and three-track validation checks
- `config/`: runtime config, subject tracks, migrations, and visual prompt definitions
- `docs/`: planning notes, release reports, architecture writeups, and audit records
- `split_builder/`: earlier lecture / handout structure-splitting experiments kept as a separate sub-workstream
- `report_assets/`: checked-in image assets referenced by reports and BRD materials

## Current Project Boundary

The repository currently treats `LessonDraftBundle` as the validated upstream boundary.

That means the backend baseline covers:

- runtime write paths and state persistence
- release-gate and regression validation
- asset packaging and question-image attachment tooling
- backend observability and audit support
- canonical release decision gating before automatic Runtime import

That boundary does not cover:

- raw PDF ingestion accuracy
- OCR quality guarantees
- final multi-discipline production rollout approval

`complete` and `record=ok` are not release criteria. The automatic import boundary
is `allow_list_manifest.json`, produced together with
`canonical_release_decision.json` and `release_decision_summary.json`. See
`docs/release_decision_gate.md`.

## Main Entry Points

The most useful places to start are:

- `package.json`: top-level validation commands
- `docs/release_gate/2026-07-01_validation_baseline.md`: current backend validation-baseline summary
- `docs/production_readiness_final_report.md`: what is closed vs still out of scope
- `docs/release_decision_gate.md`: why release decision is the only automatic import gate
- `docs/artifact_lineage.md`: how source document, semantic node, assets, release decision, and Runtime import are traced
- `runtime/postgres/scoped_state_repository.mjs`: scoped-table-write baseline introduced in the latest backend round
- `tools/run_question_ingest_skill.py`: question-ingest and visual-asset flow entry for the current skill-side pipeline

## Quick Start

Install dependencies:

```bash
npm install
```

Recommended validation commands:

```bash
npm run test:release-gate
npm run test:production-readiness
npm run test:consistency
```

Additional checks available:

```bash
npm run test:three-track-baseline
npm run test:baseline-final-review
npm run test:backup-restore
npm run test:failure-injection
npm run test:load
npm run test:soak
npm run test:postgres-live
```

## Runtime Notes

- Official local backend entry: `http://127.0.0.1:8790`
- Compatibility port `8792` is deprecated and kept only as a forwarding shim during migration
- Some release-gate flows can fall back to embedded Postgres when `DATABASE_URL_TEST` is not preset

## Suggested Reading Order For RD

1. Read this file for repo scope and boundaries.
2. Open `package.json` to see the supported validation surface.
3. Read `docs/release_gate/2026-07-01_validation_baseline.md` for the current backend status.
4. Read `docs/production_readiness_final_report.md` and `docs/three_track_known_limitations.md` for known gaps.
5. Inspect `runtime/postgres/` and `tests/release_gate/` for the latest architecture and gate coverage.

## Repo Hygiene Notes

This branch intentionally keeps local scratch outputs, one-off backup folders, and temporary file copies out of the tracked code surface so the repository is easier to review.
