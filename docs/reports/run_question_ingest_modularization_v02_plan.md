# run_question_ingest_skill.py Modularization v02 Plan

Status: not implemented in Phase 2A.

## Current Decision

`tools/run_question_ingest_skill.py` was intentionally not migrated in Phase 2A. It should remain a separate Phase 2B or v02 slice because it touches broader ingest orchestration, output packaging, and runtime-facing contracts.

## Proposed Entry Criteria

- Semantic Role Eval Phase 2A remains green after external review.
- Golden Master method is reused for every old CLI entry.
- DOCX and English migrations are either complete or explicitly frozen.

## Proposed Scope

- Preserve old CLI path and arguments.
- Capture pre-migration Golden outputs on portable fixtures.
- Split orchestration, artifact writing, status policy, and runtime-facing export contracts.
- Do not add Runtime/Postgres writes by default.
- Do not change prompt content, model strategy, or output schema in the same commit.
