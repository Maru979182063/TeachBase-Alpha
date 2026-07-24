# Production Readiness Defects

Updated: 2026-07-01

## Closed Policy Gate

### POLICY-001 Validation baseline must not claim production readiness while the write path remains a state replay bridge

- Status: `closed`
- Gate: `POLICY-001`
- Closure result:
  - Postgres runtime health now reports `releaseChannel = validation_baseline`
  - Postgres runtime health now reports `architectureMode = scoped_table_write`
  - core LessonDraftBundle-based business writes no longer use the full-runtime replay bridge
- Verified core paths:
  - `importLessonDraftBundle`
  - `approveReviewTask`
  - `requestReviewChanges`
  - `publishLesson`
  - `createQuestionBankItem`
  - `createMaterialBuild`
  - `addMaterialBuildItems`
  - `exportMaterialBuild`
  - `registerExportRun`
- Remaining explicit boundary:
  - this branch is still a `validation_baseline` branch
  - it is not the production promotion branch
  - upstream `PDF/DOCX -> OCR/model decomposition -> LessonDraftBundle` quality remains outside this backend gate

## Closed Architecture Item

### S1-ARCH-001 Postgres snapshot was previously treated as a primary source risk

- Status: `closed`
- Current result:
  - `ARCH-001` passes
  - normalized Postgres tables are the active business source of truth
  - `runtime_state_snapshot` is retained only for debug / migration support

## Current Blocking Count

- `S0 = 0`
- `S1 = 0` within the reviewed validation-baseline scope
- `Policy gates = 0`

## Remaining Non-Blocking Follow-Ups

The following are still important, but they are no longer represented as open readiness blockers for this branch:

- decommission the deprecated `8792` compatibility forwarder after reference cleanup is complete
- decide whether non-core rerun / patch / recovery flows should also leave the scoped bridge
- perform larger-scale soak and capacity validation before any production promotion
- validate the upstream `PDF/DOCX -> OCR/model decomposition -> LessonDraftBundle` chain separately from the backend baseline
