-- 用途：
-- - 建立以 Postgres 为主的运行时 schema，让运行状态不再依赖文件快照。
-- - 新增运行时表时，要同步维护存储契约和在线校验套件。

-- Validation-stage follow-up migration.
-- Goal: make normalized tables the primary business source for the existing
-- runtime backbone logic, while keeping snapshot JSON as an optional debug aid.

create table if not exists runtime_metadata (
  snapshot_key text primary key,
  generated_at timestamptz not null,
  updated_at timestamptz not null,
  source text
);

create table if not exists document_source (
  source_id text primary key,
  source_type text,
  subject text,
  owner_id text,
  import_batch_id text,
  metadata_json jsonb,
  created_at timestamptz
);

create table if not exists document_group (
  document_group_id text primary key,
  subject text,
  group_type text,
  label text,
  status text,
  metadata_json jsonb,
  created_at timestamptz
);

create table if not exists document_group_member (
  document_group_member_id text primary key,
  document_group_id text not null,
  document_id text not null,
  member_role text,
  sort_index integer,
  created_at timestamptz
);
create index if not exists idx_document_group_member_group
  on document_group_member (document_group_id);

create table if not exists document_relation (
  document_relation_id text primary key,
  from_document_id text not null,
  to_document_id text not null,
  relation_type text,
  metadata_json jsonb,
  created_at timestamptz
);
create index if not exists idx_document_relation_from_document
  on document_relation (from_document_id);

create table if not exists job_dependency (
  job_dependency_id text primary key,
  upstream_job_id text not null,
  downstream_job_id text not null,
  dependency_type text,
  created_at timestamptz
);
create index if not exists idx_job_dependency_downstream
  on job_dependency (downstream_job_id);

create table if not exists outbox_event (
  outbox_event_id text primary key,
  aggregate_type text,
  aggregate_id text,
  event_type text,
  payload_json jsonb,
  status text,
  created_at timestamptz,
  dispatched_at timestamptz
);
create index if not exists idx_outbox_event_status
  on outbox_event (status);

create table if not exists lesson_import (
  import_id text primary key,
  bundle_id text not null,
  content_hash text not null,
  lesson_id text not null,
  lesson_revision_id text not null,
  run_id text,
  review_task_id text,
  artifact_id text,
  created_at timestamptz
);
create index if not exists idx_lesson_import_bundle_hash
  on lesson_import (bundle_id, content_hash);

create table if not exists component_link (
  component_link_id text primary key,
  component_id text not null,
  target_type text not null,
  target_revision_id text not null,
  relation_type text,
  created_at timestamptz
);
create index if not exists idx_component_link_target_revision
  on component_link (target_revision_id);

create table if not exists source_node (
  source_node_id text primary key,
  lesson_id text not null,
  stable_code text,
  current_revision_id text,
  created_at timestamptz
);
create index if not exists idx_source_node_lesson
  on source_node (lesson_id);

create table if not exists source_node_revision (
  source_node_revision_id text primary key,
  source_node_id text not null,
  lesson_revision_id text not null,
  parent_node_revision_id text,
  node_type text,
  phase text,
  title text,
  order_index integer,
  page_span integer[],
  component_bundle_ref text,
  generated_data_ref text,
  manual_patch_ref text,
  merged_data_ref text,
  status text,
  created_at timestamptz
);
create index if not exists idx_source_node_revision_lesson_revision
  on source_node_revision (lesson_revision_id);

create table if not exists task (
  task_id text primary key,
  lesson_id text not null,
  stable_question_no text,
  current_revision_id text,
  created_at timestamptz
);
create index if not exists idx_task_lesson
  on task (lesson_id);

create table if not exists task_revision (
  task_revision_id text primary key,
  task_id text not null,
  lesson_revision_id text not null,
  source_node_revision_id text,
  student_stem text,
  teacher_stem text,
  answer text,
  explanation text,
  visibility text,
  generated_data_ref text,
  manual_patch_ref text,
  merged_data_ref text,
  status text,
  created_at timestamptz
);
create index if not exists idx_task_revision_lesson_revision
  on task_revision (lesson_revision_id);

create table if not exists checkpoint_catalog (
  catalog_id text primary key,
  key text,
  subject text,
  scope_type text,
  status text,
  created_at timestamptz
);

create table if not exists checkpoint_catalog_version (
  catalog_version_id text primary key,
  catalog_id text not null,
  version_no integer,
  status text,
  base_version_id text,
  overlay_ref text,
  published_at timestamptz,
  created_at timestamptz
);
create index if not exists idx_checkpoint_catalog_version_catalog
  on checkpoint_catalog_version (catalog_id);

create table if not exists checkpoint_node (
  checkpoint_node_id text primary key,
  catalog_version_id text not null,
  parent_id text,
  code text,
  name text,
  node_kind text,
  order_index integer,
  created_at timestamptz
);
create index if not exists idx_checkpoint_node_catalog_version
  on checkpoint_node (catalog_version_id);

create table if not exists source_node_checkpoint_link (
  link_id text primary key,
  source_node_revision_id text not null,
  checkpoint_node_id text not null,
  relation_type text,
  confidence numeric,
  mapping_source text,
  created_at timestamptz
);
create index if not exists idx_source_node_checkpoint_link_revision
  on source_node_checkpoint_link (source_node_revision_id);

create table if not exists task_checkpoint_override (
  override_id text primary key,
  task_revision_id text not null,
  checkpoint_node_id text not null,
  relation_type text,
  confidence numeric,
  mapping_source text,
  reason text,
  created_at timestamptz
);
create index if not exists idx_task_checkpoint_override_revision
  on task_checkpoint_override (task_revision_id);

create table if not exists task_subject_ext (
  task_revision_id text primary key,
  subject text,
  plugin_id text,
  plugin_version text,
  schema_version text,
  payload_json jsonb,
  risk_flags text[] default '{}',
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists quality_evaluation (
  quality_evaluation_id text primary key,
  target_type text not null,
  target_revision_id text not null,
  rule_set_version text,
  check_code text,
  severity text,
  score numeric,
  passed boolean,
  evidence_ref text,
  evaluated_at timestamptz
);
create index if not exists idx_quality_evaluation_target
  on quality_evaluation (target_type, target_revision_id);
