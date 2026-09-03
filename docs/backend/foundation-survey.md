# Java Backend Foundation Survey

## Scope

This survey establishes the implementation baseline for the Java-controlled TeachBase workbench backend. It measures the committed runtime schema and the current high-fidelity prototype without modifying either dirty source workspace.

Baseline:

- Branch: `backend/java-modulith-foundation-survey`
- SHA: `8ca1703700c22d6e13ee3b26e2b902c8d9c5a309`
- Parent integration baseline: `b96a400daadd11fd496ecc47152861f3d5496dae`
- Distance from integration baseline: 51 commits

The uncommitted Java worker under the source worktree is evidence only. It is not a backend foundation dependency.

## Build Environment

- Java and `javac`: Temurin 21.0.12 LTS
- Maven: 3.9.16
- Maven effective Java: 17.0.20
- Node.js: 24.18.0
- PostgreSQL client and embedded test engine: 18.4
- Docker: not installed
- Gradle: not installed

The machine-level Maven selection was Java 17 during the survey. Phase 1 resolves this with a cross-platform repository runner that derives `JAVA_HOME` from the active Java 21 compiler before invoking Maven. Because Docker is absent, CI may use a PostgreSQL service, while local tests retain the isolated embedded PostgreSQL path.

## Measured Facts

### Existing PostgreSQL runtime

- PostgreSQL 18.4 migration and runtime checks pass in a disposable database.
- The `public` schema contains 43 tables, 430 columns, 197 constraints, 22 foreign keys, 82 indexes and 20 JSON/JSONB columns.
- Deterministic startup fixtures populate 31 tables.
- Twelve tables remain empty in the exercised runtime: `component_patch_candidate`, `document_relation`, `job_dependency`, `material_build`, `material_item`, `outbox_event`, `quality_evaluation`, `question_bank_item`, `question_bank_item_revision`, `question_bank_source_link`, `runtime_migration_warning`, and `runtime_state_snapshot`.
- The empty question-bank and material tables show that their DDL is a validation-stage design, not proven workbench storage.
- Runtime jobs already model idempotency, retries, leases, heartbeats, timeouts and structured attempt errors. These concepts should be retained, but the old unconstrained IDs should not be copied directly.
- The historical file named `postgres_schema_current_audit_2026-07-01.md` does not contain a schema audit. Its content is a ten-question gold review. Historical report filenames are therefore not authoritative evidence.

### Current prototype

- All 51 prototype contract tests pass.
- `alpha-build-fixtures-v2` contains 85 effective questions, including parent-child questions, structured content, display blocks, source provenance, assets and approved revision numbers.
- Question collection snapshots freeze full question content and selected child membership.
- The editor persists Tiptap JSON with the `master-overrides-v1` model.
- Question and knowledge references pin both stable identity and revision identity.
- Preview confirmation produces immutable handout snapshots before export.
- Export retries create new jobs and retain the failed job lineage.
- The fixture payload contains 77 machine-specific Windows absolute path values. They must be converted to `file_asset` IDs and portable storage keys before backend import.

## Architecture Decision

The 43-table `public` schema is a pipeline/runtime validation model. It is not reused as the Java workbench write model because:

1. Most semantic identifier columns have no database foreign key.
2. Whole lesson bundles and subject extensions still carry significant JSON projections.
3. The question-bank and material authoring path is not exercised by current fixtures.
4. The prototype requires versioned knowledge, question collections, immutable collection snapshots, editor confirmations and export lineage that are not represented cleanly.
5. Allowing Java and the Node runtime to write the same tables would create an unsafe dual-write system.

The Java application will own a new `teachbase_app` schema. The old `public` schema is read-only during an idempotent import, then retained as rollback and audit evidence until migration acceptance.

## Candidate Target Model

The measured model contains 42 candidate tables. This is a domain inventory, not permission to create all tables in one migration.

| Module | Tables | Count |
|---|---|---:|
| Identity | `workspace`, `app_user`, `workspace_member` | 3 |
| Files | `file_asset`, `file_version` | 2 |
| Source | `source_document`, `source_region`, `source_question`, `source_question_revision` | 4 |
| Questions | `question`, `question_revision`, `question_relation`, `question_file_reference`, `question_knowledge_link` | 5 |
| Knowledge | `taxonomy_node`, `knowledge_item`, `knowledge_revision`, `knowledge_relation`, `question_taxonomy_link` | 5 |
| Review | `review_case`, `review_draft`, `review_decision` | 3 |
| Collections | `question_collection`, `question_collection_item`, `question_collection_snapshot` | 3 |
| Editor | `editor_document`, `editor_draft`, `editor_revision`, `editor_variant`, `editor_question_reference`, `editor_knowledge_reference`, `editor_file_reference`, `editor_preview_confirmation`, `editor_snapshot` | 9 |
| Export | `export_request`, `export_attempt`, `export_file` | 3 |
| Jobs | `processing_job`, `job_attempt` | 2 |
| Audit and migration | `audit_event`, `legacy_import_batch`, `legacy_id_map` | 3 |

