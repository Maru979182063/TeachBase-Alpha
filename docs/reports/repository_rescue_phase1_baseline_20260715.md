# Repository Rescue Phase 1 Baseline - 2026-07-15

## Real Status

- Original branch protected: `backup/pre-repository-rescue-20260715`
- Protected original HEAD: `3e543aad7e190f619d1f5982e97ebab941adcac1`
- Original dirty worktree was not reused for rescue edits.
- Safety artifacts: `outputs/git_safety_backup_20260715/pre_repository_rescue/`
- Safety artifacts include `working_tree.patch`, full dirty-file copies, and `safety_manifest.json`.

## Implemented

- Rescue work was isolated in Git worktrees.
- Semantic Eval branch starts from `c2efef90c2257261103da7f17f8cdc783d29157a`.
- English branch starts from `6747169c0ed405844e6822dbef51057561ed5e5c`.
- DOCX branch starts from `6747169c0ed405844e6822dbef51057561ed5e5c`.
- Integration branch starts from `6747169c0ed405844e6822dbef51057561ed5e5c` and cherry-picks small scoped commits.

## Current Code Truth

- `3e543aad` mixed English Text-first and DOCX Native code into the Semantic Eval remote branch.
- The Semantic Eval runner previously derived input fragment flags from `expected_presentation_kind`.
- The existing 12 synthetic Semantic Eval fixtures were not real audited Gold, even though they used `gold_status=VERIFIED`.
- English tests previously relied on untracked local `outputs/...` directories.
- DOCX Native had implementation files but no dedicated tests.

## Actually Run

- `npm run test:semantic-role-eval`: 9 passed.
- `npm run test:english-text-first-v05`: 7 passed.
- `npm run test:docx-native-repair`: 10 passed.
- `npm run test:repository-rescue-phase1`: 37 passed.
- Semantic Eval runner status: `SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED`, exit code 20.

## Artifacts

- Machine-readable test report: `docs/reports/repository_rescue_phase1_test_report_20260715.json`
- Semantic Eval output: `outputs/semantic_role_effectiveness_eval/integration_phase1_20260715/`

## Status

`PHASE1_RESCUE_INCOMPLETE`

Reason: real human-reviewed Gold is still absent, so effectiveness READY is intentionally not claimed.
