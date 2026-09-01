-- Search, placement, and collection persistence for the ingestion boundary.
-- Chinese text needs trigram lookup because the default full-text parser does not
-- tokenize it reliably. tsvector remains useful for Latin text and exact terms.
create extension if not exists pg_trgm;

-- Stable question identity across review and correction revisions.
create table teachbase_app.question (
  question_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  external_key varchar(240) not null,
  source_system varchar(80) not null,
  source_key varchar(512) not null,
  status varchar(24) not null default 'active',
  current_revision_no bigint not null default 0,
  approved_revision_id uuid,
  created_by uuid not null,
  updated_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_question_workspace unique (question_id, workspace_id),
  constraint uq_question_external_key unique (workspace_id, external_key),
  constraint uq_question_source_key unique (workspace_id, source_system, source_key),
  constraint fk_question_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_question_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_status check (status in ('active', 'archived', 'quarantined')),
  constraint ck_question_external_key check (length(trim(external_key)) > 0),
  constraint ck_question_source check (length(trim(source_system)) > 0 and length(trim(source_key)) > 0),
  constraint ck_question_current_revision check (current_revision_no >= 0)
);

-- Immutable content revision. Scalars support filtering while structured content
-- and provenance stay lossless JSON for future schema evolution.
create table teachbase_app.question_revision (
  question_revision_id uuid primary key,
  question_id uuid not null,
  workspace_id uuid not null,
  revision_no bigint not null,
  review_status varchar(24) not null,
  subject varchar(80) not null,
  stage varchar(80) not null default '',
  grade varchar(80) not null default '',
  question_type varchar(80) not null,
  title varchar(512) not null default '',
  lesson varchar(512) not null default '',
  primary_knowledge_tag varchar(512) not null default '',
  secondary_knowledge_tags_json jsonb not null default '[]'::jsonb,
  difficulty_stars smallint,
  material_markdown text not null default '',
  stem_markdown text not null,
  options_json jsonb not null default '[]'::jsonb,
  answer_markdown text not null default '',
  analysis_markdown text not null default '',
  content_json jsonb not null,
  provenance_json jsonb not null default '{}'::jsonb,
  content_hash char(64) not null,
  approved_at timestamptz,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_question_revision_number unique (question_id, revision_no),
  constraint uq_question_revision_scope unique (question_revision_id, question_id, workspace_id),
  constraint uq_question_revision_workspace unique (question_revision_id, workspace_id),
  constraint uq_question_revision_hash unique (question_id, content_hash),
  constraint fk_question_revision_question foreign key (question_id, workspace_id)
    references teachbase_app.question(question_id, workspace_id),
  constraint fk_question_revision_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_revision_number check (revision_no > 0),
  constraint ck_question_revision_review check (review_status in ('unreviewed', 'pending_review', 'approved', 'rejected')),
  constraint ck_question_revision_subject check (length(trim(subject)) > 0),
  constraint ck_question_revision_type check (length(trim(question_type)) > 0),
  constraint ck_question_revision_stem check (length(trim(stem_markdown)) > 0),
  constraint ck_question_revision_options check (jsonb_typeof(options_json) = 'array'),
  constraint ck_question_revision_tags check (jsonb_typeof(secondary_knowledge_tags_json) = 'array'),
  constraint ck_question_revision_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_question_revision_provenance check (jsonb_typeof(provenance_json) = 'object'),
  constraint ck_question_revision_difficulty check (difficulty_stars is null or difficulty_stars between 1 and 5),
  constraint ck_question_revision_hash check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_question_revision_approval check (
    (review_status = 'approved' and approved_at is not null)
    or (review_status <> 'approved' and approved_at is null)
  )
);

-- Resolve the intentional cycle: revisions belong to a question, while the question
-- points at the one approved revision visible to production search.
alter table teachbase_app.question
  add constraint fk_question_approved_revision foreign key (approved_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id);

create index idx_question_workspace_status
  on teachbase_app.question(workspace_id, status, updated_at desc, question_id);
create index idx_question_revision_filters
  on teachbase_app.question_revision(workspace_id, review_status, subject, stage, grade, question_type, difficulty_stars);