An outbox table is deliberately absent. It should be added only when an actual asynchronous consumer and delivery guarantee exist.

## Construction Phases

### Phase 1: foundation and files

Create the Java 21 Spring Boot modular monolith, Flyway ownership, jOOQ generation, database roles and the 10 phase-one tables. Prove file upload metadata, portable storage keys, checksums, users, audit events and idempotent legacy batches.

Exit gate: one real local source file is registered without storing its absolute path, and a repeated import does not duplicate it.

Status on 2026-08-31: implemented. The gate additionally proves eight-request concurrent idempotency, one audit event per winning registration, absolute-path rejection and disposable PostgreSQL cleanup. See `docs/backend/java-foundation-phase1.md`.

### Phase 2: source to reviewed question

Create source evidence, canonical questions, knowledge and review tables. Import representative math and English records and preserve source file, page, block, parent-child relation and revision history.

Exit gate: modifying an approved question creates a new unreviewed revision while the approved revision remains immutable.

Status on 2026-08-31: the ingestion boundary is implemented in V004. Stable question identity, immutable revisions, approved/current separation, four-source-system batch ingestion, Chinese/Latin indexes, review-state search and keyset pagination are live-gated. Dedicated knowledge and review-decision aggregates remain future work; V004 records the review state required for initial ingestion without pretending that the review UI exists.

### Phase 3: collection and editor

Create question collections and snapshots, then implement Tiptap drafts, optimistic locking, master plus three variants, typed references, preview confirmation and immutable editor snapshots.

Exit gate: changing a question or draft cannot mutate an existing collection or handout snapshot.

Status on 2026-08-31: question collections and typed question references are implemented in V004. Draft revisions, three prototype-compatible variants, optimistic concurrency, autosave/manual/restore checkpoints, immutable collection and editor snapshots, batch placement and hydrated teacher/student question content are live-gated. Knowledge/file reference projections remain pending their source domains.

### Phase 4: export and jobs

Create immutable export requests, generic processing jobs, attempts, heartbeat, lease, retry lineage and export files. Four-chain execution remains outside this phase; only the stable port is provided.

Exit gate: one request creates one job per snapshot/audience/format combination, and retry preserves the failed job.

Status on 2026-08-31: implemented for document export in V002/V003. Snapshot-bound idempotent admission, two-instance PostgreSQL claiming, attempts, heartbeat, leases, retry/final failure, stale-lease recovery, versioned Pandoc AST, native DOCX formulas, PDF generation and file-version registration are live-gated. The generic four-chain processing-job domain remains separate and unimplemented here.

### Question basket and Redis boundary

The implemented question basket belongs in PostgreSQL as `question_collection`, `question_collection_item`, `question_collection_checkpoint`, `question_collection_snapshot` and `question_collection_snapshot_item`. It is a durable, cross-device, auditable business asset. Redis may later accelerate temporary selection sessions, distributed coordination and hot reads, but it is not the basket's source of truth and is not required for the current modular-monolith foundation.

## Blocking Decisions Before Schema V1

The following items must be resolved during the first implementation slice, not guessed in DDL:

1. Whether one user can belong to multiple workspaces and which actor source provides the initial users.
2. Storage backend for development and production. The contract must support local filesystem and object storage through the same storage key.
3. Exact promotion rule from `source_question_revision` to `question_revision` after human review.
4. Whether the three editor variants store complete JSON documents or patches. The prototype currently stores projected or overridden complete documents; the backend should first preserve this behavior and optimize later.
5. Which historical knowledge checkpoint records are content-bearing knowledge revisions and which are taxonomy-only labels.

## Reproducible Evidence

- `npm run audit:java-foundation-db`
- Set `TEACHBASE_PROTOTYPE_ROOT` to the local prototype checkout, then run `npm run audit:java-foundation-prototype`.
- `npm run test:java-foundation-survey`
- `npm run test:java-foundation-phase1`
- `npm run test:editor-backend`
- `npm run test:document-renderer`
- `npm run test:java-backend-foundation`
- Run the prototype's Node test suite separately from its checkout.

Machine-readable evidence:

- `docs/reports/java_foundation_database_inventory_20260831.json`
- `docs/reports/java_foundation_prototype_inventory_20260831.json`
- `docs/reports/java_foundation_legacy_mapping_20260831.json`
- `docs/reports/java_foundation_environment_20260831.json`
- `docs/reports/java_foundation_phase1_live_gate_20260831.json`
- `docs/reports/editor_backend_contract_audit_20260831.json`
- `docs/reports/editor_backend_live_gate_20260831.json`
- `docs/reports/document_renderer_live_gate_20260831.json`

No machine-specific absolute path is part of the report input contract.
