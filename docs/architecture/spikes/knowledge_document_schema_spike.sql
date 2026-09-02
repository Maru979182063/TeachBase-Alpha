-- Phase 0 隔离 spike：知识文档复用 workspace/member 和结构化内容合同，不复用 editor 聚合根。
create schema if not exists teachbase_phase0_spike;

create table teachbase_phase0_spike.knowledge_document (
  knowledge_document_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  lesson_key varchar(240) not null,
  title varchar(512) not null,
  lifecycle_status varchar(24) not null default 'active',
  current_revision_no bigint not null default 0,
  approved_revision_id uuid,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_spike_knowledge_document_scope unique (knowledge_document_id, workspace_id),
  constraint uq_spike_knowledge_lesson unique (workspace_id, lesson_key),
  constraint fk_spike_knowledge_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_spike_knowledge_lesson check (length(trim(lesson_key)) > 0),
  constraint ck_spike_knowledge_title check (length(trim(title)) > 0),
  constraint ck_spike_knowledge_lifecycle check (lifecycle_status in ('active', 'archived')),
  constraint ck_spike_knowledge_revision_no check (current_revision_no >= 0)
);

create table teachbase_phase0_spike.knowledge_document_revision (
  knowledge_document_revision_id uuid primary key,
  knowledge_document_id uuid not null,
  workspace_id uuid not null,
  revision_no bigint not null,
  workflow_status varchar(24) not null,
  schema_version integer not null default 1,
  content_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_spike_knowledge_revision_scope unique (
    knowledge_document_revision_id, knowledge_document_id, workspace_id),
  constraint uq_spike_knowledge_revision_no unique (knowledge_document_id, revision_no),
  constraint uq_spike_knowledge_revision_hash unique (knowledge_document_id, schema_version, content_hash),
  constraint fk_spike_knowledge_revision_document foreign key (knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_document(knowledge_document_id, workspace_id),
  constraint fk_spike_knowledge_revision_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_spike_knowledge_revision_no check (revision_no > 0),
  constraint ck_spike_knowledge_workflow check (
    workflow_status in ('draft', 'pending_review', 'approved', 'rejected', 'superseded')),
  constraint ck_spike_knowledge_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

alter table teachbase_phase0_spike.knowledge_document
  add constraint fk_spike_knowledge_approved_revision foreign key (
    approved_revision_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_document_revision(
      knowledge_document_revision_id, knowledge_document_id, workspace_id);

create table teachbase_phase0_spike.knowledge_section_identity (
  knowledge_section_id uuid primary key,
  knowledge_document_id uuid not null,
  workspace_id uuid not null,
  section_key varchar(240) not null,
  created_at timestamptz not null default now(),
  constraint uq_spike_section_scope unique (
    knowledge_section_id, knowledge_document_id, workspace_id),
  constraint uq_spike_section_key unique (knowledge_document_id, section_key),
  constraint fk_spike_section_document foreign key (knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_document(knowledge_document_id, workspace_id),
  constraint ck_spike_section_key check (length(trim(section_key)) > 0)
);

create table teachbase_phase0_spike.knowledge_section_revision (
  knowledge_document_revision_id uuid not null,
  knowledge_document_id uuid not null,
  workspace_id uuid not null,
  knowledge_section_id uuid not null,
  parent_section_id uuid,
  sort_order integer not null,
  title varchar(512) not null,
  change_kind varchar(24) not null,
  content_json jsonb not null,
  primary key (knowledge_document_revision_id, knowledge_section_id),
  constraint fk_spike_section_revision_document foreign key (
    knowledge_document_revision_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_document_revision(
      knowledge_document_revision_id, knowledge_document_id, workspace_id),
  constraint fk_spike_section_revision_identity foreign key (
    knowledge_section_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_section_identity(
      knowledge_section_id, knowledge_document_id, workspace_id),
  constraint fk_spike_section_revision_parent foreign key (
    parent_section_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_section_identity(
      knowledge_section_id, knowledge_document_id, workspace_id),
  constraint ck_spike_section_order check (sort_order >= 0),
  constraint ck_spike_section_title check (length(trim(title)) > 0),
  constraint ck_spike_section_change check (
    change_kind in ('created', 'unchanged', 'updated', 'moved')),
  constraint ck_spike_section_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_spike_section_not_parent check (
    parent_section_id is null or parent_section_id <> knowledge_section_id)
);

create unique index uq_spike_section_tree_order
  on teachbase_phase0_spike.knowledge_section_revision(
    knowledge_document_revision_id, parent_section_id, sort_order) nulls not distinct;

create table teachbase_phase0_spike.knowledge_section_lineage (
  knowledge_document_revision_id uuid not null,
  knowledge_document_id uuid not null,
  workspace_id uuid not null,
  from_section_id uuid not null,
  to_section_id uuid not null,
  relation_type varchar(24) not null,
  primary key (knowledge_document_revision_id, from_section_id, to_section_id, relation_type),
  constraint fk_spike_lineage_revision foreign key (
    knowledge_document_revision_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_document_revision(
      knowledge_document_revision_id, knowledge_document_id, workspace_id),
  constraint fk_spike_lineage_from foreign key (
    from_section_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_section_identity(
      knowledge_section_id, knowledge_document_id, workspace_id),
  constraint fk_spike_lineage_to foreign key (
    to_section_id, knowledge_document_id, workspace_id)
    references teachbase_phase0_spike.knowledge_section_identity(
      knowledge_section_id, knowledge_document_id, workspace_id),
  constraint ck_spike_lineage_type check (relation_type in ('split_into', 'merged_into', 'replaced_by')),
  constraint ck_spike_lineage_distinct check (from_section_id <> to_section_id)
);
