-- Phase 0 隔离 spike：组版本只固定现有 question revision，不复制题目内容。
create schema if not exists teachbase_phase0_spike;

create table teachbase_phase0_spike.question_group (
  question_group_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  source_system varchar(80) not null,
  external_group_key varchar(320),
  current_composition_revision_no bigint not null default 0,
  approved_composition_revision_id uuid,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_spike_question_group_scope unique (question_group_id, workspace_id),
  constraint fk_spike_question_group_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_spike_question_group_source check (length(trim(source_system)) > 0),
  constraint ck_spike_question_group_revision check (current_composition_revision_no >= 0)
);

create unique index uq_spike_question_group_external
  on teachbase_phase0_spike.question_group(workspace_id, source_system, external_group_key)
  where external_group_key is not null;

create table teachbase_phase0_spike.question_group_composition_revision (
  question_group_composition_revision_id uuid primary key,
  question_group_id uuid not null,
  workspace_id uuid not null,
  revision_no bigint not null,
  workflow_status varchar(24) not null,
  schema_version integer not null default 1,
  content_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_spike_group_composition_scope unique (
    question_group_composition_revision_id, question_group_id, workspace_id),
  constraint uq_spike_group_composition_revision unique (question_group_id, revision_no),
  constraint uq_spike_group_composition_hash unique (question_group_id, schema_version, content_hash),
  constraint fk_spike_group_composition_group foreign key (question_group_id, workspace_id)
    references teachbase_phase0_spike.question_group(question_group_id, workspace_id),
  constraint fk_spike_group_composition_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_spike_group_composition_revision check (revision_no > 0),
  constraint ck_spike_group_composition_workflow check (
    workflow_status in ('draft', 'pending_review', 'approved', 'rejected', 'superseded')),
  constraint ck_spike_group_composition_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

alter table teachbase_phase0_spike.question_group
  add constraint fk_spike_question_group_approved_composition foreign key (
    approved_composition_revision_id, question_group_id, workspace_id)
    references teachbase_phase0_spike.question_group_composition_revision(
      question_group_composition_revision_id, question_group_id, workspace_id);

create table teachbase_phase0_spike.question_group_composition_item (
  question_group_composition_revision_id uuid not null,
  question_group_id uuid not null,
  workspace_id uuid not null,
  sort_order integer not null,
  member_role varchar(24) not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  local_label varchar(120),
  primary key (question_group_composition_revision_id, sort_order),
  constraint uq_spike_group_composition_question unique (
    question_group_composition_revision_id, question_id),
  constraint fk_spike_group_item_composition foreign key (
    question_group_composition_revision_id, question_group_id, workspace_id)
    references teachbase_phase0_spike.question_group_composition_revision(
      question_group_composition_revision_id, question_group_id, workspace_id),
  constraint fk_spike_group_item_question_revision foreign key (
    question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint ck_spike_group_item_order check (sort_order >= 0),
  constraint ck_spike_group_item_role check (member_role in ('material', 'child'))
);

create unique index uq_spike_group_single_material
  on teachbase_phase0_spike.question_group_composition_item(question_group_composition_revision_id)
  where member_role = 'material';
