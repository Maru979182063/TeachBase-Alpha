# Generated Material Policy

PR #4 originally added 101 files under report, archive, release-seed report, and final-chain fixture locations. The Phase 2B merge added two more report files, so the closure inventory contains 103 entries.

- `RUNTIME_REQUIRED_FIXTURE`: may remain tracked only when its real file format is validated and it is required by a portable dry-run.
- `STABLE_GOLDEN_EVIDENCE`: may remain tracked when it is human-readable architecture or historical audit evidence rather than a regenerable CI result.
- `CI_GENERATED_REPORT`: must not remain tracked; CI writes it locally and uploads it as a workflow artifact.
- `HISTORICAL_ARCHIVE`: remains isolated under `_archive/` and is not an active runtime input.
- `INVALID_PLACEHOLDER`: must be replaced with a valid minimal container or renamed.
- `UNKNOWN`: blocks integration.

`python tools/check_generated_material_policy.py --base <base-sha>` emits the complete machine-readable inventory. The inventory is anchored to merge commit `439249e95ffd3d27427812ac2b6a59744efb7421`, preserving the original 101-file audit population plus the two Phase 2B report additions even after CI reports are removed from the final tree.

The Java prototype inventory, legacy mapping, and environment report are frozen survey inputs because no repository-contained source can reproduce them. The database inventory is different: CI regenerates it against an ephemeral PostgreSQL instance before validating the survey contract.

The DOCX/PDF fixtures validate container parsing and adapter portability only. They are not evidence of production question quality or continuous pipeline readiness.
