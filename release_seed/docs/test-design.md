# Release Seed V1 test design

## Executable now: offline contract tests

The current test suite uses a deterministic synthetic package and temporary
copies. It covers:

| Case | Expected result |
|---|---|
| Minimal complete package | passes |
| Manifest payload hash changed | fails |
| Difficulty outside 1–5 | fails |
| Primary knowledge tag absent | fails |
| Absolute asset path | fails |
| Asset bytes/hash mismatch | fails |
| Relation points to unknown question | fails |
| Complete difficulty + knowledge merge | source body unchanged; pending review |
| Missing enrichment | no semantic default; pending review |
| Enricher supplies original body field | fails |
| Tagger input hash declaration differs | fails |

The fixture builder is deterministic; rebuilding it and then validating it is a
contract smoke test. It is synthetic and does not count as a real data gate.

## Data-fixture matrix for the next integration phase

Five provenance fixtures must be bound to real source files before the live
gate: DOC mathematics, DOC English, PDF mathematics, PDF English and
`manual_seed`. Each fixture must preserve the original text/material/options/
answer/explanation/formula/image references and carry original file SHA-256 plus
a stable locator. Current inventory contains only the `manual_seed` mathematics
candidate set; the other four counts are zero.

## Deferred until shared foundations and Java Loader are ready

The following are test specifications, not current passing claims:

1. Recompute canonical per-question content and tagger-input hashes with the
   shared hash implementation; detect any model modification of original body.
2. Validate primary/secondary tags against the shared taxonomy contract without
   lexical heuristics.
3. Map the shared Review contract into an approved revision and reject packages
   without a matching human signature.
4. Start an isolated PostgreSQL instance, run Java validate/dry-run/import/verify,
   and verify cleanup of the database and Java process.
5. Import the same package twice; the second run creates no question or revision.
6. Reuse a stable source key with changed content; the run reports a conflict.
7. Interrupt after a durable batch checkpoint, restart, and verify recovery with
   no duplicates.
8. Verify approved counts, batch payload hash, asset publication and random
   field-level samples after import.
9. Sample Chinese knowledge-tag search and confirm expected approved questions
   are discoverable.
10. Verify all five source types and both subjects through the full path.

The final live-gate report must include commands, versions, isolated database
result, counts, idempotency result, recovery result, sampling evidence and
cleanup status without passwords or absolute local paths.
