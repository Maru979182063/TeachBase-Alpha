-- G4 讲义内容资产与编排基础。
-- 本迁移只追加关系模型并修正来源链接唯一性，不重写既有题目、编辑器修订或快照内容。

-- source_region 原本只能按单列引用；补充组合唯一键后，新关系可以在数据库层验证
-- region 确实属于所声明的 source document。
alter table teachbase_app.source_region
  add constraint uq_source_region_document unique (source_region_id, source_document_id);

alter table teachbase_app.source_document
  add constraint uq_source_document_workspace unique (source_document_id, workspace_id),
  add constraint uq_source_document_file_scope unique (source_document_id, file_version_id, workspace_id);

-- 一个题目修订可以拥有多条规范来源证据；evidence key 只负责同一条证据的重试幂等。
alter table teachbase_app.question_source_link
  add column source_evidence_key varchar(160);

update teachbase_app.question_source_link
set source_evidence_key = 'legacy:' || question_source_link_id::text
where source_evidence_key is null;

alter table teachbase_app.question_source_link
  alter column source_evidence_key set not null;

alter table teachbase_app.question_source_link
  drop constraint uq_question_source_revision;

alter table teachbase_app.question_source_link
  add constraint uq_question_source_evidence unique (question_revision_id, source_evidence_key),
  add constraint ck_question_source_evidence_key check (length(trim(source_evidence_key)) > 0),
  add constraint ck_question_source_region_document check (
    source_region_id is null or source_document_id is not null
  );

alter table teachbase_app.question_source_link
  drop constraint fk_question_source_document;

alter table teachbase_app.question_source_link
  add constraint fk_question_source_document_workspace foreign key (source_document_id, workspace_id)
    references teachbase_app.source_document(source_document_id, workspace_id);

alter table teachbase_app.question_source_link
  drop constraint fk_question_source_region;

alter table teachbase_app.question_source_link
  add constraint fk_question_source_region_document foreign key (source_region_id, source_document_id)
    references teachbase_app.source_region(source_region_id, source_document_id);

create index idx_question_source_revision
  on teachbase_app.question_source_link(workspace_id, question_revision_id, created_at);

-- 与 question 同级的可复用内容资产。稳定根对象只保存身份和生命周期指针，
-- 正文、标题和结构均保存在不可变 revision 中。
create table teachbase_app.standard_module (
  standard_module_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  module_key varchar(240) not null,
  module_type varchar(120) not null,
  status varchar(24) not null default 'active',
  current_revision_no bigint not null default 0,
  approved_revision_id uuid,
  created_by uuid not null,
  updated_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_standard_module_scope unique (standard_module_id, workspace_id),
  constraint uq_standard_module_key unique (workspace_id, module_key),
  constraint fk_standard_module_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_standard_module_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_standard_module_key check (length(trim(module_key)) > 0),
  constraint ck_standard_module_type check (length(trim(module_type)) > 0),
  constraint ck_standard_module_status check (status in ('active', 'archived', 'quarantined')),
  constraint ck_standard_module_revision check (current_revision_no >= 0)
);

create table teachbase_app.standard_module_revision (
  standard_module_revision_id uuid primary key,
  standard_module_id uuid not null,
  workspace_id uuid not null,
  revision_no bigint not null,
  review_status varchar(24) not null default 'unreviewed',
  title varchar(512) not null,
  subject varchar(80) not null,
  stage varchar(80) not null default '',
  grade varchar(80) not null default '',
  schema_version integer not null default 1,
  content_json jsonb not null,
  content_hash char(64) not null,
  approved_at timestamptz,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_standard_module_revision_number unique (standard_module_id, revision_no),
  constraint uq_standard_module_revision_hash unique (standard_module_id, content_hash),
  constraint uq_standard_module_revision_scope unique (
    standard_module_revision_id, standard_module_id, workspace_id
  ),
  constraint uq_standard_module_revision_workspace unique (standard_module_revision_id, workspace_id),
  constraint fk_standard_module_revision_root foreign key (standard_module_id, workspace_id)
    references teachbase_app.standard_module(standard_module_id, workspace_id),
  constraint fk_standard_module_revision_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_standard_module_revision_no check (revision_no > 0),
  constraint ck_standard_module_review check (
    review_status in ('unreviewed', 'pending_review', 'approved', 'rejected')
  ),
  constraint ck_standard_module_title check (length(trim(title)) > 0),
  constraint ck_standard_module_subject check (length(trim(subject)) > 0),
  constraint ck_standard_module_schema check (schema_version > 0),
  constraint ck_standard_module_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_standard_module_hash check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_standard_module_approval check (
    (review_status = 'approved' and approved_at is not null)
    or (review_status <> 'approved' and approved_at is null)
  )
);

