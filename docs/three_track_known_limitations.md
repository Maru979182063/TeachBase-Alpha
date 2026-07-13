# Three-Track Known Limitations

Updated: 2026-07-01

## Current Positioning

This round delivered a validation baseline, not a production release.

The runtime currently self-identifies as:

- `releaseChannel = validation_baseline`
- `architectureMode = scoped_table_write`
- validated input boundary = `LessonDraftBundle`

## Active Limitations

### 1. This branch is still not the production promotion branch

- the backend write-path blocker `POLICY-001` is closed
- that does not automatically promote this branch to a production release branch
- final production promotion still requires separate operational review and sign-off

### 2. Compatibility forwarding is still present

- port `8792` is deprecated
- it remains in place only as a compatibility bridge
- it should not be treated as a second official runtime entry

### 3. Current projection model is still rebuild-first

- `task_projection` is rebuildable from facts
- this is correct for the current validation scope
- it is not the same as a final production-optimized query architecture

### 4. This is not the final domain ERD

- the current schema is sufficient for three-track validation
- it is not being declared the final full-discipline production data model

### 5. Large-scale soak and capacity work remain future tasks

This round did not attempt:

- long-duration soak validation
- larger-volume subject expansion validation
- final production concurrency sizing
- final production partitioning and indexing strategy for full-discipline scale

### 6. OCR and model-import accuracy are outside this baseline

- this validation starts from `LessonDraftBundle`
- it does not prove `PDF/DOCX -> OCR -> model decomposition -> LessonDraftBundle`
- upstream ingestion quality must be reviewed and validated separately

## Recommended Next-Step Focus

After review, the next step should be to decide whether to:

- keep shrinking the remaining non-core state bridge paths, or
- open a separate production promotion round with operational readiness criteria
