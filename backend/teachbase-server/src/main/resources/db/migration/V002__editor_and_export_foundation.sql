-- Aggregate root. current_revision_no is advanced under a row lock so concurrent
-- browser saves cannot silently overwrite each other.
create table teachbase_app.editor_document (
  editor_document_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  document_kind varchar(40) not null,
  title varchar(512) not null,
  status varchar(24) not null default 'draft',
  current_revision_no bigint not null default 0,
  created_by uuid not null,
  updated_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_editor_document_workspace unique (editor_document_id, workspace_id),
  constraint fk_editor_document_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_editor_document_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_document_kind check (document_kind in ('synchronized_handout', 'independent_question_pack')),
  constraint ck_editor_document_status check (status in ('draft', 'active', 'archived')),
  constraint ck_editor_document_revision check (current_revision_no >= 0),
  constraint ck_editor_document_title check (length(trim(title)) > 0)
);

create index idx_editor_document_workspace on teachbase_app.editor_document(workspace_id, updated_at desc);

-- Stable product variants; interactive layout remains a frontend concern.
create table teachbase_app.editor_variant (
  editor_document_id uuid not null,
  workspace_id uuid not null,
  variant_key varchar(24) not null,
  display_name varchar(80) not null,
  sort_order smallint not null,
  created_at timestamptz not null default now(),
  primary key (editor_document_id, variant_key),
  constraint uq_editor_variant_workspace unique (editor_document_id, workspace_id, variant_key),
  constraint uq_editor_variant_order unique (editor_document_id, sort_order),
  constraint fk_editor_variant_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint ck_editor_variant_key check (variant_key in ('basic', 'advanced', 'common')),
  constraint ck_editor_variant_order check (sort_order between 0 and 2),
  constraint ck_editor_variant_name check (length(trim(display_name)) > 0)
);

-- Immutable structured revisions. Canonical JSON survives editor-library changes.
create table teachbase_app.editor_revision (
  editor_revision_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  revision_no bigint not null,
  editor_model varchar(40) not null,
  schema_version integer not null,
  master_doc_json jsonb not null,
  version_overrides_json jsonb not null,
  content_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_editor_revision_number unique (editor_document_id, revision_no),
  constraint uq_editor_revision_scope unique (editor_revision_id, editor_document_id, workspace_id),
  constraint uq_editor_revision_draft_scope unique (editor_revision_id, editor_document_id, workspace_id, revision_no),
  constraint fk_editor_revision_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_editor_revision_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_revision_number check (revision_no > 0),
  constraint ck_editor_revision_model check (editor_model = 'master-overrides-v1'),
  constraint ck_editor_revision_schema check (schema_version = 1),
  constraint ck_editor_revision_master check (jsonb_typeof(master_doc_json) = 'object'),
  constraint ck_editor_revision_overrides check (
    jsonb_typeof(version_overrides_json) = 'array'
    and jsonb_array_length(version_overrides_json) = 3
  ),
  constraint ck_editor_revision_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

create index idx_editor_revision_document on teachbase_app.editor_revision(editor_document_id, revision_no desc);

-- Mutable pointer to the latest immutable revision; content is never updated in place.
create table teachbase_app.editor_draft (
  editor_document_id uuid primary key,
  workspace_id uuid not null,
  editor_revision_id uuid not null,
  revision_no bigint not null,
  updated_by uuid not null,
  updated_at timestamptz not null default now(),
  constraint fk_editor_draft_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_editor_draft_revision foreign key (editor_revision_id, editor_document_id, workspace_id, revision_no)
    references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id, revision_no),
  constraint fk_editor_draft_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_draft_revision check (revision_no > 0)
);

