# Release Seed and Question Governance Integration

## Boundary

The `release_seed/` directory owns the portable package, byte-level package digest,
offline validator, fixtures and merge tooling. The Java backend owns canonical question
hashing, database identity, review state, taxonomy membership and durable import
observations. Neither side reimplements the other's hash algorithm.

The current real-data inventory remains 200 pending candidates and zero approved
questions. The synthetic fixture proves the package shape only.

## Named Java Ports

The Java Seed Loader depends only on these Modulith named interfaces:

| Interface | Purpose |
|---|---|
| `question::api` / `QuestionBatchImporter` | Import bounded pending-review batches and verify declared per-question content hashes |
| `review::api` / `ReviewWorkflow` | Open hash-frozen cases and append evidence-bearing approval/rejection decisions |
| `taxonomy::api` / `TaxonomyCatalog` | Resolve codes or aliases against an explicit version and pin assignments |
| `fileasset::api` | Publish and reference source/assets through portable storage keys |

The Loader must not import application or infrastructure packages and must not write the
question, review or taxonomy tables directly.

## Hash Mapping

| Release Seed value | Backend value |
|---|---|
| `manifest.contentSha256` | Package/batch evidence; include in review evidence and Loader checkpoint records |
| question `contentHash` | Declared semantic hash; `QuestionBatchImporter` recomputes and rejects mismatch |
| exact original/source row bytes or canonical source packet | `sourcePayloadHash` |
| complete normalized Loader command including batch and row identity | `importEnvelopeHash` |
| `taggerInputHash` | Enrichment evidence; preserve in provenance/review evidence, not as semantic content identity |

A semantic replay can therefore reuse one `question_revision` while adding a distinct
`question_import_observation` for a changed envelope.

## Approval Mapping

Approved package rows are still imported with `reviewStatus=pending_review`. The Loader
then opens a review case and submits an evidence-bearing decision with:

- `policyVersion` from `reviewPolicyVersion`;
- `decisionSource=release_seed`;
- `evidenceOccurredAt` from the signed review timestamp;
- evidence containing batch ID, release version, package digest, external reviewer ID
  and validation report digest.

The executing `actorUserId` is a workspace service principal or mapped active member;
the external reviewer identity remains evidence and is never silently converted to a
random UUID. Direct approved import remains forbidden.

## Taxonomy Pin

Release Seed V1 currently carries free-text primary and secondary knowledge tags but no
taxonomy version pin. The Loader must not resolve them against whichever version happens
to be active at runtime. Before the Loader can claim production readiness, one of these
must be frozen in its validated input contract:

1. a package-level `taxonomyKey` plus `taxonomyVersionKey`; or
2. an operator-supplied `taxonomyVersionId` recorded in the Loader batch manifest.

For every tag, `TaxonomyCatalog.resolve` receives that explicit version and resolves an
exact knowledge code or normalized alias. Missing tags fail closed. The resulting links
pin both the question revision and taxonomy version. Difficulty remains an imported,
nullable value and this integration defines no difficulty rubric.

## Loader Gate

The Loader gate validates offline input first, then exercises validate,
dry-run, import and verify against disposable PostgreSQL. It must cover exact replay,
changed-envelope observation, source-key/content conflict, interruption recovery,
evidence-preserving approval, taxonomy resolution, Chinese search, asset publication,
post-import counts/hashes and complete process/database cleanup. Reports may contain
portable repository-relative paths but no local absolute paths as input contracts.

This gate is implemented by `npm run test:release-seed-loader`. Real package readiness
remains separate and is still blocked on completed enrichment and human review evidence.
