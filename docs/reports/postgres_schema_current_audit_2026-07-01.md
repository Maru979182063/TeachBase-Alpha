# Current Postgres Schema Audit

Updated: 2026-07-01

## Audit Scope

This audit reflects the current repository schema after actually applying the live migration chain into a temporary PostgreSQL database.

Audited sources:

- `config/migrations/20260623_runtime_backbone_validation.sql`
- `config/migrations/20260623_postgres_sole_source.sql`
- `config/migrations/20260624_three_track_validation_alignment.sql`
- `config/migrations/20260624_three_track_final_review_hardening.sql`
- `tools/runtime_backbone_postgres_store.mjs`
- `tests/migrations/postgres_migration_checks.mjs`
- `outputs/db/current_postgres_schema_snapshot.md`
- `outputs/db/current_postgres_schema_snapshot.json`

## Executive Summary

### 1. The repository already has a real Postgres schema

The current migration chain builds **43 public tables**.
This is not a paper draft only.
It is a runnable validation-stage schema.

### 2. The table count is high, but the count is being inflated by support layers

The current structure is not just:

- lesson
- question
- question bank
- material

It also already carries:

- runtime operations
- artifact lineage
- visual/component decomposition
- migration warnings
- three-track governance
- checkpoint inheritance and override

So the correct reading is not "43 core business tables".
The correct reading is "about 15 core business tables plus a large support envelope".

### 3. Current assessment

The schema should currently be described as:

- structurally real
- validation-baseline grade
- traceability-oriented
- heavier than a narrow MVP
- not yet a final simplified production model

## Category Breakdown

### Core lesson and question fact chain: 15 tables

- `lesson`
- `lesson_revision`
- `source_node`
- `source_node_revision`
- `task`
- `task_revision`
- `task_subject_ext`
- `task_projection`
- `question_bank_item`
- `question_bank_item_revision`
- `question_bank_source_link`
- `review_task`
- `publication`
- `material_build`
- `material_item`

This is the real business backbone.
If we only cared about the backend chain from `LessonDraftBundle -> review -> publish -> search -> question bank -> material`, this is the part that matters most.

### Checkpoint and track governance: 6 tables

- `checkpoint_catalog`
- `checkpoint_catalog_version`
- `checkpoint_node`
- `source_node_checkpoint_link`
- `task_checkpoint_override`
- `subject_track`

This layer exists because the repository is no longer pretending that checkpoint mapping and three-track isolation can stay implicit in code.

### Document and visual/component support: 10 tables

- `document_source`
- `document`
- `document_group`
- `document_group_member`
- `document_relation`
- `page_asset`
- `component`
- `component_revision`
- `component_link`
- `component_patch_candidate`

This layer is a major reason the table count looks large.
It is carrying visual split, page-level assets, component rerun, and component-to-task linkage.

### Runtime operations and lineage: 9 tables

- `run`
- `job`
- `job_attempt`
- `job_dependency`
- `artifact`
- `artifact_dependency`
- `outbox_event`
- `lesson_import`
- `quality_evaluation`

This is not required for the smallest possible CRUD backend.
It exists because the current branch wants replayability, export registration, rerun traceability, and future agent/job orchestration.

### Snapshot and migration support: 3 tables

- `runtime_metadata`
- `runtime_state_snapshot`
- `runtime_migration_warning`

These tables are important for interpretation.
They show that the repository is not yet a "pure final-form normalized business schema with no transitional scaffolding".

## What Is Already Good

### 1. The business fact chain is no longer imaginary

The repository has separate tables for:

- lesson
- lesson revision
- source node
- task
- task revision
- question bank revision
- material build
- publication

That means the backend is already beyond a file-only mock phase.

### 2. Three-track governance is already in the database

The schema now contains:

- `subject`
- `stage`
- `track_code`
- `difficulty_level`
- `difficulty_scheme`
- `difficulty_source`
- `difficulty_confidence`

across the relevant search, question bank, and material tables.

This is the right direction for:

- `math_junior`
- `math_senior`
- `english_senior`

### 3. `task_projection` is clearly separated from fact tables

This is a healthy sign.
The schema does not pretend that the search projection is the only truth source.

### 4. Checkpoint inheritance has explicit carriers

The presence of:

- `source_node_checkpoint_link`
- `task_checkpoint_override`

means the model can express:

- node default checkpoint ownership
- exceptional per-task add/remove/replace behavior

