-- 后端数据库草案 v0.1
-- 目标：把 v0.3 设计中的核心对象落到可审阅的 PostgreSQL 表结构草案
-- 说明：这是评审稿，不是最终迁移文件。字段与索引以“先把边界定住”为目标。

create extension if not exists pgcrypto;

-- ========== 基础来源与文档 ==========

create table if not exists document_source (
  source_id uuid primary key default gen_random_uuid(),
  source_type text not null,
  subject text,
  owner_id text,
  import_batch_id text,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists document (
  document_id uuid primary key default gen_random_uuid(),
  source_id uuid not null references document_source(source_id),
  subject text,
  stage text,
  grade text,
  season text,
  doc_role text not null,
  title text,
  storage_uri text not null,
  checksum text,
  page_count integer,
  status text not null default 'uploaded',
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_document_source_id on document(source_id);
create index if not exists idx_document_subject_role on document(subject, doc_role);

create table if not exists document_group (
  document_group_id uuid primary key default gen_random_uuid(),
  subject text,
  group_type text not null,
  label text not null,
  status text not null default 'active',
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists document_group_member (
  document_group_member_id uuid primary key default gen_random_uuid(),
  document_group_id uuid not null references document_group(document_group_id) on delete cascade,
  document_id uuid not null references document(document_id) on delete cascade,
  member_role text not null,
  sort_index integer not null default 0,
  created_at timestamptz not null default now(),
  unique (document_group_id, document_id, member_role)
);

create index if not exists idx_document_group_member_group on document_group_member(document_group_id, sort_index);

create table if not exists document_relation (
  document_relation_id uuid primary key default gen_random_uuid(),
  from_document_id uuid not null references document(document_id) on delete cascade,
  to_document_id uuid not null references document(document_id) on delete cascade,
  relation_type text not null,
  confidence numeric(5,4),
  source text,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_document_relation_from on document_relation(from_document_id, relation_type);
create index if not exists idx_document_relation_to on document_relation(to_document_id, relation_type);

-- ========== 运行、任务、队列 ==========

create table if not exists run (
  run_id uuid primary key default gen_random_uuid(),
  run_type text not null,
  root_target_type text not null,
  root_target_id uuid,
  subject text,
  lane text not null,
  status text not null default 'processing',
  triggered_by text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists idx_run_root_target on run(root_target_type, root_target_id);
create index if not exists idx_run_lane_status on run(lane, status, started_at desc);

create table if not exists job (
  job_id uuid primary key default gen_random_uuid(),
  run_id uuid not null references run(run_id) on delete cascade,
  job_type text not null,
  lane text not null,
  capability text not null,
  resource_class text not null,
  priority integer not null default 100,
  idempotency_key text not null,
  status text not null default 'queued',
  attempt_count integer not null default 0,
  max_attempts integer not null default 3,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  timeout_at timestamptz,
  cancel_requested_at timestamptz,
  next_retry_at timestamptz,
  error_code text,
  error_detail_ref text,
  payload_ref text,
  result_artifact_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (idempotency_key)
);

create index if not exists idx_job_run_id on job(run_id);
create index if not exists idx_job_sched on job(status, lane, capability, priority, created_at);
create index if not exists idx_job_retry on job(status, next_retry_at);

create table if not exists job_dependency (
  job_dependency_id uuid primary key default gen_random_uuid(),
  upstream_job_id uuid not null references job(job_id) on delete cascade,
  downstream_job_id uuid not null references job(job_id) on delete cascade,
  dependency_type text not null,
  created_at timestamptz not null default now(),
  unique (upstream_job_id, downstream_job_id, dependency_type),
  check (upstream_job_id <> downstream_job_id)
);

create index if not exists idx_job_dependency_downstream on job_dependency(downstream_job_id);

create table if not exists outbox_event (
  outbox_event_id uuid primary key default gen_random_uuid(),
  aggregate_type text not null,
  aggregate_id uuid not null,
  event_type text not null,
  payload_json jsonb not null,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  dispatched_at timestamptz
);

create index if not exists idx_outbox_event_status on outbox_event(status, created_at);

-- ========== Artifact 与血缘 ==========

create table if not exists artifact (
  artifact_id uuid primary key default gen_random_uuid(),
  run_id uuid references run(run_id) on delete set null,
  job_id uuid references job(job_id) on delete set null,
  artifact_type text not null,
  schema_version text not null,
  producer_name text not null,
  producer_version text,
  model_version text,
  prompt_hash text,
  plugin_version text,
  storage_uri text not null,
  content_hash text,
  summary_json jsonb not null default '{}'::jsonb,
  supersedes_artifact_id uuid references artifact(artifact_id),
  lifecycle_status text not null default 'valid',
  created_at timestamptz not null default now()
);

create index if not exists idx_artifact_run_id on artifact(run_id, artifact_type);
create index if not exists idx_artifact_job_id on artifact(job_id);
create index if not exists idx_artifact_lifecycle on artifact(lifecycle_status, artifact_type, created_at desc);
create index if not exists idx_artifact_supersedes on artifact(supersedes_artifact_id);

alter table job
  add constraint fk_job_result_artifact
  foreign key (result_artifact_id) references artifact(artifact_id) deferrable initially deferred;

create table if not exists artifact_dependency (
  artifact_dependency_id uuid primary key default gen_random_uuid(),
  parent_artifact_id uuid not null references artifact(artifact_id) on delete cascade,
  child_artifact_id uuid not null references artifact(artifact_id) on delete cascade,
  dependency_type text not null,
  created_at timestamptz not null default now(),
  unique (parent_artifact_id, child_artifact_id, dependency_type),
  check (parent_artifact_id <> child_artifact_id)
);

create index if not exists idx_artifact_dependency_child on artifact_dependency(child_artifact_id);

-- ========== 讲义逻辑实体与修订 ==========

create table if not exists lesson (
  lesson_id uuid primary key default gen_random_uuid(),
  document_group_id uuid references document_group(document_group_id),
  subject text not null,
  stage text,
  grade text,
  season text,
  title text not null,
  active_revision_id uuid,
  published_revision_id uuid,
  status text not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists lesson_revision (
  lesson_revision_id uuid primary key default gen_random_uuid(),
  lesson_id uuid not null references lesson(lesson_id) on delete cascade,
  base_artifact_id uuid references artifact(artifact_id),
  generated_snapshot_ref text,
  manual_patch_ref text,
  merged_snapshot_ref text,
  revision_no integer not null,
  status text not null default 'draft',
  created_by text,
  created_at timestamptz not null default now(),
  unique (lesson_id, revision_no)
);

create index if not exists idx_lesson_revision_lesson on lesson_revision(lesson_id, revision_no desc);

alter table lesson
  add constraint fk_lesson_active_revision
  foreign key (active_revision_id) references lesson_revision(lesson_revision_id) deferrable initially deferred;

alter table lesson
  add constraint fk_lesson_published_revision
  foreign key (published_revision_id) references lesson_revision(lesson_revision_id) deferrable initially deferred;

-- ========== 页与组件 ==========

create table if not exists page_asset (
  page_asset_id uuid primary key default gen_random_uuid(),
  document_id uuid not null references document(document_id) on delete cascade,
  page_no integer not null,
  width integer,
  height integer,
  image_artifact_id uuid references artifact(artifact_id),
  ocr_artifact_id uuid references artifact(artifact_id),
  layout_artifact_id uuid references artifact(artifact_id),
  status text not null default 'ready',
  created_at timestamptz not null default now(),
  unique (document_id, page_no)
);

create index if not exists idx_page_asset_document on page_asset(document_id, page_no);

create table if not exists component (
  component_id uuid primary key default gen_random_uuid(),
  page_asset_id uuid not null references page_asset(page_asset_id) on delete cascade,
  parent_component_id uuid references component(component_id) on delete set null,
  component_type text not null,
  bbox_json jsonb not null,
  reading_order integer,
  crop_artifact_id uuid references artifact(artifact_id),
  content_hash text,
  schema_version text not null,
  extraction_confidence numeric(5,4),
  status text not null default 'ready',
  created_at timestamptz not null default now()
);

create index if not exists idx_component_page_asset on component(page_asset_id, reading_order);
create index if not exists idx_component_parent on component(parent_component_id);
create index if not exists idx_component_type on component(component_type, status);

create table if not exists source_node (
  source_node_id uuid primary key default gen_random_uuid(),
  lesson_id uuid not null references lesson(lesson_id) on delete cascade,
  stable_code text not null,
  current_revision_id uuid,
  created_at timestamptz not null default now(),
  unique (lesson_id, stable_code)
);

create table if not exists source_node_revision (
  source_node_revision_id uuid primary key default gen_random_uuid(),
  source_node_id uuid not null references source_node(source_node_id) on delete cascade,
  lesson_revision_id uuid not null references lesson_revision(lesson_revision_id) on delete cascade,
  parent_node_revision_id uuid references source_node_revision(source_node_revision_id) on delete set null,
  node_type text not null,
  phase text,
  title text not null,
  order_index integer not null default 0,
  page_span int4range,
  component_bundle_ref text,
  generated_data_ref text,
  manual_patch_ref text,
  merged_data_ref text,
  status text not null default 'draft',
  created_at timestamptz not null default now()
);

create index if not exists idx_source_node_revision_source_node on source_node_revision(source_node_id, created_at desc);
create index if not exists idx_source_node_revision_lesson_revision on source_node_revision(lesson_revision_id, order_index);

alter table source_node
  add constraint fk_source_node_current_revision
  foreign key (current_revision_id) references source_node_revision(source_node_revision_id) deferrable initially deferred;

create table if not exists task (
  task_id uuid primary key default gen_random_uuid(),
  lesson_id uuid not null references lesson(lesson_id) on delete cascade,
  stable_question_no text not null,
  current_revision_id uuid,
  created_at timestamptz not null default now(),
  unique (lesson_id, stable_question_no)
);

create table if not exists task_revision (
  task_revision_id uuid primary key default gen_random_uuid(),
  task_id uuid not null references task(task_id) on delete cascade,
  lesson_revision_id uuid not null references lesson_revision(lesson_revision_id) on delete cascade,
  source_node_revision_id uuid not null references source_node_revision(source_node_revision_id) on delete cascade,
  student_stem text,
  teacher_stem text,
  answer text,
  explanation text,
  visibility text,
  generated_data_ref text,
  manual_patch_ref text,
  merged_data_ref text,
  status text not null default 'draft',
  created_at timestamptz not null default now()
);

create index if not exists idx_task_revision_task on task_revision(task_id, created_at desc);
create index if not exists idx_task_revision_source_node on task_revision(source_node_revision_id);

alter table task
  add constraint fk_task_current_revision
  foreign key (current_revision_id) references task_revision(task_revision_id) deferrable initially deferred;

create table if not exists component_link (
  component_link_id uuid primary key default gen_random_uuid(),
  component_id uuid not null references component(component_id) on delete cascade,
  target_type text not null,
  target_revision_id uuid not null,
  relation_type text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_component_link_target on component_link(target_type, target_revision_id);

-- ========== 考点目录与映射 ==========

create table if not exists checkpoint_catalog (
  catalog_id uuid primary key default gen_random_uuid(),
  subject text not null,
  scope_type text,
  status text not null default 'active',
  created_at timestamptz not null default now()
);

create table if not exists checkpoint_catalog_version (
  catalog_version_id uuid primary key default gen_random_uuid(),
  catalog_id uuid not null references checkpoint_catalog(catalog_id) on delete cascade,
  version_no integer not null,
  status text not null default 'draft',
  base_version_id uuid references checkpoint_catalog_version(catalog_version_id),
  overlay_ref text,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  unique (catalog_id, version_no)
);

create table if not exists checkpoint_node (
  checkpoint_node_id uuid primary key default gen_random_uuid(),
  catalog_version_id uuid not null references checkpoint_catalog_version(catalog_version_id) on delete cascade,
  parent_id uuid references checkpoint_node(checkpoint_node_id) on delete set null,
  code text,
  name text not null,
  node_kind text,
  order_index integer not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists idx_checkpoint_node_catalog_version on checkpoint_node(catalog_version_id, order_index);

create table if not exists source_node_checkpoint_link (
  link_id uuid primary key default gen_random_uuid(),
  source_node_revision_id uuid not null references source_node_revision(source_node_revision_id) on delete cascade,
  checkpoint_node_id uuid not null references checkpoint_node(checkpoint_node_id) on delete cascade,
  relation_type text not null,
  confidence numeric(5,4),
  mapping_source text,
  created_at timestamptz not null default now(),
  unique (source_node_revision_id, checkpoint_node_id, relation_type)
);

create table if not exists task_checkpoint_override (
  override_id uuid primary key default gen_random_uuid(),
  task_revision_id uuid not null references task_revision(task_revision_id) on delete cascade,
  checkpoint_node_id uuid not null references checkpoint_node(checkpoint_node_id) on delete cascade,
  relation_type text not null,
  confidence numeric(5,4),
  mapping_source text,
  reason text,
  created_at timestamptz not null default now(),
  unique (task_revision_id, checkpoint_node_id, relation_type)
);

-- ========== 学科扩展 ==========

create table if not exists task_subject_ext (
  task_revision_id uuid not null references task_revision(task_revision_id) on delete cascade,
  subject text not null,
  plugin_id text not null,
  plugin_version text,
  schema_version text not null,
  payload_json jsonb not null default '{}'::jsonb,
  risk_flags jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (task_revision_id, plugin_id)
);

create index if not exists idx_task_subject_ext_subject on task_subject_ext(subject, plugin_id);

-- ========== 审核、发布、质量 ==========

create table if not exists review_task (
  review_task_id uuid primary key default gen_random_uuid(),
  target_type text not null,
  target_revision_id uuid not null,
  run_id uuid references run(run_id) on delete set null,
  status text not null default 'pending',
  assigned_to text,
  requested_by text,
  changes_summary text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_review_task_status on review_task(status, created_at);
create index if not exists idx_review_task_target on review_task(target_type, target_revision_id);

create table if not exists quality_evaluation (
  quality_evaluation_id uuid primary key default gen_random_uuid(),
  target_type text not null,
  target_revision_id uuid not null,
  rule_set_version text not null,
  check_code text not null,
  severity text not null,
  score numeric(6,2),
  passed boolean not null,
  evidence_ref text,
  evaluated_at timestamptz not null default now()
);

create index if not exists idx_quality_eval_target on quality_evaluation(target_type, target_revision_id);
create index if not exists idx_quality_eval_check on quality_evaluation(rule_set_version, check_code, passed);
