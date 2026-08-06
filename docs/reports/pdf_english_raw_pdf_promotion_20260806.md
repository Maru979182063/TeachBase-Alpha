# PDF English Raw PDF Promotion 2026-08-06

Status: `pass`
Promotion level: `raw_pdf_ingress_and_manifest_gate`
Java shell admission: `true`

## Checks

- `pass` `raw_pdf_sample_exists`
- `pass` `raw_pdf_preflight_accepts_english_profile`
- `pass` `raw_pdf_pages_rendered`
- `pass` `raw_pdf_text_blocks_extracted`
- `pass` `graph_first_active_manifest_valid`
- `pass` `no_model_db_runtime_or_secret_side_effects`

This gate does not call a model, write a database, import Runtime, or read business secrets.
