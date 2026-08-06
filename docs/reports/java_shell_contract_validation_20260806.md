# Java Shell Contract Validation 2026-08-06

Status: `pass`
Contract: `config/java_shell_contract_v01.json`

## Checks

- `pass` `schema_and_workspace_contract_match`
- `pass` `four_protected_chain_ids_declared`
- `pass` `task_state_machine_declares_required_statuses`
- `pass` `task_state_machine_transitions_are_closed`
- `pass` `checkpoint_and_failure_contract_are_structured`
- `pass` `database_contract_declares_required_tables`
- `pass` `worker_contract_has_lock_heartbeat_timeout_retry_and_dedupe`
- `pass` `ui_contract_hides_internal_nodes`
- `pass` `contract_validation_has_no_runtime_side_effects`
- `pass` `contract_contains_no_absolute_paths`
