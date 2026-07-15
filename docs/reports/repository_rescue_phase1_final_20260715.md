# Repository Rescue Phase 1 Final - 2026-07-15

## Real Status

Phase 1 local rescue reached a clean local integration checkpoint. Repository rescue status and Semantic Role business-effectiveness status are reported separately.

Repository rescue status: `PHASE1_RESCUE_LOCALLY_COMPLETE`

Semantic Role Effectiveness dataset status: `SEMANTIC_ROLE_EFFECTIVENESS_DATASET_REVIEW_REQUIRED`

## Branch Split Result

- `fix/semantic-role-eval-validity-v01`: Semantic Eval P0 fixes.
- `feat/english-text-first-v05-isolated-clean`: English Text-first portable fixtures and tests.
- `feat/docx-native-repair-v01-isolated-clean`: DOCX Native portable tests.
- `integration/repository-scope-clean-20260715`: local integration checkpoint.

## Semantic Eval P0 Fixes

- Prediction input no longer derives `table_like` or `diagram_like` from `expected_presentation_kind`.
- Metamorphic tests verify that changing each `expected_*` field does not change prediction input or prediction output.
- Existing synthetic fixtures are preserved as `CONTRACT_FIXTURE`.
- Formal effectiveness metrics only count `VERIFIED_REAL_GOLD`.
- `VERIFIED_REAL_GOLD` requires human/manual source, valid SHA-256, existing source artifact, hash match, and audit evidence.
- Candidate discovery is split into explicit root discovery and manifest-driven evaluation.

## Portable Test Result

- Semantic Eval: 9 passed.
- English Text-first: 7 passed.
- DOCX Native: 10 passed.
- Unified Phase 1 gate: 37 passed.

## Integration Gate Result

- Command: `npm run test:repository-rescue-phase1`
- Exit code: 0
- Result: 37 passed.
- No paid model call.
- No database write.
- No Runtime import.

## Status Split

- `PHASE1_RESCUE_LOCALLY_COMPLETE`
- `EVALUATION_CONTRACT_VALID`
- `PORTABLE_REGRESSION_LOCAL_READY`
- `INTEGRATION_CHECKPOINT_LOCAL_READY`
- `SEMANTIC_ROLE_EFFECTIVENESS_DATASET_REVIEW_REQUIRED`

No Semantic Role Effectiveness READY claim is made.

## Dirty Worktree Investigation

Original worktree: `C:\Users\EDY\Documents\教研基建`

Current dirty files:

- `tools/english_text_first_verifier_projector_v02.py`
  - SHA-256: `6BF515E566E9723544D2F35C7EC5167E90D53C82B981A82C6E3660E4F49C21EE`
  - LastWriteTimeUtc: `2026-07-15T09:09:06Z`
  - Diff: asset verifier now carries `asset_candidates` and marks rough derivative assets as incomplete for required coverage.
  - First successful pre-rescue patch: included initially.
  - Current refreshed pre-rescue patch: included.
  - DOCX clean branch `47fbfcf5c5f6691a1e2ddcc813a3140ba3517531`: file absent.

- `tools/docx_native_text_repair_model_node_v01.py`
  - SHA-256: `FE832EA00C197E6E244BCF64CA1C8104CC0D387B97BF287F452ABEF0A90CD06C`
  - LastWriteTimeUtc: `2026-07-15T09:28:55Z`
  - Diff: wraps model JSON parsing in `try/except json.JSONDecodeError`, builds validation issues, and retries when possible.
  - First successful pre-rescue patch: not included initially; it appeared dirty later and the pre-rescue patch was refreshed.
  - Current refreshed pre-rescue patch: included.
  - DOCX clean branch SHA for same file: `793A4ABE8C2F5F88DC2A3FC87B187300EB17562FE953BF0650616AEF0F6A998E`
  - Matches DOCX clean branch: `false`.

Likely source of second dirty file: unknown external/user/parallel process. The DOCX dirty mtime predates the safety refresh and the DOCX clean worktree was created after this dirty file had already been detected. Rescue worktree edits were made under separate worktree directories and did not write to the original worktree business files.

Post-rescue safety snapshot:

- `outputs/git_safety_backup_20260715/post_repository_rescue/post_rescue_working_tree.patch`
- `outputs/git_safety_backup_20260715/post_repository_rescue/tools__english_text_first_verifier_projector_v02.py`
- `outputs/git_safety_backup_20260715/post_repository_rescue/tools__docx_native_text_repair_model_node_v01.py`
- `outputs/git_safety_backup_20260715/post_repository_rescue/safety_manifest.json`

## Remaining Risks

- No real `VERIFIED_REAL_GOLD` set exists yet.
- Semantic effectiveness status remains `SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED`.
- English Text-first is still experimental and fixture-backed.
- DOCX Native tests cover unit behavior and recorded/mock repair paths, not full production DOCX ingestion at scale.

## Exact Branches And Commits

- `fix/semantic-role-eval-validity-v01`: `0934a30815fa487ac96474dd6fbb23cba6e54216`
- `feat/english-text-first-v05-isolated-clean`: `592ab6167eabe4012dc50bd0e370eca1e7f0d098`
- `feat/docx-native-repair-v01-isolated-clean`: `47fbfcf5c5f6691a1e2ddcc813a3140ba3517531`
- `integration/repository-scope-clean-20260715`: final commit SHA is recorded in the handoff response because a commit cannot reliably contain its own final hash.

## Final Status

`PHASE1_RESCUE_LOCALLY_COMPLETE`

`SEMANTIC_ROLE_EFFECTIVENESS_DATASET_REVIEW_REQUIRED`
