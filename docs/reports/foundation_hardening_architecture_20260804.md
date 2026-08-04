# Foundation Hardening Architecture 2026-08-04

## Scope

This hardening layer is an execution safety shell around existing final-chain Python tools. It does not change prompts, models, routes, roles, thresholds, split policy, transcription policy, refinement policy, or review policy.

## Current Python Shell

- `teachbase.infrastructure.artifact_store` owns atomic artifact writes for package-facing code and hardened legacy entry points.
- `teachbase.infrastructure.model_call_guard` owns retry and checkpoint evidence for model calls.
- DOCX Native repair and PDF visual transcription call the guard as an outer shell while preserving their existing prompt construction, request payload shape, model name, response parsing, and artifact contract.
- Checkpoints are sidecar artifacts. A successful checkpoint can skip a duplicate model call only when the operation id matches the same node, model, prompt, and relevant image identity.

## Java Control Plane Boundary

Java is a good future control plane for:

- API service and CLI service lifecycle.
- Job scheduling, queue consumption, and worker orchestration.
- Long-running task state machines.
- User, tenant, permission, and account boundaries.
- Database transactions and observability.
- Reading pipeline registry metadata and launching Python workers through stable contracts.

Java should not rewrite or silently reinterpret final-chain internals during this phase. The contract between Java and Python should stay artifact-based:

- input manifest JSON;
- output summary/report JSON;
- artifact directory layout;
- exit code contract;
- checkpoint/resume sidecar contract;
- no business secret exposure in generated reports.

## Non-Negotiable Red Lines

- Do not modify prompt text or prompt templates as part of foundation hardening.
- Do not change model names, provider selection, temperature, route, role, threshold, split/refine strategy, or fallback policy.
- Do not introduce Runtime or database writes into foundation gates.
- Do not clean, archive, or delete final-chain-adjacent files until the protected-chain registry and compartment report agree on the scope.

## Operational Gates

- `npm run test:foundation-hardening` verifies artifact atomicity, model retry/checkpoint guard behavior, DOCX model checkpoint integration, PDF visual model checkpoint integration, and architecture boundaries.
- `npm run audit:worktree-compartments` classifies the current dirty worktree into final-chain registry, foundation hardening, validation report refresh, mixed control files, and unclassified records.
