# Final Chain Environment Contract 2026-08-04

Status: `pass`
Schema: `final_chain_environment_interaction_contract.v0.1`
Ready chains: `doc_math, doc_english, pdf_math, pdf_english`
Blocked chains: ``

## Filesystem

- `write_scope`: `outputs/`
- `read_scope`: `registered_relative_paths_only`

## Profiles

- `doc_math`: `ready`, gate `ready_for_control_plane`, required paths `3/3`
- `doc_english`: `ready`, gate `ready_for_control_plane`, required paths `3/3`
- `pdf_math`: `ready`, gate `ready_for_control_plane`, required paths `1/1`
- `pdf_english`: `ready`, gate `ready_for_control_plane`, required paths `1/1`

All paths are repository-relative contract paths; no local absolute path is reproducible input.
