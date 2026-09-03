# Question Ingestion, Governance, Search, Collections, and Placement

## Scope

This slice prepares the Java backend for controlled ingestion from the four protected
question pipelines. It does not change pipeline prompts, model policy, route logic, or
pipeline execution. The boundary begins after a pipeline has produced a complete
pre-database question packet.

The implementation is a Spring Modulith modular monolith on PostgreSQL. PostgreSQL is
the source of truth. Redis is intentionally absent: it may later cache hot search pages
or coordinate ephemeral UI sessions, but it must not own questions, baskets, revisions,
checkpoints, or snapshots.

## Ownership

| Module | Owns | Does not own |
|---|---|---|
| `question` | Stable question identity, immutable revisions, three hash domains, review projection, provenance, indexed search | Pipeline execution and review decisions |
| `review` | Frozen review cases, append-only decisions, sole ordinary approval path | Editing question content |
| `taxonomy` | Versioned knowledge trees, aliases and revision-pinned assignments | Difficulty policy and free-text content mutation |
| `collection` | Ordered baskets, optimistic saves, checkpoints, restore, immutable snapshots | Question content mutation |
| `editor` | Structured documents, placement, hydrated references, editor revisions and snapshots | Choosing a latest question revision implicitly |

Cross-module access is restricted to named APIs. Collection and editor code use
`QuestionRevisionDirectory`; neither imports question persistence classes.

## V004 Tables

| Table | Contract |
|---|---|
| `question` | Stable identity and explicit pointer to the production-approved revision |
| `question_revision` | Immutable normalized packet, review state, content hash, filter columns and structured JSON |
| `question_source_link` | Queryable link to original source document or region |
| `question_relation` | Parent-child, variant and related-question graph |
| `editor_question_reference` | Usage index pinning an editor revision to a question revision |
| `question_collection` | Basket aggregate and optimistic `draft_version` |
| `question_collection_item` | Current ordered basket projection |
| `question_collection_checkpoint` | Recoverable autosave, manual-save and restore history |
| `question_collection_snapshot` | Immutable collection publication envelope |
| `question_collection_snapshot_item` | Frozen question packets and usage index |

The complete application schema contains 29 business tables after V004.

## V005 Governance Tables

| Table | Contract |
|---|---|
| `question_import_observation` | Every distinct received import envelope, including semantic replays |
| `review_case` | Review target frozen by question revision and expected content hash |
| `review_decision` | Append-only approved or rejected human decision |
| `taxonomy_version` | Draft, active or retired version of a stable taxonomy key |
| `taxonomy_node` | Coded hierarchical node owned by one taxonomy version |
| `taxonomy_alias` | Version-local normalized lookup alias |
| `question_taxonomy_link` | Primary or secondary assignment pinned to one question and taxonomy revision |

## Ingestion Contract

`POST /api/v1/questions/import-batch` accepts at most 500 complete packets in one
transaction. Larger imports are split into bounded batches by the ingestion client.

- `(workspace_id, source_system, source_key)` identifies the same source question.
- Canonical teaching content produces `content_hash`; review state, source identity and
  operational provenance are deliberately excluded.
- `source_payload_hash` identifies the exact upstream/source packet. Callers may
  supply a lowercase SHA-256; otherwise the API derives a deterministic fallback.
- `import_envelope_hash` identifies the complete ingestion envelope. Every distinct
  envelope is retained in `question_import_observation`, including content replays.
- Replaying an identical packet returns the existing revision.
- Changed content creates the next immutable revision under a row lock.
- Import accepts only `unreviewed` and `pending_review`. Direct `approved` and
  `rejected` imports fail with a stable validation problem.
- A later pending or unreviewed revision becomes current review work but does not hide
  or mutate the previously approved production revision.
- `external_key` is a stable display/integration identifier, not searchable teaching
  text.

`content_json` preserves the full structured packet. Scalar columns are deliberate
search and filter projections, not a second competing representation.

## Review Contract

`POST /api/v1/review-cases` opens or reuses the one active case for a concrete question
revision. The case stores the expected semantic hash, so a decision cannot drift to a
different content revision.

