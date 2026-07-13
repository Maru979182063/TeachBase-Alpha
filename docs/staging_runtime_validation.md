# Staging Runtime Validation

This document describes the current validation/staging check that runs against a
dedicated local Postgres cluster under `outputs/staging_validation/local_pg_cluster`.

It does not target any shared team database, and it must not be pointed at a
production database.

## Scope

The script is:

- `tools/run_staging_validation.mjs`

It validates the current backend chain on a persistent local cluster:

1. initialize or reuse the local cluster data directory
2. recreate a staging database whose name contains `validation` or `staging`
3. start the `8790` runtime API against Postgres
4. import one real visual batch
5. import one real English `runtime_manifest.json`
6. review and publish both
7. run search, question bank, material build, export, and component rerun
8. run backup/restore smoke
9. restart the runtime API and re-check read paths
10. write JSON and Markdown reports under `outputs/staging_validation/{runId}/`

## Safety Rules

- localhost only
- database names must contain `validation` or `staging`
- names that look like `prod`, `production`, `live`, `main`, `shared`, or `team`
  are rejected
- the script masks database URLs in reports
- the script never writes passwords to reports

## Inputs

By default the script uses:

- visual batch:
  `outputs/visual_transcription_v0.1/case007_numberline_focus_20260702/runtime_out/06_6_asset_reconcile_refine/reconciled_refined_manifest.json`
- visual asset base:
  `outputs/visual_transcription_v0.1/case007_numberline_focus_20260702/runtime_out/06_asset_bundle`
- English runtime manifest:
  `outputs/ingress_runtime_v0.1/english_narrative_teacher_runtime_v01/runtime_manifest.json`

These can be overridden with `.env.staging.example` values or shell env vars.

## Run

```bash
node tools/run_staging_validation.mjs
```

## Outputs

Each run writes:

- `outputs/staging_validation/{runId}/staging_report.json`
- `outputs/staging_validation/{runId}/staging_report.md`

The report includes:

- masked DB URL
- git commit hash
- migration list
- public table count
- import / review / publish / export ids
- file outputs
- storage key samples
- runtime_state_snapshot row count
- blockers and warnings

## Important Boundary

This script validates the current backend chain only.

It does not:

- promote the branch to production
- change DDL
- expand tables
- bypass export preflight
- treat HTML externalization as a source of truth
