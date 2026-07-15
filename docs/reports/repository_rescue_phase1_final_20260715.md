# Repository Rescue Phase 1 Final - 2026-07-15

## Real Status

Phase 1 local rescue reached a clean local integration checkpoint, but not a production/effectiveness READY state.

Final status: `PHASE1_RESCUE_INCOMPLETE`

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

`PHASE1_RESCUE_INCOMPLETE`