alter table teachbase_app.standard_module
  add constraint fk_standard_module_approved_revision foreign key (
    approved_revision_id, standard_module_id, workspace_id
  ) references teachbase_app.standard_module_revision(
    standard_module_revision_id, standard_module_id, workspace_id
  );

create index idx_standard_module_workspace
  on teachbase_app.standard_module(workspace_id, status, updated_at desc, standard_module_id);
create index idx_standard_module_revision_review
  on teachbase_app.standard_module_revision(workspace_id, review_status, created_at, standard_module_revision_id);

create table teachbase_app.standard_module_source_link (
  standard_module_source_link_id uuid primary key,
  standard_module_id uuid not null,
  standard_module_revision_id uuid not null,
  workspace_id uuid not null,
  source_evidence_key varchar(160) not null,
  source_document_id uuid,
  source_region_id uuid,
  source_role varchar(40) not null default 'canonical',
  source_ref_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_standard_module_source unique (
    standard_module_revision_id, source_evidence_key
  ),
  constraint fk_standard_module_source_revision foreign key (
    standard_module_revision_id, standard_module_id, workspace_id
  ) references teachbase_app.standard_module_revision(
    standard_module_revision_id, standard_module_id, workspace_id
  ),
  constraint fk_standard_module_source_document foreign key (source_document_id, workspace_id)
    references teachbase_app.source_document(source_document_id, workspace_id),
  constraint fk_standard_module_source_region foreign key (source_region_id, source_document_id)
    references teachbase_app.source_region(source_region_id, source_document_id),
  constraint ck_standard_module_source_key check (length(trim(source_evidence_key)) > 0),
  constraint ck_standard_module_source_role check (
    source_role in ('canonical', 'supporting', 'teacher_original', 'student_original')
  ),
  constraint ck_standard_module_source_pair check (
    source_region_id is null or source_document_id is not null
  ),
  constraint ck_standard_module_source_ref check (jsonb_typeof(source_ref_json) = 'object')
);

create index idx_standard_module_source_lookup
  on teachbase_app.standard_module_source_link(workspace_id, standard_module_revision_id, source_document_id);

create table teachbase_app.standard_module_file_reference (
  standard_module_file_reference_id uuid primary key,
  standard_module_id uuid not null,
  standard_module_revision_id uuid not null,
  workspace_id uuid not null,
  file_version_id uuid not null,
  reference_key varchar(160) not null,
  reference_role varchar(40) not null,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_standard_module_file_reference unique (
    standard_module_revision_id, reference_key
  ),
  constraint fk_standard_module_file_revision foreign key (
    standard_module_revision_id, standard_module_id, workspace_id
  ) references teachbase_app.standard_module_revision(
    standard_module_revision_id, standard_module_id, workspace_id
  ),
  constraint fk_standard_module_file_version foreign key (file_version_id, workspace_id)
    references teachbase_app.file_version(file_version_id, workspace_id),
  constraint ck_standard_module_file_key check (length(trim(reference_key)) > 0),
  constraint ck_standard_module_file_role check (length(trim(reference_role)) > 0),
  constraint ck_standard_module_file_metadata check (jsonb_typeof(metadata_json) = 'object')
);

