# Release Seed Java Loader

## Status

The Java Loader infrastructure is implemented. It validates the V1 package, performs a
database-aware dry run, imports through named Modulith ports, resumes after interruption
and independently verifies the resulting database state.

This does not make a real Release Seed package available. Current discovery evidence is
still 200 pending candidates, zero approved questions and no frozen real package.

## Ownership

The `releaseseed` module owns only package orchestration, process leases, monotonic
question checkpoints, package-to-domain ID mappings and machine reports. It uses
`fileasset::api`, `source::api`, `question::api`, `review::api` and `taxonomy::api`.
It never writes those modules' tables directly.

V006 adds `release_seed_batch`, `release_seed_item`, source document mappings and source
region mappings. It also adds durable external keys to source documents and regions so
recovery never relies on row order or a machine path.

## Commands

The packaged JAR runs the Loader as a non-web command. Required database variables are
the same as the server. Set these Loader variables:

```text
TEACHBASE_RELEASE_SEED_MODE=validate|dry-run|import|verify
TEACHBASE_RELEASE_SEED_PACKAGE_ROOT=<runtime package directory>
TEACHBASE_RELEASE_SEED_REPORT_PATH=<runtime report file>
TEACHBASE_RELEASE_SEED_WORKSPACE_ID=<uuid>
TEACHBASE_RELEASE_SEED_ACTOR_USER_ID=<uuid>
TEACHBASE_RELEASE_SEED_TAXONOMY_VERSION_ID=<uuid>
TEACHBASE_RELEASE_SEED_DEFAULT_SUBJECT=<subject>
TEACHBASE_RELEASE_SEED_DEFAULT_STAGE=<stage>
TEACHBASE_RELEASE_SEED_DEFAULT_GRADE=<grade>
TEACHBASE_RELEASE_SEED_DEFAULT_QUESTION_TYPE=<type>
TEACHBASE_RELEASE_SEED_STORAGE_ROOT=<runtime storage directory>
```

Then run:

```text
java -jar backend/teachbase-server/target/teachbase-server-0.1.0-SNAPSHOT.jar \
  --spring.main.web-application-type=none
```

Package and storage paths are runtime deployment settings. They are not persisted or
reported as reproducible input contracts. Reports contain package digest and stable
business IDs instead.

## Mode Semantics

| Mode | Business writes | Contract |
|---|---:|---|
| `validate` | 0 | UTF-8, required files, counts, references, assets, report bindings and exact package digest |
| `dry-run` | 0 | Validation plus server canonical content hash and explicit-version taxonomy resolution |
| `import` | Yes | Atomic assets, sources, pending import, review evidence, taxonomy assignments, links, relations and checkpoints |
| `verify` | 0 | Recounts items, revisions, decisions, sources, regions, relations and taxonomy links |

`import` acquires an expiring database lease. Every question is a separate transaction;
the item result and `next_question_index` advance in that same transaction. A crash
cannot leave a question approved without its checkpoint. After lease expiry another
process resumes from the first uncommitted item. A completed package digest is an
idempotent no-op on replay.

## Fail-Closed Rules

- Direct approved question import remains forbidden.
- The server recomputes every declared `contentHash`.
- Taxonomy resolution requires one explicit active `taxonomyVersionId`.
- Unknown tags, changed source identity, invalid relationships or review evidence fail
  before the corresponding checkpoint advances.
- Assets are checksum-verified, written through a same-directory unique temporary file
  and atomically replaced before registration.
- External reviewer identity, policy, package digest and report evidence are preserved;
  no random reviewer UUID is invented.

## Verification

Run `npm run test:release-seed-loader`. The live gate uses disposable PostgreSQL and
separate Java processes for validate, dry-run, interrupted import, resumed import,
completed replay and verify. It injects an exit after the first committed item and
confirms the second process resumes at index 1.

Machine report: `docs/reports/release_seed_loader_live_gate_20260901.json`.
