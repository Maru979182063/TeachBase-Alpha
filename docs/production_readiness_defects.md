# Production Readiness Defects

Updated: 2026-06-24

## Open Blocking Policy Gate

### POLICY-001 Validation baseline must not claim production readiness yet

- Status: `open`
- Gate: `POLICY-001`
- Current behavior:
  - runtime health reports `releaseChannel = validation_only`
  - runtime health reports `architectureMode = state_replay_bridge`
  - `npm run test:production-readiness` ends in `NOT_READY`
- Why it is blocking:
  - this repository has a validated three-track baseline
  - it has not yet crossed the agreed production architecture boundary
  - declaring `READY` in the current state would be misleading
- Expected closure condition:
  - a later round explicitly removes the validation-only bridge positioning
  - the production readiness gate is re-reviewed against that new architecture target

## Closed Item

### S1-ARCH-001 Postgres snapshot was previously treated as a primary source risk

- Status: `closed`
- Current result:
  - `ARCH-001` passes
  - normalized Postgres tables are the active business source of truth
  - snapshot behavior is no longer allowed to control the formal business read path

## Current Blocking Count

- `S0 = 0`
- `S1 = 0` within the reviewed validation-baseline scope
- `Policy gates = 1`

## Non-Blocking Follow-Ups

The following are important, but they are not being represented as additional blocking defects in this round:

- decommission the deprecated `8792` compatibility forwarder after reference cleanup is complete
- decide whether to keep the state replay bridge or move to a stricter production architecture split
- perform larger-scale soak and capacity validation after the production boundary is agreed
- validate the upstream `PDF/DOCX -> OCR/model decomposition -> LessonDraftBundle` chain separately from the backend baseline
