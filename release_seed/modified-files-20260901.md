# Modified files — 2026-09-01

All retained implementation from this task is under `release_seed/`.

## Added

- `release_seed/README.md`
- `release_seed/validator.py`
- `release_seed/merge_enrichments_v1.py`
- `release_seed/schemas/release-seed-v1.schema.json`
- `release_seed/docs/release-seed-v1.md`
- `release_seed/docs/test-design.md`
- `release_seed/reports/input-inventory-20260901.json`
- `release_seed/reports/readiness-20260901.json`
- `release_seed/reports/offline-tests-20260901.json`
- `release_seed/tests/test_validator.py`
- `release_seed/tests/test_merge_enrichments.py`
- `release_seed/fixtures/README.md`
- `release_seed/fixtures/build_fixtures.py`
- `release_seed/fixtures/minimal_valid/manifest.json`
- `release_seed/fixtures/minimal_valid/questions.jsonl`
- `release_seed/fixtures/minimal_valid/question_relations.jsonl`
- `release_seed/fixtures/minimal_valid/source_documents.jsonl`
- `release_seed/fixtures/minimal_valid/source_regions.jsonl`
- `release_seed/fixtures/minimal_valid/rejected_questions.jsonl`
- `release_seed/fixtures/minimal_valid/validation_report.json`
- `release_seed/fixtures/minimal_valid/review_report.json`
- `release_seed/fixtures/minimal_valid/assets/manual-source.json`
- `release_seed/modified-files-20260901.md`

## Temporarily touched, then restored

The following existing files were temporarily edited by this task before the
scope was narrowed. The Release Seed additions were removed; no retained
Release Seed code remains in them:

- `package.json`
- `backend/teachbase-server/README.md`
- `backend/teachbase-server/src/main/java/com/teachbase/server/TeachBaseServerApplication.java`
- `backend/teachbase-server/src/main/java/com/teachbase/server/question/internal/QuestionService.java`

No commit, reset, checkout, clean, branch creation or worktree creation was
performed. No migration or shared question/Review/hash/taxonomy field was
modified as part of the retained implementation.

## Created during the superseded approach, then removed

These paths were created by this task before the scope update and are absent at
handoff:

- `backend/teachbase-server/src/main/java/com/teachbase/server/question/api/QuestionBatchImporter.java`
- `backend/teachbase-server/src/main/java/com/teachbase/server/seed/` (15 Java source files and `package-info.java`)
- `backend/teachbase-server/src/main/resources/db/migration/V005__release_seed_ingestion_batches.sql`
- `backend/teachbase-server/src/main/resources/seed/v1/release-seed-v1.schema.json`
- `backend/teachbase-server/src/test/java/com/teachbase/server/seed/SeedPackageValidatorTest.java`
- `tools/run_release_seed_live_gate.mjs`
- `tools/release_seed/`
- `tests/test_release_seed_merge.py`
- `docs/backend/release-seed-v1.md`
- `docs/reports/release_seed_data_discovery_20260901.json`
- `docs/reports/release_seed_pipeline_readiness_20260901.json`
- `docs/reports/release_seed_live_gate_20260901.json`

The similarly numbered
`V005__question_governance_foundation.sql` belongs to shared concurrent work and
was not edited or removed by this task.
