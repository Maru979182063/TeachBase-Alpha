# Java Editor Backend Foundation

## Ownership Rule

The frontend owns interaction. The backend owns content assets, validation, versions, permissions, immutable snapshots and deterministic exports.

| Capability | Frontend ownership | Backend ownership |
|---|---|---|
| Formula editing | Input, cursor, selection, deletion and instant rendering | LaTeX/MathML source, validation, revisions and export rendering |
| Mind map | Node operations, drag, layout, zoom and instant rendering | Stable-node tree, revisions, permissions, blank annotations, snapshots and export |
| Student blanks | Selection UI and teacher/student preview | Versioned marks/ranges/node IDs and audience projection |
| Markdown | Fast preview | Canonical parse/normalization contract and export rendering |
| DOCX/PDF/PPTX | Editing preview | Immutable-snapshot rendering, archive and download |

Generated HTML, SVG, canvas pixels, KaTeX DOM and screenshots are never canonical content.

## Audited Prototype Contract

The current high-fidelity prototype proves these source structures:

- Tiptap JSON with `master-overrides-v1`.
- Three variants in the prototype's persisted array order: `basic`, `advanced` and `common`.
- Formula nodes: `inlineMath` and legacy `blockMath`, with `latex` and optional `mathml`.
- Mind-map nodes with stable IDs, text, child trees and `studentBlankNodeIds`.
- Text blanking through the `studentBlank` mark.
- Knowledge blanking through `studentBlankRanges`.
- Question and knowledge references pinned to revision IDs.
- Teacher/student preview, preview confirmation and export snapshot intent.

The audit also found browser-local storage, handwritten Markdown parsing, suppressed formula errors, client-generated IDs, base64 images, dual Markdown/HTML fields and no optimistic concurrency. Machine-readable evidence is in `docs/reports/editor_backend_contract_audit_20260831.json`.

## Implemented Persistence

Flyway V002 creates eight tables:

| Boundary | Tables |
|---|---|
| Editor identity and variants | `editor_document`, `editor_variant` |
| Mutable head and immutable history | `editor_draft`, `editor_revision` |
| Confirmation and frozen content | `editor_preview_confirmation`, `editor_snapshot` |
| Rendering lineage and output link | `export_request`, `export_file` |

Every document starts with the three variants and revision 1. Saving a draft requires `expectedRevisionNo`; PostgreSQL row locking allows one concurrent winner and returns `409 editor_revision_conflict` to a stale writer.

Snapshot confirmation pins document, revision, variant and audience. The backend selects the full variant override when present or applies the prototype-compatible `targetLayers` projection to the master document. It then freezes the projected Tiptap document with a deterministic SHA-256. The frontend cannot submit a replacement projected document. An export request can only reference a snapshot in the same workspace and is idempotent within that workspace.

## Structured Content Validation

Content schema version 1 currently enforces:

- Tiptap `doc` root and bounded node/depth limits.
- Exactly three version override entries.
- Formula LaTeX presence and size limits.
- Mind-map stable and unique node IDs, bounded tree size/depth and valid blank-node references.
- The mind-map root cannot be a student blank.
- No base64 image content or machine absolute image path.
- Canonical object-key ordering before content hashing.

Legacy `override*Html` attributes are accepted during prototype migration so current drafts are not destroyed. They are compatibility projections, not the render source; the backend renderer must prefer structured nodes and Markdown/LaTeX fields.

Compatibility is retained for prototype attributes that encode blank ID arrays as JSON strings. A later schema migration may normalize those attributes to native arrays after the frontend adapter is ready.

## Markdown And Formula Rendering

Markdown-to-formula conversion is a backend responsibility for persisted and exported content. The frontend may produce an immediate preview, but that preview is not authoritative.

The backend render pipeline is now:

1. Parse Markdown and custom inline/block math into a versioned intermediate document AST.
2. Resolve images and other media through registered file/version identities.
3. Preserve LaTeX math nodes without rewriting mathematical meaning.
4. Apply variant and teacher/student projections from an immutable editor snapshot.
5. Render HTML preview, DOCX formula objects and PDF from the same intermediate representation.
6. Record render contract version, renderer profile, concrete engine version and output file version.

V002 records `render_contract_version`, `renderer_profile`, `renderer_version` and structured output options on every export request. The initial profile is `teachbase-document-v1`. V003 adds the execution lease, heartbeat, attempts, retry state, versioned render-source envelope and output storage key.

The concrete execution stack is implemented and pinned:

- `TiptapMarkdownAdapter` converts the immutable snapshot into audience-specific Pandoc Markdown under adapter contract `tiptap-pandoc-v1`.
- Pandoc 3.11 parses Markdown and LaTeX math into its native JSON AST. The stored envelope has `schemaVersion: 1`, the adapter version, audience and `pandocAst` including Pandoc's own API version.
- The same AST produces server HTML with MathML, DOCX with native OMML formula objects and Typst source for PDF.
- Typst 0.15.1 produces PDF; PDFBox 3.0.8 re-opens every PDF and requires at least one page with extractable text before publication.
- Generated bytes are hashed, moved atomically in the target directory and then registered in `file_version` and `export_file`.

The bootstrap script downloads official Windows/Linux x64 archives into an ignored tool cache and checks pinned SHA-256 values. Production images may install the same versions directly and set executable paths through environment variables.

Current render limitations are explicit: question references placed through the Java API are hydrated before snapshot creation, while unknown legacy question references and unresolved knowledge references fail closed. Registered image bytes still need a storage resolver, and mind maps currently export as a deterministic hierarchy rather than their eventual graphical layout. PPTX admission is disabled until a real writer exists.

## Worker Execution

V003 adds `export_attempt` and extends `export_request` with attempt counts, availability, worker identity, lease timestamps, render-source metadata and the portable output key.

- Workers claim with PostgreSQL row locks and `SKIP LOCKED`, so multiple Java instances can drain one queue without double execution.
- Heartbeats extend a bounded lease. An expired lease marks the old attempt `abandoned` and either retries or closes as `failed_final`.
- Failures are structured and never create `export_file` rows.
- Each attempt is immutable execution evidence with worker, renderer, source hash, output hash and terminal error.
- Temporary output names are unique and share the final directory. Exceptions clean them immediately; a conservative startup/periodic sweep removes only stale renderer-owned names older than both lease and process-timeout safety windows.

## API Surface

- `POST /api/v1/editor/documents`: create document, variants and revision 1.
- `GET /api/v1/editor/documents/{id}/draft`: read the current draft and ETag.
- `PUT /api/v1/editor/documents/{id}/draft`: validate and save the next immutable revision.
- `POST /api/v1/editor/documents/{id}/snapshots`: confirm and freeze one variant/audience projection.
- `POST /api/v1/editor/documents/{id}/question-references`: place approved question revisions in one editor revision.
- `POST /api/v1/exports`: create an idempotent snapshot-bound export request.
- `GET /api/v1/exports/{id}`: read queue/attempt status, structured failure and generated file metadata.

Accepted formats are currently `docx` and `pdf` only.

## Remaining Work

- Project knowledge and file references into typed FK-backed tables after those domains exist.
- Replace prototype base64 insertion with file upload/registration adapters.
- Resolve registered image bytes into render-local media without exposing machine paths.
- Add a graphical mind-map export adapter while retaining the stable tree as canonical source.
- Add production authentication and authorization policies beyond active workspace membership.
- Move generated output from local storage to the production object-storage adapter without changing portable keys.

Machine-readable execution evidence is in `docs/reports/document_renderer_live_gate_20260831.json`.
