# TeachBase Server

Java-controlled modular backend for the TeachBase workbench.

## Requirements

- Java 21 JDK available on `PATH`
- Maven 3.9+
- PostgreSQL 16+

The repository build runner derives `JAVA_HOME` from the active Java 21 `javac`, so a stale machine-level `JAVA_HOME` does not silently select an older JDK.

## Build And Test

From the repository root:

```text
npm run build:java-foundation
npm run test:java-foundation-phase1
npm run test:editor-backend
npm run test:question-governance
npm run test:release-seed-loader
npm run test:java-backend-foundation
```

The full phase-one gate compiles with Java 21, verifies Spring Modulith boundaries, runs domain tests, starts an isolated PostgreSQL instance, applies Flyway, starts the packaged JAR and exercises the file-registration API.

## Runtime Configuration

Required environment variables:

- `TEACHBASE_DATABASE_URL`: JDBC PostgreSQL URL
- `TEACHBASE_DATABASE_USER`: application database user
- `TEACHBASE_DATABASE_PASSWORD`: application database password

Optional variables:

- `TEACHBASE_DATABASE_POOL_SIZE`: Hikari pool size, default `10`
- `TEACHBASE_SERVER_PORT`: HTTP port, default `8080`

Database storage locations are represented by portable relative storage keys. Machine absolute paths, URI schemes, backslashes and parent traversal segments are rejected.

## Phase-One API

`POST /api/v1/files` registers metadata for a file already accepted by a storage adapter. The endpoint does not copy or transform the file.

Idempotency is defined by `(workspace_id, sha256)`. The first successful request returns `201`; equivalent sequential or concurrent requests return `200` and the same asset/version identities.

Health is available at `GET /actuator/health`.

## Editor And Export Foundation

V002 adds backend-owned editor revisions, three variant definitions, optimistic concurrency, immutable preview snapshots and idempotent export requests. Formula LaTeX, mind-map trees and student blank annotations remain structured Tiptap source data.

The document renderer and export worker consume immutable snapshots; editor interaction
remains frontend-owned while structured source, revisions, rendering and export history
remain backend-owned.

## Question Governance

V005 separates semantic content, source payload and import envelope hashes. Imports can
only stage unreviewed or pending revisions. The `review` module is the ordinary approval
boundary and serializes concurrent decisions before advancing the production revision
pointer. The `taxonomy` module stores versioned knowledge trees and revision-pinned
assignments. It intentionally does not define a difficulty rubric.

## Release Seed Loader

V006 adds a resumable non-web Loader with validate, dry-run, import and verify modes.
It uses expiring database leases, per-question transactions and monotonic checkpoints,
and calls only named file/source/question/review/taxonomy module ports. See
`docs/backend/release-seed-loader.md` for the command contract.