-- 复用统一 Review case；旧 question 行自动保持 target_type=question。
alter table teachbase_app.review_case
  add column target_type varchar(32) not null default 'question',
  add column standard_module_id uuid,
  add column standard_module_revision_id uuid;

-- jOOQ DDL simulator不支持 PostgreSQL的 DROP NOT NULL 语法；Flyway仍会执行。
-- [jooq ignore start]
alter table teachbase_app.review_case alter column question_id drop not null;
alter table teachbase_app.review_case alter column question_revision_id drop not null;
-- [jooq ignore stop]

alter table teachbase_app.review_case
  add constraint fk_review_case_standard_module_revision foreign key (
    standard_module_revision_id, standard_module_id, workspace_id
  ) references teachbase_app.standard_module_revision(
    standard_module_revision_id, standard_module_id, workspace_id
  ),
  add constraint ck_review_case_target check (
    (target_type = 'question'
      and question_id is not null and question_revision_id is not null
      and standard_module_id is null and standard_module_revision_id is null)
    or
    (target_type = 'standard_module'
      and question_id is null and question_revision_id is null
      and standard_module_id is not null and standard_module_revision_id is not null)
  );

-- [jooq ignore start]
create unique index uq_review_case_open_standard_module_revision
  on teachbase_app.review_case(standard_module_revision_id)
  where status = 'open' and target_type = 'standard_module';
-- [jooq ignore stop]

