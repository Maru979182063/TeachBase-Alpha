# TeachBase Java Shell Contract v0.1

This contract is the next layer above the four protected final chains.

The UI and Java backend should treat the chains as durable task workers. The UI must not know internal node names, prompt files, or per-chain graph details. It sees uploads, tasks, statuses, question packages, review results, and exports.

## Boundary

- Four admitted chains: `doc_math`, `doc_english`, `pdf_math`, `pdf_english`
- Contract file: `config/java_shell_contract_v01.json`
- Python chains remain subprocess workers behind the Java shell.
- Contract validation does not call models, write databases, import Runtime, or read business secrets.

## Task Statuses

`queued`, `running`, `waiting_review`, `failed_retryable`, `failed_final`, `completed`

Every node must emit a checkpoint artifact. Retryable failures resume from the last successful checkpoint; non-retryable failures become `failed_final`.

## Required Tables

`source_files`, `tasks`, `node_runs`, `artifacts`, `questions`, `reviews`, `version_sources`

The Java layer owns task locks, heartbeats, timeout recovery, dedupe, retry budgets, and database writes. Python chain entrypoints should not write business tables directly by default.

## Next Build Step

Implement the Java service against this contract first as a dry-run worker shell: create tasks, acquire locks, emit heartbeats, transition statuses, and store artifacts without invoking model execution by default.
