# Java Foundation Phase 1

## Purpose

Phase 1 turns the backend survey into an executable foundation. It establishes Java ownership, database ownership and a narrow file-registration contract without migrating the four production question-processing chains or the high-fidelity prototype.

The useful mental model is a new load-bearing service entrance beside an occupied building. The old `public` schema and Python pipelines remain in place and untouched. New work enters through the Java service and is recorded in `teachbase_app`; later phases can move one bounded domain at a time instead of rewiring the occupied building all at once.

## Technology Baseline

- Java 21
- Spring Boot 3.5.16
- Spring Modulith 1.4.13
- jOOQ 3.19.35, generated from the Flyway DDL
- Flyway with PostgreSQL
- Maven 3.9+
- PostgreSQL 16 or newer; the local gate exercises PostgreSQL 18

`tools/run_java_foundation_maven.mjs` resolves the active Java 21 compiler and supplies its home to Maven. This removes dependence on the machine's stale global `JAVA_HOME` and works on Windows and Linux.

## Module Boundaries

The application is a modular monolith with five initial modules:

| Module | Responsibility | Current dependency surface |
|---|---|---|
| `identity` | Workspace existence and membership foundation | Exposes `identity::api` |
| `fileasset` | Portable file metadata and idempotent registration | Uses `identity::api`, `audit::api` |
| `audit` | Append-only business event recording | Exposes `audit::api` |
| `source` | Reserved boundary for source documents and regions | No implementation dependency yet |
| `migration` | Reserved boundary for controlled legacy import | No implementation dependency yet |

Spring Modulith verifies these dependencies during every Maven test run. Controllers do not call jOOQ directly; transaction ownership lives in the application service and persistence stays behind module interfaces.

## Database Ownership

Flyway migration `V001__foundation.sql` creates exactly ten domain tables in `teachbase_app`:

| Area | Tables |
|---|---|
| Identity | `workspace`, `app_user`, `workspace_member` |
| Files | `file_asset`, `file_version` |
| Source evidence | `source_document`, `source_region` |
| Audit | `audit_event` |
| Controlled migration | `legacy_import_batch`, `legacy_id_map` |

The historical `public` schema is not modified and is not a Java write target. A later importer may read it and write idempotently into `teachbase_app`; dual writes are prohibited.

Production database users and grants belong to deployment provisioning, not application Flyway migrations. Flyway owns objects inside `teachbase_app`; it does not require superuser privileges or create cluster-level roles.

## File Registration Contract

Endpoint: `POST /api/v1/files`

The request contains workspace identity, optional actor identity, original filename, storage provider, portable storage key, media type, byte size and SHA-256. It records metadata only; upload streaming and storage adapters are separate future ports.

Rules enforced in Java and PostgreSQL:

- workspace must already exist;
- filename is a leaf name, not a path;
- storage provider is `local` or `object_storage`;
- storage key is relative and slash-delimited;
- drive letters, URI schemes, backslashes and `..` traversal are rejected;
- SHA-256 is normalized to 64 lowercase hexadecimal characters;
- byte size is non-negative;
- `(workspace_id, sha256)` is unique.
- file assets, versions, source documents, creators and audit actors are tied together with composite workspace foreign keys, preventing cross-workspace association through direct SQL.
- when an actor is supplied, that user must be an active member of the workspace or the API returns `403`.

The service performs a fast existing-record lookup and the repository repeats the guarantee with `ON CONFLICT DO NOTHING`. A losing concurrent transaction removes its provisional parent row, reads the committed winner and returns the same identities. Audit creation shares the registration transaction, so only the winner emits `file_asset.registered`.

## Verification Gate

Run:

```text
npm run test:java-foundation-phase1
```

The gate performs:

1. Java 21 compile, jOOQ generation and unit tests.
2. Spring Modulith architecture verification.
3. Survey report consistency validation.
4. Disposable PostgreSQL startup and Flyway migration.
5. Packaged Spring Boot JAR startup and health check.
6. Registration of a tracked DOCX fixture using only a repository-relative storage key.
7. Sequential duplicate registration validation.
8. Eight simultaneous registrations for one checksum, asserting one winner and stable IDs.
9. Database count, audit count, absolute-path rejection and cross-workspace foreign-key assertions.
10. Java process termination and disposable database directory removal.

Machine-readable result: `docs/reports/java_foundation_phase1_live_gate_20260831.json`.

## Deliberate Non-Scope

- No Python pipeline, prompt, model, role, route or threshold changes.
- No four-chain execution or Java orchestration adapter.
- No write to the historical `public` schema.
- No legacy data import yet.
- V001 itself contains no question, knowledge, review, editor, export or worker implementation. Editor and export foundations are added separately by V002 and documented in `docs/backend/java-editor-backend-foundation.md`.
- No authentication provider or production authorization policy yet.
- No file-byte upload endpoint or object-storage client yet.

## Next Construction Slice

Phase 2 should implement source evidence, canonical question revisions, knowledge references and human review. The first acceptance test must promote a representative source question into an approved revision, then prove that a later edit creates a new unreviewed revision without mutating the approved content. The editor remains a later consumer of immutable revisions rather than the owner of question truth.
