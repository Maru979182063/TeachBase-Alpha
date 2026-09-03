# TeachBase Alpha Phase 2B Package Foundation Hardening

## Real status

- Baseline branch: `integration/repository-scope-clean-20260715`
- Baseline SHA: `b96a400daadd11fd496ecc47152861f3d5496dae`
- Working branch: `refactor/pipeline-modularization-phase2b-foundation-hardening`
- Phase 2B gate entrypoint: `npm run test:modularization-phase2b`
- Machine-readable local report: `docs/reports/modularization_phase2b_test_report_20260715.json`

## Implemented

- Canonical Semantic Profile Config implementation now lives at `src/teachbase/semantic_role/profile_config.py`.
- Legacy config entrypoint `tools/semantic_profile_config.py` remains a compatibility wrapper/re-export with the same helper names.
- Package evaluator entrypoint `src/teachbase/semantic_role/evaluator.py` keeps the old `load_semantic_profile_configs(workspace_root)` function name and delegates to the canonical package implementation.
- Artifact writes in `src/teachbase/infrastructure/artifact_store.py` now use unique same-directory temporary files, close before `os.replace`, clean up on exceptions, and serialize/retry replace on Windows same-path contention.
- GitHub Actions workflow added at `.github/workflows/modularization-phase2b.yml`.

## Actually run by the Phase 2B gate

- Phase 2A full gate.
- Config parity tests using committed `config/semantic_profiles` files.
- Artifact single-write, concurrent-write, no-temp-residue, and replace-failure cleanup tests.
- Architecture boundary tests.
- Legacy CLI compatibility smoke.
- English portable regression.
- DOCX Native regression.

## Not implemented

- DOCX Native module migration.
- English Text-first module migration.
- Semantic Shadow predictor or adapter migration.
- Runtime/Postgres changes.
- Gold data production.
- Prompt/model/route/role/threshold changes.
- Large directory relocation.

## Artifacts

- `docs/reports/modularization_phase2b_architecture_20260715.md`
- `docs/reports/modularization_phase2b_test_report_20260715.json`
