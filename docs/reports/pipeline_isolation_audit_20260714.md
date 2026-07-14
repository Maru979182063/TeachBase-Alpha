# Pipeline Isolation Audit 20260714

## Real Status

- Status: `PIPELINE_CONTROL_PLANE_BASELINE_READY`.
- Generated at: `2026-07-14T07:54:03.811535+00:00`.
- Current branch: `chore/pipeline-isolation-control-plane`.
- Current commit before control-plane commit: `5ceccd230dc7041b108046217f480357078aa68c`.
- This round did not modify business algorithms, model logic, prompts, dependencies, DDL, DOCX behavior, English Text-first behavior, Semantic Role behavior, or split_v03 behavior.
- No paid model call was made.

## Safety Backup

- Backup branch: `backup/pre-pipeline-isolation-20260714`.
- WIP backup commits:

```text
b92a8f44 chore: preserve late untracked DOCX preview renderer
d61de81d chore: WIP snapshot before pipeline isolation 20260714
4e0335ed Add semantic role shadow adapter flow
```

- Safety records: `outputs/pipeline_isolation_safety_20260714/`.
- Late business files discovered after branch creation were copied under `outputs/pipeline_isolation_safety_20260714/late_business_files_after_control_branch/` and stashed.
- Current stash list:

```text
stash@{0}: On chore/pipeline-isolation-control-plane: safety-reappeared-docx-files-after-audit-20260714
stash@{1}: On chore/pipeline-isolation-control-plane: safety-late-business-files-pre-control-plane-20260714
stash@{2}: On backup/pre-three-track-baseline-20260624: safety-leftovers-pre-three-track-baseline-20260624
```

## Baseline Candidate Discovery

- Candidate JSON: `outputs/pipeline_baseline_discovery_20260714/candidates.json`.
- Candidate report: `outputs/pipeline_baseline_discovery_20260714/candidate_report.md`.
- `deterministic_english_mock_p5_6_coordinate_v2`: `deterministic`, recommendation `selected_for_deterministic_baseline`, completeness `3/4`, input exists `True`.
- `live_math_full_handout_concurrent_20260709`: `live_model_reference`, recommendation `selected_for_live_reference`, completeness `4/4`, input exists `True`.
- `live_english_full_handout_concurrent_20260709`: `live_model_reference`, recommendation `selected_for_live_reference`, completeness `4/4`, input exists `True`.
- `live_biology_edge_crosspage_20260709`: `live_model_reference`, recommendation `selected_as_edge_candidate_not_hard_gate`, completeness `4/4`, input exists `True`.

## Frozen Baseline

- Baseline ID: `control_plane_20260714_v01`.
- Baseline manifest: `outputs/pipeline_baseline_snapshot/control_plane_20260714_v01/baseline_manifest.json`.
- Artifact hashes: `outputs/pipeline_baseline_snapshot/control_plane_20260714_v01/artifact_hashes.json`.
- Deterministic baseline count: `1`.
- Live model references count: `3`.
- Deterministic limitation: selected mock candidate lacks `review_repair_pool.json`; it is a minimal hard-gate baseline, not full PDF production evidence.
- Live references are existing artifacts only and are not strict CI hash gates.

## Control Plane

Implemented files:

- `config/pipeline_registry.yaml`
- `config/pipeline_feature_flags.yaml`
- `tools/validate_pipeline_registry.py`
- `tools/pipeline_run_context.py`
- `tests/test_pipeline_registry.py`
- `docs/pipeline_maintenance_and_isolation.md`

Registry pipeline count: `2`. Registered pipelines: `split_v03, runtime_backend`.
Feature flag count: `6`. All defaults are false: `True`.

## Actually Run

- `python tools/validate_pipeline_registry.py --json`: exit `0`.
- `python tests/test_pipeline_registry.py`: exit `0`.
- Overall test passed: `True`.
- Test result files: `outputs/pipeline_control_plane_validation_20260714/test_results.json` and `test_results.md`.

## Not Run

- No split_v03 rerun.
- No Semantic Role Shadow run.
- No DOCX Native run.
- No English Text-first run.
- No paid model call.
- No baseline rerun, no non-interference rerun, no output ownership gate, no Semantic Shadow sidecar gate.

## Risks And Limits

- The registry is a skeleton and is not wired into existing runtime/pipeline entrypoints.
- Output ownership is declared but not enforced in this round.
- Deterministic baseline is partial; it is enough for first control-plane hash anchoring, not enough for full pipeline non-interference certification.
- Semantic Role Adapter, DOCX Native, and English Text-first are not registered as implemented pipelines on this branch because their code/config is absent from `validation/backend-runtime-20260706`.
- Late business files were stashed to keep the control-plane branch clean; recover using `git stash show -p stash@{0}` or apply the stash after switching to the intended branch.
- During final verification, `config/pipeline_registry.yaml` was repeatedly modified by a late/parallel DOCX writer to add an unvalidated `docx_native_ingest_v01` entry. Each occurrence was copied into `outputs/pipeline_isolation_safety_20260714/` and stashed with a narrow pathspec. The committed registry intentionally contains only the two pipelines whose entrypoints and configs exist on this branch.

## Final Verification After Repollution Cleanup

- `python tools/validate_pipeline_registry.py --json`: exit `0`, `pipeline_count=2`, `error_count=0`.
- `python tests/test_pipeline_registry.py`: exit `0`, `Ran 3 tests`, `OK`.
- `git status --short --branch`: clean on `chore/pipeline-isolation-control-plane`.
- Latest repollution stash at final verification time: `stash@{0}: safety-final-repollution-registry-docx-20260714`.

## Git Status At Report Time

```text
## chore/pipeline-isolation-control-plane
?? config/pipeline_feature_flags.yaml
?? config/pipeline_registry.yaml
?? docs/pipeline_maintenance_and_isolation.md
?? docs/reports/pipeline_isolation_audit_20260714.md
?? tests/test_pipeline_registry.py
?? tools/pipeline_run_context.py
?? tools/validate_pipeline_registry.py
```

## Current Conclusion

`PIPELINE_CONTROL_PLANE_BASELINE_READY`
