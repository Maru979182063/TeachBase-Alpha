# Release Decision Gate

## Real Policy

`complete` is not releasable.

`record=ok` is not import allowed.

Runtime auto-import must use `release_decision_summary.json`,
`canonical_release_decision.json`, and `allow_list_manifest.json` as the release
boundary. Existing transcription, visual asset, and split summaries remain useful
for diagnosis, but they are not the final import gate.

## Current Implementation

The release decision layer is implemented in:

- `tools/build_release_decision.mjs`

It reads stage-level audit outputs and writes:

- `canonical_release_decision.json`
- `allow_list_manifest.json`
- `release_decision_summary.json`

The Runtime import boundary now consumes `allow_list_manifest` when it is supplied
on `/api/runtime/imports/lesson-draft-bundles` or `/api/runtime/imports/runtime-manifest`.
Only tasks listed in `allow_question_ids` are kept in the imported
`LessonDraftBundle`. `review` and `block` questions stay outside automatic import
and should be routed to the review pool by the caller.

For legacy tests and non-production fixtures that do not provide release decision
artifacts, the import path remains backward compatible unless
`requireReleaseDecision` or `RUNTIME_REQUIRE_RELEASE_ALLOW_LIST=1` is set.

## Decision Rules

`allow` requires:

- transcription quality gate is `allow`
- asset audit is `pass`
- split_v03, when present, is `AUDITED_READY`

`review` applies when there is no hard fail, but at least one stage reports
`allow_with_review`, `needs_review`, or another non-blocking risk.

`block` applies when any of these is true:

- transcription quality gate is `block`
- asset audit is `fail`
- split_v03 is `QUARANTINED`

## CLI

```powershell
node tools/build_release_decision.mjs `
  --transcription path/to/transcription.json `
  --asset-audit path/to/asset_audit.json `
  --split-audit path/to/split_audit.json `
  --out-dir outputs/release_decision/run_001 `
  --run-id run_001
```

## Runtime Import Contract

Production automatic import should include:

```json
{
  "requireReleaseDecision": true,
  "allow_list_manifest": {
    "schema_version": "allow_list_manifest.v0.1",
    "run_id": "run_001",
    "allow_question_ids": ["q_001"],
    "review_question_ids": ["q_002"],
    "block_question_ids": ["q_003"]
  },
  "bundle": {
    "bundle_id": "lesson_bundle",
    "tasks": []
  }
}
```

The Runtime model still accepts `LessonDraftBundle`, runtime manifest, and visual
manifest payloads. The release gate is a pre-import filter, not a schema or
database migration.
