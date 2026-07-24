# Docs

This directory keeps non-source project materials out of the repository root.

- Runtime API note: the only official local backend entry is `http://127.0.0.1:8790`.
- Compatibility note: `8792` is deprecated and only kept as a forwarding shim.
- Validation boundary: the current backend baseline starts from `LessonDraftBundle`.
- Validation boundary: it does not prove OCR/PDF-to-`LessonDraftBundle` accuracy or end-to-end model import quality.
- `planning/`: project proposals, implementation plans, and architecture notes.
- `reports/`: research summaries, status reports, and analysis writeups.
- `previews/`: standalone HTML previews and single-file demo pages.
- `db/`: database draft materials that are not active migrations.
- `diagrams/`: exported workflow and architecture visuals.
