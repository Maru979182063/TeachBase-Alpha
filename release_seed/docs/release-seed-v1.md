# Release Seed V1 input contract

## Package layout

```text
teachbase_release_seed_v1/
├── manifest.json
├── questions.jsonl
├── question_relations.jsonl
├── source_documents.jsonl
├── source_regions.jsonl
├── assets/
├── validation_report.json
├── review_report.json
└── rejected_questions.jsonl
```

All JSON and JSONL files are UTF-8. JSONL files contain one object per line and
may be empty. Reproducible inputs use `/`-separated relative paths; absolute
paths, drive-letter paths, backslashes and `..` traversal are rejected.

The machine contract is
[`schemas/release-seed-v1.schema.json`](../schemas/release-seed-v1.schema.json).
It is a definition bundle: consumers select `$defs.manifest` for the manifest,
the corresponding row definition for each JSONL stream, and the two report
definitions for the reports.

## Immutable payload hash

`manifest.contentSha256` binds the immutable package payload without creating a
self-reference. The hash excludes `manifest.json`, `validation_report.json` and
`review_report.json`; both reports bind the resulting digest.

The byte stream is formed in this exact order:

1. `questions.jsonl`
2. `question_relations.jsonl`
3. `source_documents.jsonl`
4. `source_regions.jsonl`
5. `rejected_questions.jsonl`
6. every regular file below `assets/`, ordered by portable relative path

For every entry, SHA-256 receives UTF-8 relative path, one NUL byte, the exact
file bytes, and one NUL byte. The validator does not normalize JSON, newlines or
asset bytes.

This package-level digest is owned by `release_seed`. Per-question `contentHash`
and `taggerInputHash` are only checked for presence, lowercase SHA-256 shape and
declared equality at merge boundaries. Their canonicalization algorithm is
owned by the shared hash foundation and is intentionally not duplicated here.

## Field ownership

Original-source fields are immutable through tagging: stable source identity,
locator, prompt/stem, material, options, answer, explanation, formulas and image
references. The enrichment adapter accepts only difficulty, knowledge tags,
confidence, tagger identity/version, tagger input hash and
`needsHumanReview`. It rejects enrichment records that supply original-body
fields and always emits `releaseSeedDisposition=pending_review`.

Stable manual identity should be built from durable provenance such as:

```text
sourceSystem = manual_seed
sourceKey = batchId + originalFileSha256 + stable locator + original business ID
```

An editable spreadsheet row number alone is not a stable locator. Random IDs
must not be regenerated on replay.

## Approval and rejection

`questions.jsonl` is the approved stream and accepts only records carrying an
explicit human review record. `rejected_questions.jsonl` is the rejected
stream. Missing difficulty, missing primary knowledge tag, incomplete
enrichment or `needsHumanReview=true` may not be replaced with semantic
defaults; such records remain outside a frozen package until reviewed.

`review_report.json` binds batch ID, release version and package payload digest,
and records reviewer, time, policy, full/sample mode, sample size, approved and
rejected counts, and issue counts. The offline validator checks structural and
binding consistency. Final Review-state semantics remain an integration point
for the shared Review foundation.

## Offline validator boundary

`validator.py` checks required files, UTF-8 JSON/JSONL structure, required
fields, counts, maximum batch size, portable paths, source and relation
references, asset existence and digest, duplicate stable keys, enrichment
provenance declarations, review/report binding, and the immutable payload hash.

It does not make teaching-meaning decisions from regular expressions or keyword
lists. Taxonomy membership and semantic correctness belong to the shared
taxonomy/model/human review path. Database idempotency, interruption recovery,
post-import count/hash checks and search sampling belong to the deferred Java
Seed Loader and total gate.