-- Expression indexes are maintained by PostgreSQL and cannot drift from content.
-- jOOQ's open-source DDL simulator cannot parse PostgreSQL operator classes, so the
-- parser markers hide only these indexes from code generation. Flyway still executes
-- and verifies them against real PostgreSQL in the live gate.
-- [jooq ignore start]
create index idx_question_revision_search_vector
  on teachbase_app.question_revision using gin(to_tsvector('simple',
    coalesce(title, '') || ' ' || coalesce(subject, '') || ' ' || coalesce(stage, '') || ' '
    || coalesce(grade, '') || ' ' || coalesce(question_type, '') || ' ' || coalesce(lesson, '') || ' '
    || coalesce(primary_knowledge_tag, '') || ' ' || coalesce(material_markdown, '') || ' '
    || coalesce(stem_markdown, '') || ' ' || coalesce(answer_markdown, '') || ' ' || coalesce(analysis_markdown, '')
  ));
-- Trigram supports Chinese phrases and substring lookup.
create index idx_question_revision_search_trgm
  on teachbase_app.question_revision using gin(lower(
    coalesce(title, '') || ' ' || coalesce(subject, '') || ' ' || coalesce(stage, '') || ' '
    || coalesce(grade, '') || ' ' || coalesce(question_type, '') || ' ' || coalesce(lesson, '') || ' '
    || coalesce(primary_knowledge_tag, '') || ' ' || coalesce(material_markdown, '') || ' '
    || coalesce(stem_markdown, '') || ' ' || coalesce(answer_markdown, '') || ' ' || coalesce(analysis_markdown, '')
  ) gin_trgm_ops);
-- [jooq ignore stop]

-- Queryable provenance back to the original source document and optional region.
create table teachbase_app.question_source_link (
  question_source_link_id uuid primary key,
  question_id uuid not null,
  question_revision_id uuid not null,
  workspace_id uuid not null,
  source_document_id uuid,
  source_region_id uuid,
  source_label varchar(1024),
  source_page_start integer,
  source_page_end integer,
  source_ref_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_question_source_revision unique (question_revision_id),
  constraint fk_question_source_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_source_document foreign key (source_document_id)
    references teachbase_app.source_document(source_document_id),
  constraint fk_question_source_region foreign key (source_region_id)
    references teachbase_app.source_region(source_region_id),
  constraint ck_question_source_pages check (
    (source_page_start is null and source_page_end is null)
    or (source_page_start > 0 and source_page_end >= source_page_start)
  ),
  constraint ck_question_source_ref check (jsonb_typeof(source_ref_json) = 'object')
);

-- Composite-question, alternative, duplicate, and future pedagogical graph edges.
create table teachbase_app.question_relation (
  parent_question_id uuid not null,
  child_question_id uuid not null,
  workspace_id uuid not null,
  relation_type varchar(24) not null,
  sort_order integer not null,
  created_at timestamptz not null default now(),
  primary key (parent_question_id, child_question_id, relation_type),
  constraint uq_question_relation_order unique (parent_question_id, relation_type, sort_order),
  constraint fk_question_relation_parent foreign key (parent_question_id, workspace_id)
    references teachbase_app.question(question_id, workspace_id),
  constraint fk_question_relation_child foreign key (child_question_id, workspace_id)
    references teachbase_app.question(question_id, workspace_id),
  constraint ck_question_relation_type check (relation_type in ('child', 'variant', 'related')),
  constraint ck_question_relation_order check (sort_order >= 0),
  constraint ck_question_relation_distinct check (parent_question_id <> child_question_id)
);

-- Relational index of references embedded in editor JSON. Each row pins an immutable
-- question revision so an export cannot change after a later correction.
create table teachbase_app.editor_question_reference (
  editor_question_reference_id uuid primary key,
  editor_document_id uuid not null,
  editor_revision_id uuid not null,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  placement_key uuid not null,
  position_index integer not null,
  target_layers_json jsonb not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_editor_question_placement unique (editor_revision_id, placement_key),
  constraint fk_editor_question_editor_revision foreign key (editor_revision_id, editor_document_id, workspace_id)
    references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_editor_question_question_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_editor_question_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_question_position check (position_index >= 0),
  constraint ck_editor_question_layers check (jsonb_typeof(target_layers_json) = 'array')
);

create index idx_editor_question_usage
  on teachbase_app.editor_question_reference(workspace_id, question_id, created_at desc);

-- Question basket aggregate. draft_version is its optimistic-lock token.
create table teachbase_app.question_collection (
  question_collection_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  name varchar(512) not null,
  status varchar(24) not null default 'draft',
  draft_version bigint not null default 0,
  created_by uuid not null,
  updated_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_question_collection_workspace unique (question_collection_id, workspace_id),
  constraint fk_question_collection_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_question_collection_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_collection_name check (length(trim(name)) > 0),
  constraint ck_question_collection_status check (status in ('draft', 'active', 'archived')),
  constraint ck_question_collection_version check (draft_version >= 0)
);

