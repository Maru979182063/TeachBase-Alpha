# Postgres Sole Source Migration Plan

## Current Audit

- `tools/runtime_backbone_postgres_store.mjs` is still snapshot-primary.
- `init()` currently loads `runtime_state_snapshot`, normalizes the JSON state, and rewrites every mirror table on startup.
- All major business writes still flow through `writeState()`:
  - `importLessonDraftBundle`
  - `rerunLesson`
  - `publishLesson`
  - `approveReviewTask`
  - `requestReviewChanges`
  - `createQuestionBankItem`
  - `createMaterialBuild`
  - `addMaterialBuildItems`
  - `exportMaterialBuild`
  - `rerunComponent`
  - `acceptComponentPatch`
  - `rejectComponentPatch`
  - `registerExportRun`
  - `recoverJobs`
- Several read APIs still derive their answers from snapshot-backed `readState()` rather than from normalized tables.
- `getConsistencyReport()` still treats snapshot JSON as the reference baseline and only checks whether mirror tables match it.

## Gaps Blocking ARCH-001

- The current Postgres schema only stores part of the runtime state.
- Missing persisted collections include:
  - `documentSources`
  - `documentGroups`
  - `documentGroupMembers`
  - `documentRelations`
  - `jobDependencies`
  - `outboxEvents`
  - `imports`
  - `componentLinks`
  - `sourceNodes`
  - `sourceNodeRevisions`
  - `tasks`
  - `taskRevisions`
  - `checkpointCatalogs`
  - `checkpointCatalogVersions`
  - `checkpointNodes`
  - `sourceNodeCheckpointLinks`
  - `taskCheckpointOverrides`
  - `taskSubjectExt`
  - `qualityEvaluations`
- Because these facts are missing from tables, Postgres cannot yet rebuild the full business view without consulting snapshot JSON.

## Validation-Stage Target

- Postgres business reads use normalized tables as the only source of truth.
- Postgres business writes no longer use `runtime_state_snapshot` as the read-modify-write baseline.
- `runtime_state_snapshot` remains available only for:
  - debug export
  - migration verification
  - manual disaster analysis
- Snapshot generation becomes best-effort and must never break the main transaction.

## Implementation Strategy

### Batch 1: Full Table Coverage

- Add a follow-up migration that persists the remaining runtime collections required by current store logic.
- Keep existing columnar tables for lesson, publication, question bank, material, component, run, job, and artifact facts.
- Use compact row tables plus JSON columns only where the current validation scope does not justify a full ERD expansion yet.

### Batch 2: Repository Split

- Introduce `runtime/postgres/` repositories so the main store stops owning all SQL details.
- Planned modules:
  - `postgres_client.mjs`
  - `state_table_configs.mjs`
  - `state_repository.mjs`
  - `snapshot_repository.mjs`
- Validation-stage scope keeps one generalized state repository that can:
  - hydrate runtime state from normalized tables
  - diff pre/post mutation collections
  - apply row-level upserts and deletes instead of full mirror rebuilds

### Batch 3: Store Cutover

- Postgres reads hydrate from tables, then reuse existing pure business selectors from `runtime_backbone_store.mjs`.
- Postgres writes:
  - load current table-backed state
  - run existing pure mutation logic
  - persist only changed rows by primary key
  - optionally refresh snapshot after commit on a best-effort path

### Batch 4: Test Gate Tightening

- Replace the string-only `ARCH-001` check with behavior tests that prove:
  - Postgres starts without snapshot rows
  - corrupt snapshot rows do not affect business reads
  - writes survive restart from normalized tables
  - snapshot failure does not roll back business success
  - no full-table mirror rebuild happens during normal writes

## Remaining Validation Risks

- The validation-stage repository still reconstructs in-memory state for pure domain logic; this is acceptable for the current cutover, but not the final scale design.
- The long-term target should still move hot paths such as lesson detail, review transitions, publication, lineage, and recovery to domain-specific SQL repositories.
- After `ARCH-001` is closed, the next architecture pass should reduce whole-state hydration on write-heavy paths.