without hiding that logic inside blobs only.

## What Makes It Feel Heavy

### 1. The schema was expanded for validation completeness, not only for MVP compactness

The table count is high mainly because the branch has already unfolded:

- visual decomposition
- component rerun
- artifact lineage
- runtime jobs
- migration warning capture

If the near-term goal were only "manage lessons, questions, question bank, and materials", this shape would feel oversized.

### 2. Support tables are arriving before the architecture is fully frozen

The repository already has:

- `run`
- `job`
- `artifact`
- `outbox_event`
- `quality_evaluation`

which is a reasonable long-term direction, but it increases cognitive load early.

### 3. The snapshot/debug layer still exists

`runtime_state_snapshot` is still part of the actual schema.

That does not mean the business read path is still fake.
But it does mean the architecture is still transitional rather than fully simplified and finalized.

## Main Audit Risks

### Risk 1. The schema is understandable for the current branch, but not lightweight

The current shape is acceptable for a traceability-heavy validation backend.
It is not a lean "few tables and move fast" MVP schema anymore.

Impact:

- higher onboarding cost
- more migration surface
- more test surface
- more places where new features can accidentally couple into the wrong layer

### Risk 2. Future subject expansion will be more expensive than the current three-track scope

`subject_track` plus related composite constraints are correct for current isolation.
But they also mean every future new subject or new stage will require careful coordinated migration work.

Impact:

- schema changes will need more planning
- validation suites will grow quickly
- expansion speed may drop if more subjects are added casually

### Risk 3. There is a mismatch between "validation-ready" modeling and "MVP readability"

The schema is already optimized for:

- auditability
- replayability
- rerun traceability
- export registration

more than for "someone opens the DB and immediately understands everything".

Impact:

- non-backend reviewers may overestimate complexity
- teams may hesitate to use the DB directly

### Risk 4. ID discipline is application-driven

A large portion of the schema uses text identifiers rather than database-generated UUID keys.
That is not inherently wrong, but it pushes naming and referential discipline into application code.

Impact:

- easier diffability and deterministic IDs
- but also more pressure on code-side consistency

## Current Judgment

### Is 43 tables "too many"?

For a narrow teaching-content MVP: yes, it is heavy.

For a validation-stage backend that already includes:

- lessons
- revisions
- projections
- question bank
- material build
- visual components
- rerun patches
- artifact lineage
- runtime job records
- migration warning capture

43 tables is not absurd.

So the honest answer is:

- not outrageously bloated
- but definitely broader than a smallest practical first release

## Recommendations

### Recommendation 1. Treat the current schema as a validation-grade full envelope, not as the final simplified production contract

This avoids the wrong expectation that every current table must remain exactly as-is forever.

### Recommendation 2. Keep the core fact chain stable first

The tables that should be treated as hardest to destabilize are:

- `lesson`
- `lesson_revision`
- `source_node`
- `source_node_revision`
- `task`
- `task_revision`
- `task_subject_ext`
- `task_projection`
- `question_bank_item`
- `question_bank_item_revision`
- `material_build`
- `material_item`
- `review_task`
- `publication`
- `subject_track`

### Recommendation 3. Treat the support envelope as second-priority for simplification later

If the team wants to reduce mental load later, the first simplification candidates should be reviewed in these groups:

- runtime ops and orchestration tables
- visual/component support tables
- snapshot/debug support tables

This does **not** mean deleting them now.
It means these are the areas most likely to be consolidated in a later production-hardening round.

### Recommendation 4. Do not judge the architecture by the raw table count alone

A better decision rule is:

- how many tables are on the critical write path
- how many tables are rebuildable projections or support records
- how many tables are optional support for audit, rerun, and export

## Final Conclusion

The current repository already has a real and fairly expanded Postgres schema.

The important conclusion is not simply "43 tables".
The more useful conclusion is:

- about 15 tables represent the core lesson/question/material business chain
- the rest mostly come from support layers the branch has already chosen to model explicitly

So the schema is currently:

- real
- reasonably structured
- heavier than MVP
- acceptable for the present validation baseline
- not yet the final minimized production shape

## Related Files

- Full live schema snapshot:
  - `outputs/db/current_postgres_schema_snapshot.md`
  - `outputs/db/current_postgres_schema_snapshot.json`
- Historical draft for comparison:
  - `docs/db/后端数据库草案_v0.1.sql`