create table teachbase_app.standard_module_taxonomy_link (
  standard_module_taxonomy_link_id uuid primary key,
  workspace_id uuid not null,
  standard_module_id uuid not null,
  standard_module_revision_id uuid not null,
  taxonomy_node_id uuid not null,
  taxonomy_version_id uuid not null,
  relation_type varchar(24) not null,
  assignment_source varchar(24) not null,
  confidence numeric(5,4),
  assigned_by uuid not null,
  assigned_at timestamptz not null default now(),
  constraint uq_standard_module_taxonomy_link unique (
    standard_module_revision_id, taxonomy_node_id, relation_type
  ),
  constraint fk_standard_module_taxonomy_revision foreign key (
    standard_module_revision_id, standard_module_id, workspace_id
  ) references teachbase_app.standard_module_revision(
    standard_module_revision_id, standard_module_id, workspace_id
  ),
  constraint fk_standard_module_taxonomy_node foreign key (
    taxonomy_node_id, taxonomy_version_id, workspace_id
  ) references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint fk_standard_module_taxonomy_actor foreign key (workspace_id, assigned_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_standard_module_taxonomy_relation check (relation_type in ('primary', 'secondary')),
  constraint ck_standard_module_taxonomy_source check (assignment_source in ('human', 'model', 'import')),
  constraint ck_standard_module_taxonomy_confidence check (confidence is null or confidence between 0 and 1)
);

create index idx_standard_module_taxonomy_lookup
  on teachbase_app.standard_module_taxonomy_link(
    workspace_id, taxonomy_node_id, standard_module_revision_id
  );

-- edition 是一份 editor document 的稳定受众身份；teacher canonical 与 student projection
-- 都必须通过不可变 edition revision 绑定精确 editor revision。
create table teachbase_app.handout_edition (
  handout_edition_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  edition_key varchar(80) not null,
  edition_role varchar(24) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_handout_edition_scope unique (handout_edition_id, editor_document_id, workspace_id),
  constraint uq_handout_edition_key unique (editor_document_id, edition_key),
  constraint fk_handout_edition_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_handout_edition_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_handout_edition_key check (length(trim(edition_key)) > 0),
  constraint ck_handout_edition_role check (edition_role in ('canonical', 'projection'))
);

create table teachbase_app.handout_edition_revision (
  handout_edition_revision_id uuid primary key,
  handout_edition_id uuid not null,
  editor_document_id uuid not null,
  editor_revision_id uuid not null,
  workspace_id uuid not null,
  edition_role varchar(24) not null,
  canonical_teacher_revision_id uuid,
  schema_version integer not null default 1,
  projection_rules_json jsonb not null default '{}'::jsonb,
  delta_json jsonb not null default '{}'::jsonb,
  content_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_handout_edition_revision_scope unique (
    handout_edition_revision_id, editor_document_id, editor_revision_id, workspace_id
  ),
  constraint uq_handout_edition_revision_document_scope unique (
    handout_edition_revision_id, editor_document_id, workspace_id
  ),
  constraint uq_handout_edition_editor_revision unique (handout_edition_id, editor_revision_id),
  constraint fk_handout_edition_revision_edition foreign key (
    handout_edition_id, editor_document_id, workspace_id
  ) references teachbase_app.handout_edition(handout_edition_id, editor_document_id, workspace_id),
  constraint fk_handout_edition_revision_editor foreign key (
    editor_revision_id, editor_document_id, workspace_id
  ) references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_handout_edition_revision_canonical foreign key (
    canonical_teacher_revision_id, editor_document_id, workspace_id
  ) references teachbase_app.handout_edition_revision(
    handout_edition_revision_id, editor_document_id, workspace_id
  ),
  constraint fk_handout_edition_revision_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_handout_edition_revision_role check (edition_role in ('canonical', 'projection')),
  constraint ck_handout_edition_revision_projection check (
    (edition_role = 'canonical' and canonical_teacher_revision_id is null)
    or (edition_role = 'projection' and canonical_teacher_revision_id is not null)
  ),
  constraint ck_handout_edition_revision_schema check (schema_version > 0),
  constraint ck_handout_edition_revision_rules check (jsonb_typeof(projection_rules_json) = 'object'),
  constraint ck_handout_edition_revision_delta check (jsonb_typeof(delta_json) = 'object'),
  constraint ck_handout_edition_revision_hash check (content_hash ~ '^[0-9a-f]{64}$')
);

create index idx_handout_edition_revision_hash
  on teachbase_app.handout_edition_revision(handout_edition_id, content_hash);

create table teachbase_app.handout_occurrence_identity (
  handout_occurrence_identity_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  occurrence_key varchar(240) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_handout_occurrence_identity_scope unique (
    handout_occurrence_identity_id, editor_document_id, workspace_id
  ),
  constraint uq_handout_occurrence_key unique (editor_document_id, occurrence_key),
  constraint fk_handout_occurrence_identity_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_handout_occurrence_identity_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_handout_occurrence_key check (length(trim(occurrence_key)) > 0)
);

create table teachbase_app.handout_occurrence (
  handout_occurrence_id uuid primary key,
  handout_occurrence_identity_id uuid not null,
  handout_edition_revision_id uuid not null,
  editor_document_id uuid not null,
  editor_revision_id uuid not null,
  workspace_id uuid not null,
  parent_occurrence_id uuid,
  position_index integer not null,
  occurrence_kind varchar(32) not null,
  question_id uuid,
  question_revision_id uuid,
  standard_module_id uuid,
  standard_module_revision_id uuid,
  local_content_json jsonb,
  attributes_json jsonb not null default '{}'::jsonb,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_handout_occurrence_scope unique (
    handout_occurrence_id, handout_edition_revision_id, workspace_id
  ),
  constraint uq_handout_occurrence_identity_revision unique (
    handout_edition_revision_id, handout_occurrence_identity_id
  ),
  constraint fk_handout_occurrence_identity foreign key (
    handout_occurrence_identity_id, editor_document_id, workspace_id
  ) references teachbase_app.handout_occurrence_identity(
    handout_occurrence_identity_id, editor_document_id, workspace_id
  ),
  constraint fk_handout_occurrence_edition_revision foreign key (
    handout_edition_revision_id, editor_document_id, editor_revision_id, workspace_id
  ) references teachbase_app.handout_edition_revision(
    handout_edition_revision_id, editor_document_id, editor_revision_id, workspace_id
  ),
  constraint fk_handout_occurrence_parent foreign key (
    parent_occurrence_id, handout_edition_revision_id, workspace_id
  ) references teachbase_app.handout_occurrence(
    handout_occurrence_id, handout_edition_revision_id, workspace_id
  ),
  constraint fk_handout_occurrence_question foreign key (
    question_revision_id, question_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_handout_occurrence_standard_module foreign key (
    standard_module_revision_id, standard_module_id, workspace_id
  ) references teachbase_app.standard_module_revision(
    standard_module_revision_id, standard_module_id, workspace_id
  ),
  constraint fk_handout_occurrence_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_handout_occurrence_position check (position_index >= 0),
  constraint ck_handout_occurrence_kind check (
    occurrence_kind in ('container', 'question', 'standard_module', 'ordinary_content')
  ),
  constraint ck_handout_occurrence_target check (
    (occurrence_kind = 'container'
      and question_id is null and question_revision_id is null
      and standard_module_id is null and standard_module_revision_id is null
      and local_content_json is null)
    or
    (occurrence_kind = 'question'
      and question_id is not null and question_revision_id is not null
      and standard_module_id is null and standard_module_revision_id is null
      and local_content_json is null)
    or
    (occurrence_kind = 'standard_module'
      and question_id is null and question_revision_id is null
      and standard_module_id is not null and standard_module_revision_id is not null
      and local_content_json is null)
    or
    (occurrence_kind = 'ordinary_content'
      and question_id is null and question_revision_id is null
      and standard_module_id is null and standard_module_revision_id is null
      and local_content_json is not null)
  ),
  constraint ck_handout_occurrence_local_content check (
    local_content_json is null or jsonb_typeof(local_content_json) = 'object'
  ),
  constraint ck_handout_occurrence_attributes check (jsonb_typeof(attributes_json) = 'object'),
  constraint ck_handout_occurrence_not_self_parent check (
    parent_occurrence_id is null or parent_occurrence_id <> handout_occurrence_id
  )
);

-- PostgreSQL partial indexes make root and child sibling order independently unique.
-- [jooq ignore start]
create unique index uq_handout_occurrence_root_order
  on teachbase_app.handout_occurrence(handout_edition_revision_id, position_index)
  where parent_occurrence_id is null;
create unique index uq_handout_occurrence_child_order
  on teachbase_app.handout_occurrence(
    handout_edition_revision_id, parent_occurrence_id, position_index
  ) where parent_occurrence_id is not null;
-- [jooq ignore stop]

create index idx_handout_occurrence_question_usage
  on teachbase_app.handout_occurrence(workspace_id, question_revision_id)
  where question_revision_id is not null;
create index idx_handout_occurrence_module_usage
  on teachbase_app.handout_occurrence(workspace_id, standard_module_revision_id)
  where standard_module_revision_id is not null;

create table teachbase_app.handout_occurrence_source_link (
  handout_occurrence_source_link_id uuid primary key,
  handout_occurrence_id uuid not null,
  handout_edition_revision_id uuid not null,
  workspace_id uuid not null,
  source_evidence_key varchar(160) not null,
  source_document_id uuid not null,
  source_region_id uuid,
  source_role varchar(40) not null,
  source_ref_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_handout_occurrence_source unique (
    handout_occurrence_id, source_evidence_key
  ),
  constraint fk_handout_occurrence_source_occurrence foreign key (
    handout_occurrence_id, handout_edition_revision_id, workspace_id
  ) references teachbase_app.handout_occurrence(
    handout_occurrence_id, handout_edition_revision_id, workspace_id
  ),
  constraint fk_handout_occurrence_source_document foreign key (source_document_id, workspace_id)
    references teachbase_app.source_document(source_document_id, workspace_id),
  constraint fk_handout_occurrence_source_region foreign key (source_region_id, source_document_id)
    references teachbase_app.source_region(source_region_id, source_document_id),
  constraint ck_handout_occurrence_source_key check (length(trim(source_evidence_key)) > 0),
  constraint ck_handout_occurrence_source_role check (
    source_role in ('teacher_original', 'student_original', 'supporting')
  ),
  constraint ck_handout_occurrence_source_ref check (jsonb_typeof(source_ref_json) = 'object')
);

create index idx_handout_occurrence_source_region
  on teachbase_app.handout_occurrence_source_link(
    workspace_id, source_document_id, source_region_id
  );

create table teachbase_app.editor_revision_artifact_link (
  editor_revision_artifact_link_id uuid primary key,
  editor_document_id uuid not null,
  editor_revision_id uuid not null,
  workspace_id uuid not null,
  artifact_key varchar(160) not null,
  artifact_role varchar(40) not null,
  file_version_id uuid not null,
  source_document_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_editor_revision_artifact unique (editor_revision_id, artifact_key),
  constraint fk_editor_revision_artifact_revision foreign key (
    editor_revision_id, editor_document_id, workspace_id
  ) references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_editor_revision_artifact_file foreign key (file_version_id, workspace_id)
    references teachbase_app.file_version(file_version_id, workspace_id),
  constraint fk_editor_revision_artifact_source foreign key (
    source_document_id, file_version_id, workspace_id
  ) references teachbase_app.source_document(source_document_id, file_version_id, workspace_id),
  constraint ck_editor_revision_artifact_key check (length(trim(artifact_key)) > 0),
  constraint ck_editor_revision_artifact_role check (
    artifact_role in ('original_docx', 'split_manifest', 'preservation_bundle', 'roundtrip_output')
  ),
  constraint ck_editor_revision_artifact_original_source check (
    artifact_role <> 'original_docx' or source_document_id is not null
  ),
  constraint ck_editor_revision_artifact_metadata check (jsonb_typeof(metadata_json) = 'object')
);

create index idx_editor_revision_artifact_lookup
  on teachbase_app.editor_revision_artifact_link(workspace_id, editor_revision_id, artifact_role);

-- G4 的 immutable 表只允许插入和读取；module revision 只有审核状态与 approved_at
-- 可由 Review 更新，正文和身份字段由数据库 trigger 封锁。
-- [jooq ignore start]
create or replace function teachbase_app.reject_handout_immutable_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'handout_immutable_row_mutation_forbidden';
end;
$$;

create or replace function teachbase_app.protect_standard_module_revision_content()
returns trigger
language plpgsql
as $$
begin
  if row(
      old.standard_module_id, old.workspace_id, old.revision_no, old.title, old.subject,
      old.stage, old.grade, old.schema_version, old.content_json, old.content_hash,
      old.created_by, old.created_at
    ) is distinct from row(
      new.standard_module_id, new.workspace_id, new.revision_no, new.title, new.subject,
      new.stage, new.grade, new.schema_version, new.content_json, new.content_hash,
      new.created_by, new.created_at
    ) then
    raise exception 'standard_module_revision_content_immutable';
  end if;
  return new;
end;
$$;

create trigger trg_standard_module_revision_content_immutable
before update on teachbase_app.standard_module_revision
for each row execute function teachbase_app.protect_standard_module_revision_content();

create trigger trg_standard_module_revision_delete_immutable
before delete on teachbase_app.standard_module_revision
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_standard_module_source_immutable
before update or delete on teachbase_app.standard_module_source_link
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_standard_module_file_reference_immutable
before update or delete on teachbase_app.standard_module_file_reference
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_handout_edition_identity_immutable
before update or delete on teachbase_app.handout_edition
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_handout_edition_revision_immutable
before update or delete on teachbase_app.handout_edition_revision
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_handout_occurrence_identity_immutable
before update or delete on teachbase_app.handout_occurrence_identity
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_handout_occurrence_immutable
before update or delete on teachbase_app.handout_occurrence
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_handout_occurrence_source_immutable
before update or delete on teachbase_app.handout_occurrence_source_link
for each row execute function teachbase_app.reject_handout_immutable_mutation();

create trigger trg_editor_revision_artifact_immutable
before update or delete on teachbase_app.editor_revision_artifact_link
for each row execute function teachbase_app.reject_handout_immutable_mutation();
-- [jooq ignore stop]
