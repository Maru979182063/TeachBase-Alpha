-- TeachBase persistence foundation.
-- Every business aggregate is scoped by workspace_id. Composite foreign keys are
-- deliberate: they prevent cross-tenant references even if application checks fail.
create schema if not exists teachbase_app;

-- Top-level tenant and ownership boundary.
create table teachbase_app.workspace (
  workspace_id uuid primary key,
  slug varchar(80) not null,
  display_name varchar(160) not null,
  status varchar(24) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_workspace_slug unique (slug),
  constraint ck_workspace_status check (status in ('active', 'suspended', 'archived'))
);

-- Human identity. Authentication credentials intentionally live outside this schema.
create table teachbase_app.app_user (
  user_id uuid primary key,
  email varchar(320) not null,
  display_name varchar(160) not null,
  status varchar(24) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_app_user_email unique (email),
  constraint ck_app_user_status check (status in ('active', 'suspended', 'archived'))
);

-- Authorization anchor used by later created_by and updated_by foreign keys.
create table teachbase_app.workspace_member (
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  user_id uuid not null references teachbase_app.app_user(user_id),
  member_role varchar(24) not null,
  status varchar(24) not null default 'active',
  joined_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id),
  constraint ck_workspace_member_role check (member_role in ('owner', 'admin', 'editor', 'reviewer', 'viewer')),
  constraint ck_workspace_member_status check (status in ('active', 'suspended', 'removed'))
);

-- Logical file identity; immutable byte metadata belongs to file_version.
create table teachbase_app.file_asset (
  file_asset_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  original_filename varchar(512) not null,
  status varchar(24) not null default 'active',
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ck_file_asset_filename check (
    length(trim(original_filename)) > 0
    and position('/' in original_filename) = 0
    and position(chr(92) in original_filename) = 0
  ),
  constraint ck_file_asset_status check (status in ('active', 'archived', 'quarantined')),
  constraint uq_file_asset_workspace unique (file_asset_id, workspace_id),
  constraint fk_file_asset_creator_member foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id)
);

-- storage_key is portable and relative. Absolute machine paths are rejected.
create table teachbase_app.file_version (
  file_version_id uuid primary key,
  file_asset_id uuid not null,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  version_no integer not null,
  storage_provider varchar(24) not null,
  storage_key varchar(1024) not null,
  media_type varchar(255) not null,
  size_bytes bigint not null,
  sha256 char(64) not null,
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint uq_file_version_asset_version unique (file_asset_id, version_no),
  constraint uq_file_version_workspace unique (file_version_id, workspace_id),
  constraint uq_file_version_workspace_sha256 unique (workspace_id, sha256),
  constraint fk_file_version_asset_workspace foreign key (file_asset_id, workspace_id)
    references teachbase_app.file_asset(file_asset_id, workspace_id),
  constraint fk_file_version_creator_member foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_file_version_no check (version_no > 0),
  constraint ck_file_version_provider check (storage_provider in ('local', 'object_storage')),
  constraint ck_file_version_storage_key check (
    length(trim(storage_key)) > 0
    and left(storage_key, 1) <> '/'
    and position(':' in storage_key) = 0
    and position(chr(92) in storage_key) = 0
    and storage_key not like '../%'
    and storage_key not like '%/../%'
    and storage_key <> '..'
  ),
  constraint ck_file_version_size check (size_bytes >= 0),
  constraint ck_file_version_sha256 check (length(sha256) = 64 and sha256 = lower(sha256))
);

create index idx_file_asset_workspace on teachbase_app.file_asset(workspace_id, created_at desc);
create index idx_file_version_asset on teachbase_app.file_version(file_asset_id, version_no desc);

-- Registered teaching source. Pipeline internals remain optional metadata.
create table teachbase_app.source_document (
  source_document_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  file_version_id uuid not null,
  source_type varchar(32) not null,
  subject varchar(64),
  stage varchar(64),
  grade varchar(64),
  title varchar(512),
  status varchar(24) not null default 'registered',
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_source_document_file_version unique (file_version_id),
  constraint fk_source_document_file_workspace foreign key (file_version_id, workspace_id)
    references teachbase_app.file_version(file_version_id, workspace_id),
  constraint ck_source_document_type check (source_type in ('docx', 'pdf', 'image', 'structured_import', 'other')),
  constraint ck_source_document_status check (status in ('registered', 'processing', 'ready', 'failed', 'archived'))
);

-- Addressable source area such as a PDF block, formula, image, or DOCX item.
create table teachbase_app.source_region (
  source_region_id uuid primary key,
  source_document_id uuid not null references teachbase_app.source_document(source_document_id),
  region_type varchar(32) not null,
  page_no integer,
  order_index integer,
  bbox_json jsonb,
  extracted_text text,
  source_ref_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint ck_source_region_page check (page_no is null or page_no > 0),
  constraint ck_source_region_order check (order_index is null or order_index >= 0),
  constraint ck_source_region_type check (region_type in ('page', 'block', 'question', 'image', 'formula', 'table', 'other'))
);

create index idx_source_region_document on teachbase_app.source_region(source_document_id, page_no, order_index);

-- Append-only business audit trail; this is not an application log replacement.
create table teachbase_app.audit_event (
  audit_event_id uuid primary key,
  workspace_id uuid references teachbase_app.workspace(workspace_id),
  actor_user_id uuid,
  event_type varchar(120) not null,
  aggregate_type varchar(80) not null,
  aggregate_id uuid not null,
  payload_json jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  constraint fk_audit_actor_member foreign key (workspace_id, actor_user_id)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_audit_actor_workspace check (actor_user_id is null or workspace_id is not null)
);

create index idx_audit_event_workspace_time on teachbase_app.audit_event(workspace_id, occurred_at desc);
create index idx_audit_event_aggregate on teachbase_app.audit_event(aggregate_type, aggregate_id, occurred_at);

-- Restartable migration ledger for Python-era data imports.
create table teachbase_app.legacy_import_batch (
  legacy_import_batch_id uuid primary key,
  source_schema varchar(128) not null,
  source_fingerprint char(64) not null,
  status varchar(24) not null,
  summary_json jsonb not null default '{}'::jsonb,
  error_json jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint uq_legacy_import_fingerprint unique (source_schema, source_fingerprint),
  constraint ck_legacy_import_status check (status in ('running', 'completed', 'failed', 'rolled_back')),
  constraint ck_legacy_import_fingerprint check (length(source_fingerprint) = 64 and source_fingerprint = lower(source_fingerprint))
);

-- Stable old-to-new mapping kept outside domain tables to contain legacy coupling.
create table teachbase_app.legacy_id_map (
  legacy_import_batch_id uuid not null references teachbase_app.legacy_import_batch(legacy_import_batch_id),
  legacy_table varchar(128) not null,
  legacy_id varchar(512) not null,
  target_table varchar(128) not null,
  target_id uuid not null,
  content_hash char(64),
  created_at timestamptz not null default now(),
  primary key (legacy_import_batch_id, legacy_table, legacy_id),
  constraint uq_legacy_id_map_target unique (legacy_import_batch_id, target_table, target_id),
  constraint ck_legacy_id_map_hash check (content_hash is null or (length(content_hash) = 64 and content_hash = lower(content_hash)))
);

create index idx_legacy_id_map_target on teachbase_app.legacy_id_map(target_table, target_id);
