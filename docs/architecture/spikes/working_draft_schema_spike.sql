-- Phase 0 隔离 spike：不得复制到 Flyway migration 后直接上线。
create schema if not exists teachbase_phase0_spike;

create table teachbase_phase0_spike.editor_working_draft (
  editor_document_id uuid primary key,
  workspace_id uuid not null,
  draft_version bigint not null default 1,
  based_on_editor_revision_id uuid,
  schema_version integer not null,
  master_doc_json jsonb not null,
  version_overrides_json jsonb not null,
  content_hash char(64) not null,
  updated_by uuid not null,
  updated_at timestamptz not null default now(),
  constraint uq_spike_working_draft_scope unique (editor_document_id, workspace_id),
  constraint fk_spike_working_draft_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_spike_working_draft_base_revision foreign key (
    based_on_editor_revision_id, editor_document_id, workspace_id)
    references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_spike_working_draft_actor foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_spike_working_draft_version check (draft_version > 0),
  constraint ck_spike_working_draft_schema check (schema_version > 0),
  constraint ck_spike_working_draft_master check (jsonb_typeof(master_doc_json) = 'object'),
  constraint ck_spike_working_draft_overrides check (
    jsonb_typeof(version_overrides_json) = 'array'
    and jsonb_array_length(version_overrides_json) = 3),
  constraint ck_spike_working_draft_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

create table teachbase_phase0_spike.editor_draft_checkpoint (
  editor_draft_checkpoint_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  draft_version bigint not null,
  checkpoint_kind varchar(32) not null,
  schema_version integer not null,
  master_doc_json jsonb not null,
  version_overrides_json jsonb not null,
  content_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  constraint uq_spike_checkpoint_version unique (editor_document_id, draft_version, checkpoint_kind),
  constraint fk_spike_checkpoint_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_spike_checkpoint_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_spike_checkpoint_version check (draft_version > 0),
  constraint ck_spike_checkpoint_kind check (
    checkpoint_kind in ('autosave', 'conflict_recovery', 'pre_transition')),
  constraint ck_spike_checkpoint_expiry check (expires_at > created_at),
  constraint ck_spike_checkpoint_master check (jsonb_typeof(master_doc_json) = 'object'),
  constraint ck_spike_checkpoint_overrides check (
    jsonb_typeof(version_overrides_json) = 'array'
    and jsonb_array_length(version_overrides_json) = 3),
  constraint ck_spike_checkpoint_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

create index idx_spike_checkpoint_cleanup
  on teachbase_phase0_spike.editor_draft_checkpoint(expires_at);
