# Production Readiness Final Report

Updated: 2026-07-01

## Current Status

Current branch status: `VALIDATION_BASELINE_READY`

This repository now has:

- a verified three-track validation baseline
- a closed `POLICY-001` write-path blocker
- a runtime that reports `releaseChannel = validation_baseline`
- a runtime that reports `architectureMode = scoped_table_write`

The validated upstream boundary remains `LessonDraftBundle`, not OCR/PDF-to-`LessonDraftBundle` accuracy.

## 2026-07-01 Architecture Closure

The key change in this round is that the core Postgres write path no longer uses the full-runtime replay bridge.

Closed core paths:

- `importLessonDraftBundle`
- `approveReviewTask`
- `requestReviewChanges`
- `publishLesson`
- `createQuestionBankItem`
- `createMaterialBuild`
- `addMaterialBuildItems`
- `exportMaterialBuild`
- `registerExportRun`

These paths now hydrate only the required Postgres scope and persist targeted table diffs back to the normalized facts.

## What Remains Explicitly Out of Scope

This report still does not claim a production promotion:

- the branch remains a validation-baseline branch
- `task_projection` remains a rebuildable projection rather than the final optimized production query model
- the compatibility port `8792` is still retained as a deprecated migration forwarder
- non-core rerun / patch / recovery paths still use the legacy bridge helper
- upstream OCR / PDF decomposition quality is not covered by this backend report

## Related Validation Baseline

See also:

- `docs/three_track_validation_baseline_report.md`
- `docs/three_track_known_limitations.md`
- `docs/three_track_validation_release_notes.md`
- `docs/release_gate/2026-07-01_validation_baseline.md`
