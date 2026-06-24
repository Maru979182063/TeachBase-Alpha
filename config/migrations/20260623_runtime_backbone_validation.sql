-- 用途：
-- - 创建运行时主干完整性检查所需的校验、审计和模糊匹配结构。
-- - 运行时数据模型变化时，这个文件需要和就绪检查一起更新。

-- Validation-scope schema for the runtime backbone.
-- This keeps the same facts that FileStore already exposes, while reserving
-- enough normalized tables for import, search, publication, material build,
-- component rerun, and recovery verification.

create extension if not exists pg_trgm;

create table if not exists runtime_state_snapshot (
  snapshot_key text primary key,
  snapshot_json jsonb not null,
  snapshot_version integer not null default 1,
  snapshot_content_hash text,
  updated_at timestamptz not null default now()
);

alter table if exists runtime_state_snapshot
  add column if not exists snapshot_version integer not null default 1;

alter table if exists runtime_state_snapshot
  add column if not exists snapshot_content_hash text;

create table if not exists document (
  document_id text primary key,
  source_id text,
  subject text,
  stage text,
  grade text,
  season text,
  doc_role text,
  title text,
  storage_uri text,
  checksum text,
  page_count integer,
  status text,
  metadata_json jsonb,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists lesson (
  lesson_id text primary key,
  document_group_id text,
  subject text,
  stage text,
  grade text,
  season text,
  title text,
  active_revision_id text,
  published_revision_id text,
  status text,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists lesson_revision (
  lesson_revision_id text primary key,
  lesson_id text not null,
  base_artifact_id text,
  generated_snapshot_ref text,
  manual_patch_ref text,
  merged_snapshot_ref text,
  revision_no integer not null,
  status text,
  approval_status text,
  bundle_jsonb jsonb,
  content_hash text,
  created_by text,
  created_at timestamptz
);

create table if not exists task_projection (
  task_projection_id text primary key,
  lesson_id text not null,
  lesson_revision_id text not null,
  local_task_id text not null,
  source_node_local_id text,
  subject text,
  grade text,
  question_type text,
  stem text,
  answer text,
  explanation text,
  difficulty_level text,
  difficulty_scheme text,
  difficulty_source text,
  difficulty_confidence numeric,
  checkpoint_codes text[] default '{}',
  subject_tags text[] default '{}',
  source_refs_json jsonb,
  content_hash text,
  search_text text,
  search_vector tsvector generated always as (
    to_tsvector('simple', coalesce(search_text, ''))
  ) stored,
  created_at timestamptz,
  unique (lesson_revision_id, local_task_id)
);
create index if not exists idx_task_projection_subject on task_projection (subject);
create index if not exists idx_task_projection_grade on task_projection (grade);
create index if not exists idx_task_projection_question_type on task_projection (question_type);
create index if not exists idx_task_projection_difficulty_level on task_projection (difficulty_level);
create index if not exists idx_task_projection_checkpoint_codes on task_projection using gin (checkpoint_codes);
create index if not exists idx_task_projection_search_vector on task_projection using gin (search_vector);

create table if not exists question_bank_item (
  question_bank_item_id text primary key,
  subject text,
  grade text,
  current_revision_id text,
  status text,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists question_bank_item_revision (
  question_bank_item_revision_id text primary key,
  question_bank_item_id text not null,
  stem text,
  answer text,
  explanation text,
  question_type text,
  difficulty_level text,
  difficulty_scheme text,
  difficulty_source text,
  difficulty_confidence numeric,
  checkpoint_codes text[] default '{}',
  subject_tags text[] default '{}',
  source_refs_json jsonb,
  content_hash text,
  search_text text,
  search_vector tsvector generated always as (
    to_tsvector('simple', coalesce(search_text, ''))
  ) stored,
  created_at timestamptz,
  created_by text
);
create index if not exists idx_question_bank_revision_search_vector
  on question_bank_item_revision using gin (search_vector);
create index if not exists idx_question_bank_revision_checkpoint_codes
  on question_bank_item_revision using gin (checkpoint_codes);

create table if not exists question_bank_source_link (
  question_bank_source_link_id text primary key,
  question_bank_item_revision_id text not null,
  lesson_id text,
  lesson_revision_id text,
  local_task_id text,
  source_node_local_id text,
  source_refs_json jsonb,
  created_at timestamptz
);

create table if not exists review_task (
  review_task_id text primary key,
  target_type text not null,
  target_revision_id text not null,
  run_id text,
  status text not null,
  assigned_to text,
  requested_by text,
  changes_summary text,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists publication (
  publication_id text primary key,
  lesson_id text not null,
  lesson_revision_id text not null,
  status text not null,
  published_artifact_id text,
  material_build_id text,
  created_by text,
  created_at timestamptz,
  published_at timestamptz,
  revoked_at timestamptz,
  superseded_by_publication_id text
);

create table if not exists material_build (
  material_build_id text primary key,
  lesson_id text,
  teacher_name text,
  build_name text,
  section_schema jsonb,
  target_variant text,
  status text,
  created_by text,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists material_item (
  material_item_id text primary key,
  material_build_id text not null,
  question_bank_item_revision_id text not null,
  section_key text,
  placement_role text,
  target_variant text,
  sort_index integer,
  difficulty_override text,
  include_answer boolean,
  include_explanation boolean,
  layout_hint_json jsonb,
  created_at timestamptz
);

create table if not exists page_asset (
  page_asset_id text primary key,
  document_id text,
  page_no integer,
  width integer,
  height integer,
  image_artifact_id text,
  ocr_artifact_id text,
  layout_artifact_id text,
  status text,
  created_at timestamptz
);

create table if not exists component (
  component_id text primary key,
  page_asset_id text,
  parent_component_id text,
  component_type text,
  bbox_json jsonb,
  reading_order integer,
  crop_artifact_id text,
  content_hash text,
  schema_version text,
  extraction_confidence numeric,
  status text,
  current_revision_id text,
  created_at timestamptz
);

create table if not exists component_revision (
  component_revision_id text primary key,
  component_id text not null,
  source_task_revision_id text,
  page_no integer,
  bbox_json jsonb,
  extracted_text text,
  source_refs_json jsonb,
  created_by text,
  created_at timestamptz
);

create table if not exists component_patch_candidate (
  component_patch_candidate_id text primary key,
  component_id text not null,
  base_component_revision_id text not null,
  proposed_component_revision_id text not null,
  target_task_revision_id text,
  run_id text,
  status text not null,
  diff_json jsonb,
  created_at timestamptz,
  updated_at timestamptz,
  reviewed_by text,
  accepted_lesson_revision_id text
);

create table if not exists run (
  run_id text primary key,
  run_type text not null,
  root_target_type text,
  root_target_id text,
  subject text,
  lane text,
  status text,
  triggered_by text,
  started_at timestamptz,
  finished_at timestamptz
);

create table if not exists job (
  job_id text primary key,
  run_id text not null,
  job_type text not null,
  lane text,
  capability text,
  resource_class text,
  priority integer,
  idempotency_key text,
  status text,
  attempt_count integer,
  max_attempts integer,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  timeout_at timestamptz,
  cancel_requested_at timestamptz,
  next_retry_at timestamptz,
  error_code text,
  error_detail_ref text,
  payload_ref text,
  result_artifact_id text,
  created_at timestamptz,
  updated_at timestamptz
);
create index if not exists idx_job_idempotency_key on job (idempotency_key);
create index if not exists idx_job_status on job (status);

create table if not exists job_attempt (
  job_attempt_id text primary key,
  job_id text not null,
  attempt_no integer not null,
  started_at timestamptz,
  heartbeat_at timestamptz,
  finished_at timestamptz,
  status text,
  error_detail_json jsonb,
  worker_ref text
);

create table if not exists artifact (
  artifact_id text primary key,
  run_id text,
  job_id text,
  artifact_type text not null,
  schema_version text,
  producer_name text,
  producer_version text,
  model_version text,
  prompt_hash text,
  plugin_version text,
  storage_uri text,
  content_hash text,
  summary_json jsonb,
  supersedes_artifact_id text,
  integrity_status text,
  logical_status text,
  lifecycle_status text,
  created_at timestamptz
);

create table if not exists artifact_dependency (
  artifact_dependency_id text primary key,
  parent_artifact_id text not null,
  child_artifact_id text not null,
  dependency_type text,
  created_at timestamptz
);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'uq_lesson_revision_lesson_revision_no'
  ) then
    alter table lesson_revision
      add constraint uq_lesson_revision_lesson_revision_no unique (lesson_id, revision_no);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'uq_job_attempt_job_attempt_no'
  ) then
    alter table job_attempt
      add constraint uq_job_attempt_job_attempt_no unique (job_id, attempt_no);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_review_task_status'
  ) then
    alter table review_task
      add constraint ck_review_task_status
      check (status in ('pending', 'in_review', 'approved', 'changes_requested', 'rejected', 'published'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_publication_status'
  ) then
    alter table publication
      add constraint ck_publication_status
      check (status in ('preparing', 'published', 'failed', 'revoked', 'superseded'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_job_status'
  ) then
    alter table job
      add constraint ck_job_status
      check (status in ('queued', 'running', 'succeeded', 'failed', 'retry_wait', 'cancelled'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_task_projection_difficulty_confidence'
  ) then
    alter table task_projection
      add constraint ck_task_projection_difficulty_confidence
      check (difficulty_confidence is null or (difficulty_confidence >= 0 and difficulty_confidence <= 1));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_question_bank_revision_difficulty_confidence'
  ) then
    alter table question_bank_item_revision
      add constraint ck_question_bank_revision_difficulty_confidence
      check (difficulty_confidence is null or (difficulty_confidence >= 0 and difficulty_confidence <= 1));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_component_extraction_confidence'
  ) then
    alter table component
      add constraint ck_component_extraction_confidence
      check (extraction_confidence is null or (extraction_confidence >= 0 and extraction_confidence <= 1));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_material_item_sort_index'
  ) then
    alter table material_item
      add constraint ck_material_item_sort_index
      check (sort_index is null or sort_index > 0);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_lesson_revision_lesson'
  ) then
    alter table lesson_revision
      add constraint fk_lesson_revision_lesson
      foreign key (lesson_id) references lesson(lesson_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_task_projection_lesson'
  ) then
    alter table task_projection
      add constraint fk_task_projection_lesson
      foreign key (lesson_id) references lesson(lesson_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_task_projection_lesson_revision'
  ) then
    alter table task_projection
      add constraint fk_task_projection_lesson_revision
      foreign key (lesson_revision_id) references lesson_revision(lesson_revision_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_question_bank_revision_item'
  ) then
    alter table question_bank_item_revision
      add constraint fk_question_bank_revision_item
      foreign key (question_bank_item_id) references question_bank_item(question_bank_item_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_question_bank_source_link_revision'
  ) then
    alter table question_bank_source_link
      add constraint fk_question_bank_source_link_revision
      foreign key (question_bank_item_revision_id)
      references question_bank_item_revision(question_bank_item_revision_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_publication_lesson'
  ) then
    alter table publication
      add constraint fk_publication_lesson
      foreign key (lesson_id) references lesson(lesson_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_publication_lesson_revision'
  ) then
    alter table publication
      add constraint fk_publication_lesson_revision
      foreign key (lesson_revision_id) references lesson_revision(lesson_revision_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_material_build_lesson'
  ) then
    alter table material_build
      add constraint fk_material_build_lesson
      foreign key (lesson_id) references lesson(lesson_id) on delete set null;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_material_item_build'
  ) then
    alter table material_item
      add constraint fk_material_item_build
      foreign key (material_build_id) references material_build(material_build_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_material_item_question_revision'
  ) then
    alter table material_item
      add constraint fk_material_item_question_revision
      foreign key (question_bank_item_revision_id)
      references question_bank_item_revision(question_bank_item_revision_id);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_page_asset_document'
  ) then
    alter table page_asset
      add constraint fk_page_asset_document
      foreign key (document_id) references document(document_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_component_page_asset'
  ) then
    alter table component
      add constraint fk_component_page_asset
      foreign key (page_asset_id) references page_asset(page_asset_id) on delete cascade;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_component_revision_component'
  ) then
    alter table component_revision
      add constraint fk_component_revision_component
      foreign key (component_id) references component(component_id) on delete cascade;
  end if;
end $$;
