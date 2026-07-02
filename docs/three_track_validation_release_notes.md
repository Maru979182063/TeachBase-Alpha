# Three-Track Validation Release Notes

Updated: 2026-07-01

## Summary

This release captures the three-track validation baseline for:

- `math_junior`
- `math_senior`
- `english_senior`

It is a validation release only. It is not a production-ready release.
Its validated upstream input is `LessonDraftBundle`, not raw PDF/OCR/model-import accuracy.

## Included Changes

### Runtime entry alignment

- made `8790` the only official runtime API entry
- downgraded `8792` to a deprecated compatibility forwarder
- aligned startup scripts and README guidance to `8790`

### Track profile centralization

- added centralized subject track configuration
- introduced canonical `subject`, `stage`, `track_code`, `plugin_id`, and `difficulty_scheme` mapping
- removed the senior-English risk of inheriting math defaults

### Schema and storage alignment

- added `20260624_three_track_validation_alignment.sql`
- pushed `subject`, `stage`, and `track_code` into projection, question-bank, and material-build layers
- normalized difficulty storage into level, scheme, source, and confidence

### Checkpoint inheritance and override

- added fact-layer support for source-node default checkpoints
- added per-task override actions: `add`, `remove`, `replace`

### Projection rebuild validation

- verified `task_projection` can be deleted, GET search stays read-only, and the explicit rebuild path can restore it from fact-backed state

### Core Postgres write-path cutover

- moved the core LessonDraftBundle write path off the full-runtime replay bridge
- changed Postgres runtime health from `validation_only / state_replay_bridge` to `validation_baseline / scoped_table_write`
- kept `runtime_state_snapshot` as debug / migration support only

### Test coverage

- added three-track golden fixtures
- added `npm run test:three-track-baseline`
- kept `npm run test:production-readiness` honest at `NOT_READY`

## Validation Outcome

- three-track baseline result: `VALIDATION_BASELINE_READY`
- backend write-path blocker result: `POLICY-001` closed
- branch positioning: still validation baseline, not a production promotion

## Explicit Boundary

- validated chain: `LessonDraftBundle -> fact layer -> review -> publish -> search -> question bank -> material -> export -> component rerun`
- not validated in this release: `PDF/DOCX -> OCR/model decomposition -> LessonDraftBundle`

## Follow-Up Reminder

The next round should only remove the `NOT_READY` production gate after a separate production architecture review is explicitly approved.