-- Exact revision/variant/audience approved before freezing an exportable snapshot.
create table teachbase_app.editor_preview_confirmation (
  editor_preview_confirmation_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  editor_revision_id uuid not null,
  variant_key varchar(24) not null,
  audience varchar(16) not null,
  confirmed_by uuid not null,
  confirmed_at timestamptz not null default now(),
  constraint uq_editor_confirmation_scope unique (
    editor_preview_confirmation_id, editor_document_id, workspace_id,
    editor_revision_id, variant_key, audience
  ),
  constraint fk_editor_confirmation_revision foreign key (editor_revision_id, editor_document_id, workspace_id)
    references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_editor_confirmation_variant foreign key (editor_document_id, workspace_id, variant_key)
    references teachbase_app.editor_variant(editor_document_id, workspace_id, variant_key),
  constraint fk_editor_confirmation_actor foreign key (workspace_id, confirmed_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_confirmation_audience check (audience in ('teacher', 'student'))
);

-- Self-contained export boundary, independent of later draft mutations.
create table teachbase_app.editor_snapshot (
  editor_snapshot_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  editor_revision_id uuid not null,
  editor_preview_confirmation_id uuid not null,
  variant_key varchar(24) not null,
  audience varchar(16) not null,
  schema_version integer not null,
  frozen_content_json jsonb not null,
  content_hash char(64) not null,
  created_at timestamptz not null default now(),
  constraint uq_editor_snapshot_workspace unique (editor_snapshot_id, workspace_id),
  constraint uq_editor_snapshot_confirmation unique (editor_preview_confirmation_id),
  constraint fk_editor_snapshot_confirmation foreign key (
    editor_preview_confirmation_id, editor_document_id, workspace_id,
    editor_revision_id, variant_key, audience
  ) references teachbase_app.editor_preview_confirmation(
    editor_preview_confirmation_id, editor_document_id, workspace_id,
    editor_revision_id, variant_key, audience
  ),
  constraint ck_editor_snapshot_schema check (schema_version = 1),
  constraint ck_editor_snapshot_content check (jsonb_typeof(frozen_content_json) = 'object'),
  constraint ck_editor_snapshot_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

create index idx_editor_snapshot_document on teachbase_app.editor_snapshot(editor_document_id, created_at desc);

-- Durable render request. workspace-scoped idempotency makes API retries safe.
create table teachbase_app.export_request (
  export_request_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  editor_snapshot_id uuid not null,
  format varchar(16) not null,
  render_contract_version integer not null default 1,
  renderer_profile varchar(80) not null default 'teachbase-document-v1',
  renderer_version varchar(120),
  output_options_json jsonb not null default '{}'::jsonb,
  status varchar(24) not null default 'queued',
  idempotency_key varchar(128) not null,
  retry_of_export_request_id uuid,
  requested_by uuid not null,
  requested_at timestamptz not null default now(),
  completed_at timestamptz,
  error_json jsonb,
  constraint uq_export_request_workspace unique (export_request_id, workspace_id),
  constraint uq_export_request_idempotency unique (workspace_id, idempotency_key),
  constraint fk_export_request_snapshot foreign key (editor_snapshot_id, workspace_id)
    references teachbase_app.editor_snapshot(editor_snapshot_id, workspace_id),
  constraint fk_export_request_retry foreign key (retry_of_export_request_id, workspace_id)
    references teachbase_app.export_request(export_request_id, workspace_id),
  constraint fk_export_request_actor foreign key (workspace_id, requested_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_export_request_format check (format in ('docx', 'pdf', 'pptx')),
  constraint ck_export_render_contract check (render_contract_version = 1),
  constraint ck_export_renderer_profile check (length(trim(renderer_profile)) > 0),
  constraint ck_export_output_options check (jsonb_typeof(output_options_json) = 'object'),
  constraint ck_export_request_status check (status in ('queued', 'running', 'completed', 'failed', 'cancelled')),
  constraint ck_export_request_idempotency check (length(trim(idempotency_key)) > 0)
);

create index idx_export_request_queue on teachbase_app.export_request(status, requested_at);

-- One successful render result per request; file_version owns bytes and checksum.
create table teachbase_app.export_file (
  export_file_id uuid primary key,
  export_request_id uuid not null,
  workspace_id uuid not null,
  file_version_id uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_export_file_request unique (export_request_id),
  constraint fk_export_file_request foreign key (export_request_id, workspace_id)
    references teachbase_app.export_request(export_request_id, workspace_id),
  constraint fk_export_file_version foreign key (file_version_id, workspace_id)
    references teachbase_app.file_version(file_version_id, workspace_id)
);
