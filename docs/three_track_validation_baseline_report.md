# Three-Track Validation Baseline Report

Updated: 2026-06-24

## Conclusion

Current result: `VALIDATION_BASELINE_READY`

This result means the repository passed the requested three-track validation baseline.
It does not mean the backend is production-ready.
It validates the backend starting from `LessonDraftBundle`, not OCR/PDF-to-`LessonDraftBundle` accuracy.

## Latest Baseline Run

- Command: `npm run test:three-track-baseline`
- Run ID: `three_track_validation_baseline_2026-06-24T09-42-07-194Z_d63ff3ae`
- Report directory: `outputs/production_readiness/three_track_validation_baseline_2026-06-24T09-42-07-194Z_d63ff3ae`
- PostgreSQL: `PostgreSQL 18.4 on x86_64-windows, compiled by msvc-19.44.35226, 64-bit`
- Total: `21`
- Passed: `21`
- Failed: `0`
- Skipped: `0`
- Final status: `VALIDATION_BASELINE_READY`

## Scope Completed In This Round

### 0. Bundle boundary kept explicit

- the validated input boundary is `LessonDraftBundle`
- this baseline covers `LessonDraftBundle -> fact layer -> review -> publish -> search -> question bank -> material -> export -> component rerun`
- it does not claim that PDF, DOCX, OCR, or model decomposition into `LessonDraftBundle` is already production-accurate

### 1. Single runtime entry

- Port `8790` is now the only official runtime API entry
- Port `8792` has been downgraded to a deprecated compatibility forwarder
- Default startup scripts and README references now point to `8790`

### 2. Centralized track profile

The runtime now uses centralized track profiles for:

- `math_junior`
- `math_senior`
- `english_senior`

Each profile carries its own:

- canonical `subject`
- canonical `stage`
- `track_code`
- `plugin_id`
- `difficulty_scheme`

This closes the old risk where senior English could accidentally fall back to math-specific defaults.

### 3. Three-track alignment migration

The repository now includes:

- `config/migrations/20260624_three_track_validation_alignment.sql`

This migration aligns the validation schema by pushing `subject`, `stage`, and `track_code` into:

- `task_projection`
- `question_bank_item_revision`
- `question_bank_item`
- `material_build`
- `task_subject_ext`
- `lesson`

It also normalizes difficulty storage so that difficulty is expressed as:

- `difficulty_level`
- `difficulty_scheme`
- `difficulty_source`
- `difficulty_confidence`

### 4. Fact-layer checkpoint inheritance

The runtime now supports:

- `source_node_revision`
- `task_revision`
- `source_node_checkpoint_link`
- `task_checkpoint_override`

Default checkpoint codes are inherited from source nodes.
Only exceptional items use per-task overrides with:

- `add`
- `remove`
- `replace`

### 5. Projection rebuildability

`task_projection` is treated as a rebuildable query projection.
The validation baseline now verifies that if projection rows are deleted from the fact-backed store, GET search reports the degradation and the explicit rebuild path can reconstruct them from lesson facts.

### 6. Three-track golden fixtures

Golden fixtures were added for:

- junior math
- senior math
- senior English

They cover the required end-to-end flow:

- import
- approve
- publish
- search
- question bank
- material build
- export
- component rerun

## Acceptance Highlights

The latest baseline run verified all of the following:

- `8790` actually runs through the store interface
- `8792` no longer acts as a second backend main entry
- junior math, senior math, and senior English remain isolated in search and question bank
- senior English no longer uses any math plugin id
- each track uses its own `difficulty_scheme`
- ordinary tasks inherit checkpoint defaults from `source_node`
- special tasks use explicit override actions only when needed
- `task_projection` can be deleted and rebuilt from facts
- FileStore and PostgresStore regression paths continue to align
- backup and restore continue to pass

## Related Outputs

- JSON report:
  - `outputs/production_readiness/three_track_validation_baseline_2026-06-24T09-42-07-194Z_d63ff3ae/three_track_validation_baseline_report.json`
- JUnit report:
  - `outputs/production_readiness/three_track_validation_baseline_2026-06-24T09-42-07-194Z_d63ff3ae/three_track_validation_baseline_junit.xml`
- Summary:
  - `outputs/production_readiness/three_track_validation_baseline_2026-06-24T09-42-07-194Z_d63ff3ae/three_track_validation_baseline_summary.md`
