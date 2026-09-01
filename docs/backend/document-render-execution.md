# Document Render Execution

## Boundary

Java owns queue admission, worker coordination, retries, source validation, artifact publication, database lineage and auditing. Pandoc and Typst are replaceable renderer adapters controlled by Java; neither owns business state.

The frontend remains responsible for editing interactions and immediate preview. A browser-rendered DOM is never persisted as canonical content.

## Data Flow

1. The frontend confirms a document revision, variant and audience.
2. Java freezes the backend-projected Tiptap document in `editor_snapshot`.
3. `POST /api/v1/exports` inserts one idempotent `export_request`.
4. A worker claims the request with a PostgreSQL lease and creates `export_attempt`.
5. `tiptap-pandoc-v1` projects teacher/student blanks, formula nodes, Markdown fields and the stable mind-map tree.
6. Pandoc parses that source into a versioned JSON AST.
7. Pandoc emits native DOCX/OMML, or Pandoc plus Typst emits PDF. The HTML verification writer emits MathML from the same AST.
8. Java validates the container, PDF page/text readability, byte count and SHA-256.
9. A unique same-directory temporary file is atomically replaced into the portable export key.
10. One transaction registers `file_version`, links `export_file`, completes the request and records audit evidence.

The frontend polls `GET /api/v1/exports/{id}`. It receives the bounded state, attempt counters, structured error and, after completion, the portable storage key, media type, size and SHA-256. It never reads queue tables directly.

## State Machine

`queued -> running -> completed`

Retryable failure uses `running -> failed_retryable -> running`. Exhaustion or a deterministic source violation uses `running -> failed_final`. A lost worker leaves an expired lease; the next worker marks that attempt `abandoned` before reclaiming the request.

Every transition checks request ID, worker ID and attempt number. A worker that has lost its lease cannot publish a late completion.

## Runtime Configuration

- `TEACHBASE_RENDER_ENABLED`
- `TEACHBASE_RENDER_WORKER_ID`
- `TEACHBASE_RENDER_PANDOC_PATH`
- `TEACHBASE_RENDER_TYPST_PATH`
- `TEACHBASE_STORAGE_ROOT`
- `TEACHBASE_RENDER_POLL_DELAY`
- `TEACHBASE_RENDER_LEASE_DURATION`
- `TEACHBASE_RENDER_PROCESS_TIMEOUT`
- `TEACHBASE_RENDER_TEMP_SWEEP_DELAY`

Rendering is disabled by default. A deployment must set `TEACHBASE_RENDER_ENABLED=true`; startup then verifies both pinned executables before any request can be claimed. Missing tools fail service startup instead of consuming and misclassifying queued business work.

Executable paths and the storage root are runtime configuration only. Database contracts and test reports contain portable storage keys, not machine paths.

## Verification

Run `npm run test:document-renderer`.

The gate starts disposable PostgreSQL and two independent Java servers, submits concurrent and idempotent work, recovers an expired lease, generates DOCX/PDF, opens DOCX XML to confirm native formula objects, parses PDF content, checks HTML MathML, verifies hashes and proves deterministic bad input creates neither file metadata nor residual temporary files.

Result: `docs/reports/document_renderer_live_gate_20260831.json`.