-- Current ordered basket projection, replaced atomically during a batch save.
create table teachbase_app.question_collection_item (
  question_collection_id uuid not null,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  position_index integer not null,
  settings_json jsonb not null default '{}'::jsonb,
  added_by uuid not null,
  added_at timestamptz not null default now(),
  primary key (question_collection_id, question_id),
  constraint uq_question_collection_position unique (question_collection_id, position_index),
  constraint fk_question_collection_item_collection foreign key (question_collection_id, workspace_id)
    references teachbase_app.question_collection(question_collection_id, workspace_id),
  constraint fk_question_collection_item_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_collection_item_actor foreign key (workspace_id, added_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_collection_item_position check (position_index >= 0),
  constraint ck_question_collection_item_settings check (jsonb_typeof(settings_json) = 'object')
);

-- Recoverable draft checkpoints. Autosaves may expire; manual saves do not.
create table teachbase_app.question_collection_checkpoint (
  question_collection_checkpoint_id uuid primary key,
  question_collection_id uuid not null,
  workspace_id uuid not null,
  draft_version bigint not null,
  content_json jsonb not null,
  content_hash char(64) not null,
  checkpoint_kind varchar(24) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  constraint uq_question_collection_checkpoint_version unique (question_collection_id, draft_version),
  constraint uq_question_collection_checkpoint_scope unique (
    question_collection_checkpoint_id, question_collection_id, workspace_id
  ),
  constraint fk_question_collection_checkpoint_collection foreign key (question_collection_id, workspace_id)
    references teachbase_app.question_collection(question_collection_id, workspace_id),
  constraint fk_question_collection_checkpoint_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_collection_checkpoint_version check (draft_version > 0),
  constraint ck_question_collection_checkpoint_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_question_collection_checkpoint_hash check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_question_collection_checkpoint_kind check (checkpoint_kind in ('autosave', 'manual', 'restore')),
  constraint ck_question_collection_checkpoint_expiry check (
    (checkpoint_kind = 'autosave' and expires_at is not null)
    or (checkpoint_kind <> 'autosave' and expires_at is null)
  )
);

create index idx_question_collection_checkpoint_retention
  on teachbase_app.question_collection_checkpoint(expires_at)
  where expires_at is not null;

-- Immutable publication snapshot; later question changes cannot alter used content.
create table teachbase_app.question_collection_snapshot (
  question_collection_snapshot_id uuid primary key,
  question_collection_id uuid not null,
  workspace_id uuid not null,
  source_draft_version bigint not null,
  schema_version integer not null,
  frozen_content_json jsonb not null,
  content_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_question_collection_snapshot_workspace unique (question_collection_snapshot_id, workspace_id),
  constraint fk_question_collection_snapshot_collection foreign key (question_collection_id, workspace_id)
    references teachbase_app.question_collection(question_collection_id, workspace_id),
  constraint fk_question_collection_snapshot_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_collection_snapshot_version check (source_draft_version >= 0),
  constraint ck_question_collection_snapshot_schema check (schema_version = 1),
  constraint ck_question_collection_snapshot_content check (jsonb_typeof(frozen_content_json) = 'object'),
  constraint ck_question_collection_snapshot_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

-- Frozen question packets keep snapshots independently exportable while the revision
-- foreign key preserves provenance and usage reporting.
create table teachbase_app.question_collection_snapshot_item (
  question_collection_snapshot_id uuid not null,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  position_index integer not null,
  frozen_question_json jsonb not null,
  primary key (question_collection_snapshot_id, question_id),
  constraint uq_question_collection_snapshot_position unique (question_collection_snapshot_id, position_index),
  constraint fk_question_collection_snapshot_item_snapshot foreign key (question_collection_snapshot_id, workspace_id)
    references teachbase_app.question_collection_snapshot(question_collection_snapshot_id, workspace_id),
  constraint fk_question_collection_snapshot_item_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint ck_question_collection_snapshot_item_position check (position_index >= 0),
  constraint ck_question_collection_snapshot_item_content check (jsonb_typeof(frozen_question_json) = 'object')
);

create index idx_question_collection_snapshot_usage
  on teachbase_app.question_collection_snapshot_item(workspace_id, question_id, question_collection_snapshot_id);
