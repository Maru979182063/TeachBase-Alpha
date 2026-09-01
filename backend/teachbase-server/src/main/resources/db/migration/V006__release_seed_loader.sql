-- Durable Release Seed orchestration. Domain content remains owned by the file,
-- source, question, review, and taxonomy modules; these tables contain only loader
-- checkpoints and stable package-to-domain mappings.

alter table teachbase_app.source_document
  add column external_source_key varchar(512);
alter table teachbase_app.source_document
  add constraint uq_source_document_external_key unique (workspace_id, external_source_key);

alter table teachbase_app.source_region
  add column external_region_key varchar(512);
alter table teachbase_app.source_region
  add constraint uq_source_region_external_key unique (source_document_id, external_region_key);

create table teachbase_app.release_seed_batch (
  release_seed_batch_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  package_batch_id varchar(240) not null,
  release_version varchar(120) not null,
  package_content_hash char(64) not null,
  taxonomy_version_id uuid not null,
  status varchar(24) not null,
  worker_token uuid,
  lease_expires_at timestamptz,
  attempt_no integer not null default 0,
  next_question_index integer not null default 0,
  question_count integer not null,
  rejected_count integer not null default 0,
  imported_count integer not null default 0,
  reused_count integer not null default 0,
  approved_count integer not null default 0,
  relation_count integer not null default 0,
  package_metadata_json jsonb not null default '{}'::jsonb,
  last_error_json jsonb,
  started_by uuid not null,
  started_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint uq_release_seed_batch_hash unique (workspace_id, package_content_hash),
  constraint uq_release_seed_batch_scope unique (release_seed_batch_id, workspace_id),
  constraint fk_release_seed_actor foreign key (workspace_id, started_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_release_seed_taxonomy foreign key (taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint ck_release_seed_batch_hash check (package_content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_release_seed_batch_status check (status in ('validated', 'importing', 'completed', 'failed')),
  constraint ck_release_seed_batch_counts check (
    question_count >= 0 and rejected_count >= 0 and next_question_index >= 0 and attempt_no >= 0
    and next_question_index <= question_count and imported_count >= 0 and reused_count >= 0
    and approved_count >= 0 and relation_count >= 0
  ),
  constraint ck_release_seed_batch_metadata check (jsonb_typeof(package_metadata_json) = 'object'),
  constraint ck_release_seed_batch_error check (last_error_json is null or jsonb_typeof(last_error_json) = 'object'),
  constraint ck_release_seed_batch_completion check (
    (status = 'completed' and completed_at is not null)
    or (status <> 'completed' and completed_at is null)
  ),
  constraint ck_release_seed_batch_lease check (
    (status = 'importing' and worker_token is not null and lease_expires_at is not null)
    or (status <> 'importing' and worker_token is null and lease_expires_at is null)
  )
);

create index idx_release_seed_batch_status
  on teachbase_app.release_seed_batch(workspace_id, status, updated_at, release_seed_batch_id);

create table teachbase_app.release_seed_item (
  release_seed_batch_id uuid not null,
  workspace_id uuid not null,
  item_index integer not null,
  external_key varchar(240) not null,
  source_system varchar(80) not null,
  source_key varchar(512) not null,
  declared_content_hash char(64) not null,
  question_id uuid,
  question_revision_id uuid,
  review_case_id uuid,
  status varchar(24) not null default 'pending',
  created_question boolean,
  created_revision boolean,
  error_json jsonb,
  processed_at timestamptz,
  primary key (release_seed_batch_id, item_index),
  constraint uq_release_seed_item_external unique (release_seed_batch_id, external_key),
  constraint fk_release_seed_item_batch foreign key (release_seed_batch_id, workspace_id)
    references teachbase_app.release_seed_batch(release_seed_batch_id, workspace_id),
  constraint fk_release_seed_item_question foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_release_seed_item_review foreign key (review_case_id, workspace_id)
    references teachbase_app.review_case(review_case_id, workspace_id),
  constraint ck_release_seed_item_index check (item_index >= 0),
  constraint ck_release_seed_item_hash check (declared_content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_release_seed_item_status check (status in ('pending', 'approved', 'failed')),
  constraint ck_release_seed_item_error check (error_json is null or jsonb_typeof(error_json) = 'object'),
  constraint ck_release_seed_item_result check (
    (status = 'pending' and processed_at is null)
    or (status <> 'pending' and processed_at is not null)
  )
);

create index idx_release_seed_item_status
  on teachbase_app.release_seed_item(release_seed_batch_id, status, item_index);

create table teachbase_app.release_seed_source_document_map (
  release_seed_batch_id uuid not null,
  workspace_id uuid not null,
  source_document_key varchar(512) not null,
  source_document_id uuid not null,
  file_version_id uuid not null,
  asset_sha256 char(64) not null,
  primary key (release_seed_batch_id, source_document_key),
  constraint fk_release_seed_source_batch foreign key (release_seed_batch_id, workspace_id)
    references teachbase_app.release_seed_batch(release_seed_batch_id, workspace_id),
  constraint fk_release_seed_source_document foreign key (source_document_id)
    references teachbase_app.source_document(source_document_id),
  constraint fk_release_seed_source_file foreign key (file_version_id, workspace_id)
    references teachbase_app.file_version(file_version_id, workspace_id),
  constraint ck_release_seed_source_hash check (asset_sha256 ~ '^[0-9a-f]{64}$')
);

create table teachbase_app.release_seed_source_region_map (
  release_seed_batch_id uuid not null,
  workspace_id uuid not null,
  source_region_key varchar(512) not null,
  source_document_key varchar(512) not null,
  source_region_id uuid not null,
  primary key (release_seed_batch_id, source_region_key),
  constraint fk_release_seed_region_batch foreign key (release_seed_batch_id, workspace_id)
    references teachbase_app.release_seed_batch(release_seed_batch_id, workspace_id),
  constraint fk_release_seed_region_source_map foreign key (release_seed_batch_id, source_document_key)
    references teachbase_app.release_seed_source_document_map(release_seed_batch_id, source_document_key),
  constraint fk_release_seed_region foreign key (source_region_id)
    references teachbase_app.source_region(source_region_id)
);