`POST /api/v1/review-cases/{id}/decisions` accepts `approved` or `rejected` with the
expected hash. The transaction locks both review and question state, appends one
decision, updates the revision's query projection and, for approval, advances
`question.approved_revision_id`. Two concurrent terminal decisions cannot both win.
Each decision also preserves policy version, decision source, structured evidence and
the external evidence timestamp. Question import has no code path that advances the
production pointer.

## Taxonomy Contract

Taxonomy versions are created as drafts. Nodes, parent links, metadata and aliases can
only be added while draft. Activation atomically retires the prior active version for
the same workspace and taxonomy key. Active and retired versions are immutable.

Question assignments pin both `question_revision_id` and `taxonomy_version_id`; later
taxonomy promotion therefore cannot rewrite historical labels. Assignments distinguish
primary/secondary and human/model/import provenance. Confidence is optional. The
existing nullable `difficulty_stars` field is preserved without defining a rubric.
Code or alias lookup requires an explicit `taxonomyVersionId`; callers cannot silently
follow the currently active version.

## Search Contract

`GET /api/v1/questions/search` defaults to `reviewStatus=approved`. Review interfaces
may request `unreviewed`, `pending_review`, or `rejected`; non-approved searches inspect
the current revision only.

Search supports subject, stage, grade, type, difficulty and teaching-text query filters.
It returns:

- stable question and concrete revision IDs;
- explicit `reviewStatus` and `humanReviewed`;
- `referenced` when the question occurs in an editor, current basket, or frozen basket;
- provenance needed by the UI to show where the question came from;
- an opaque keyset cursor ordered by revision creation time and question ID.

PostgreSQL `pg_trgm` indexes Chinese phrase and substring search. A `simple` tsvector
expression index supports tokenized Latin content. Expression indexes are database
maintained, so application writes cannot leave stale search documents.

## Collection and Checkpoint Contract

`PUT /api/v1/question-collections/{id}/draft` replaces the complete ordered projection
in one transaction. `expectedDraftVersion` is mandatory. Two saves based on the same
version cannot both succeed; the loser receives HTTP 409 with `currentDraftVersion`.

Every successful save creates a self-contained checkpoint:

- `autosave` expires after seven days;
- `manual` has no automatic expiry;
- `restore` records recovery as a new version instead of moving the aggregate backward.

The checkpoint list excludes expired autosaves. Restoring a checkpoint resolves and
revalidates every pinned question revision before creating the new draft version.

`POST /api/v1/question-collections/{id}/snapshots` freezes metadata, order, display
settings, and full question packets. Later question revisions or basket edits cannot
change an existing snapshot.

## Editor Placement

`POST /api/v1/editor/documents/{id}/question-references` inserts up to 200 approved
revisions at a top-level editor position. One batch creates exactly one editor revision.
The request pins concrete revision IDs and target layers.

Each structured `questionReference` contains deterministic teacher and student Markdown.
The teacher projection may include answer and analysis according to placement settings;
the student projection does not. This hydration happens before snapshot creation, so
rendering never queries mutable question state. Unknown legacy references still fail
closed at render time.

## Verification

Run:

```text
npm run test:question-collection
npm run test:question-governance
```

The live gate uses disposable PostgreSQL and the packaged Java service. It imports 240
representative records across the four source-system names and verifies exact replay,
new correction revisions, Chinese index use, keyset pagination, review queues, usage
markers, concurrent save conflict, checkpoint restore, snapshot immutability, batch
editor placement, hydrated snapshot content, and complete cleanup.

Machine-readable evidence:
`docs/reports/question_collection_live_gate_20260831.json` and
`docs/reports/question_governance_live_gate_20260901.json`.

## Next Ingestion Step

Before bulk-loading production history, build a read-only adapter for each protected
pipeline output contract. Each adapter must map into the import packet, preserve its
source identifiers and provenance, validate a dry-run count/hash manifest, then submit
bounded pending-review batches. A Release Seed loader may later translate a signed,
validated human approval manifest into review decisions through an explicit privileged
adapter; it must not restore direct approved import. Begin with a representative sample
from each chain and verify review decisions before scaling to the full corpus.
