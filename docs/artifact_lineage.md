# Artifact Lineage

`canonical_release_decision` answers whether a question may enter Runtime.
Artifact lineage answers why a Runtime question exists and where it came from.

The lineage layer is metadata-only. It does not add tables, migrations, Runtime
models, or split_v03 behavior.

## Canonical Schema

```json
{
  "lineage": {
    "source_run_id": "",
    "source_document_id": "",
    "document_revision_id": "",
    "semantic_node_id": "",
    "question_id": "",
    "asset_ids": [],
    "release_decision_id": "",
    "runtime_import_id": "",
    "created_at": ""
  }
}
```

## Where Lineage Appears

- `question_asset_manifest_v0.1.json`: each question record carries `lineage`.
- `canonical_release_decision.json`: each decision carries `lineage` and
  `release_decision_id`.
- `allow_list_manifest.json`: keeps the legacy ID arrays and also adds
  `allow_items`, `review_items`, and `block_items` with lineage.
- Runtime import response: keeps `releaseGate` and adds `lineage` in the import
  result.

## Audit

Use:

```powershell
node tools/audit_artifact_lineage.mjs `
  --canonical outputs/release_decision/run_001/canonical_release_decision.json `
  --allow-list outputs/release_decision/run_001/allow_list_manifest.json `
  --runtime-import-result outputs/runtime/import_result.json `
  --out-dir outputs/artifact_lineage/run_001
```

It writes:

```text
artifact_lineage_audit.json
```

The audit checks:

- `question_id` exists.
- Matching release decision exists.
- `release_decision_id` exists.
- At least one `asset_id` exists.
- `source_run_id` exists.
- Runtime import lineage preserves `runtime_import_id`.

## Boundary

Lineage is not a release decision and does not change allow/review/block rules.
It is only the trace path from source document to Runtime import artifact.
