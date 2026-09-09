-- G5 唯一正式内容收货口：只追加 import ledger、operation DAG 和 editor 稳定导入身份。
-- 领域正文仍由 question/module/editor/handout 各自拥有，本迁移不复制资产表。

alter table teachbase_app.editor_document
  add column import_identity_key varchar(240);

alter table teachbase_app.editor_document
  add constraint ck_editor_import_identity_key check (
    import_identity_key is null or length(trim(import_identity_key)) > 0
  );

create unique index uq_editor_document_import_identity
  on teachbase_app.editor_document(workspace_id, import_identity_key)
  where import_identity_key is not null;

create table teachbase_app.canonical_import_request (
  import_request_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  actor_user_id uuid not null,
  producer varchar(160) not null,
  contract_version varchar(80) not null,
  package_key varchar(240) not null,
  package_hash char(64) not null,
  package_json jsonb not null,
  execution_plan_json jsonb not null,
  status varchar(24) not null,
  operation_count integer not null,
  completed_operation_count integer not null default 0,
  worker_token uuid,
  lease_expires_at timestamptz,
  attempt_no integer not null default 0,
  failure_summary_json jsonb,
  result_fingerprint char(64),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint uq_canonical_import_package_key unique (workspace_id, package_key),
  constraint uq_canonical_import_request_scope unique (import_request_id, workspace_id),
  constraint fk_canonical_import_actor foreign key (workspace_id, actor_user_id)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_canonical_import_producer check (length(trim(producer)) > 0),
  constraint ck_canonical_import_contract check (
    contract_version = 'teachbase.canonical-content-import.v1'
  ),
  constraint ck_canonical_import_package_key check (length(trim(package_key)) > 0),
  constraint ck_canonical_import_package_hash check (package_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_canonical_import_package_json check (jsonb_typeof(package_json) = 'object'),
  constraint ck_canonical_import_plan_json check (jsonb_typeof(execution_plan_json) = 'array'),
  constraint ck_canonical_import_status check (
    status in ('validated', 'importing', 'failed', 'completed')
  ),
  constraint ck_canonical_import_counts check (
    operation_count >= 0 and completed_operation_count between 0 and operation_count
  ),
  constraint ck_canonical_import_attempt check (attempt_no >= 0),
  constraint ck_canonical_import_lease check (
    (status = 'importing' and worker_token is not null and lease_expires_at is not null)
    or (status <> 'importing' and worker_token is null and lease_expires_at is null)
  ),
  constraint ck_canonical_import_failure check (
    failure_summary_json is null or jsonb_typeof(failure_summary_json) = 'object'
  ),
  constraint ck_canonical_import_result_hash check (
    result_fingerprint is null or result_fingerprint ~ '^[0-9a-f]{64}$'
  )
);

create index idx_canonical_import_status
  on teachbase_app.canonical_import_request(workspace_id, status, updated_at, import_request_id);
create index idx_canonical_import_expired_lease
  on teachbase_app.canonical_import_request(lease_expires_at)
  where status = 'importing';

create table teachbase_app.canonical_import_operation (
  import_operation_id uuid primary key,
  import_request_id uuid not null,
  workspace_id uuid not null,
  operation_key varchar(320) not null,
  operation_type varchar(48) not null,
  sequence_no integer not null,
  dependencies_json jsonb not null default '[]'::jsonb,
  payload_json jsonb not null,
  payload_hash char(64) not null,
  status varchar(24) not null default 'pending',
  attempt_no integer not null default 0,
  target_id uuid,
  target_revision_id uuid,
  target_hash char(64),
  result_json jsonb,
  error_json jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint uq_canonical_import_operation_key unique (import_request_id, operation_key),
  constraint uq_canonical_import_operation_sequence unique (import_request_id, sequence_no),
  constraint uq_canonical_import_operation_scope unique (import_operation_id, import_request_id, workspace_id),
  constraint fk_canonical_import_operation_request foreign key (import_request_id, workspace_id)
    references teachbase_app.canonical_import_request(import_request_id, workspace_id),
  constraint ck_canonical_import_operation_key check (length(trim(operation_key)) > 0),
  constraint ck_canonical_import_operation_type check (operation_type in (
    'file_reference', 'source_document', 'source_region',
    'question_revision', 'question_provenance',
    'standard_module_revision', 'standard_module_provenance', 'standard_module_file',
    'taxonomy_assignment', 'review_intent', 'editor_revision', 'handout_composition'
  )),
  constraint ck_canonical_import_operation_sequence check (sequence_no >= 0),
  constraint ck_canonical_import_operation_dependencies check (jsonb_typeof(dependencies_json) = 'array'),
  constraint ck_canonical_import_operation_payload check (jsonb_typeof(payload_json) = 'object'),
  constraint ck_canonical_import_operation_payload_hash check (payload_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_canonical_import_operation_status check (
    status in ('pending', 'running', 'failed', 'completed')
  ),
  constraint ck_canonical_import_operation_attempt check (attempt_no >= 0),
  constraint ck_canonical_import_operation_target_hash check (
    target_hash is null or target_hash ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_canonical_import_operation_result check (
    result_json is null or jsonb_typeof(result_json) = 'object'
  ),
  constraint ck_canonical_import_operation_error check (
    error_json is null or jsonb_typeof(error_json) = 'object'
  ),
  constraint ck_canonical_import_operation_completed check (
    status <> 'completed' or (completed_at is not null and result_json is not null)
  )
);

create index idx_canonical_import_operation_frontier
  on teachbase_app.canonical_import_operation(import_request_id, status, sequence_no);
create index idx_canonical_import_operation_target
  on teachbase_app.canonical_import_operation(workspace_id, operation_type, target_id, target_revision_id)
  where status = 'completed';

-- [jooq ignore start]
create or replace function teachbase_app.protect_canonical_import_request_identity()
returns trigger
language plpgsql
as $$
begin
  if row(old.workspace_id, old.actor_user_id, old.producer, old.contract_version, old.package_key,
         old.package_hash, old.package_json, old.execution_plan_json, old.operation_count,
         old.created_at)
     is distinct from
     row(new.workspace_id, new.actor_user_id, new.producer, new.contract_version, new.package_key,
         new.package_hash, new.package_json, new.execution_plan_json, new.operation_count,
         new.created_at) then
    raise exception 'canonical_import_request_identity_immutable';
  end if;
  return new;
end;
$$;

create trigger trg_canonical_import_request_identity_immutable
before update on teachbase_app.canonical_import_request
for each row execute function teachbase_app.protect_canonical_import_request_identity();

create or replace function teachbase_app.protect_completed_import_operation()
returns trigger
language plpgsql
as $$
begin
  if row(old.import_request_id, old.workspace_id, old.operation_key, old.operation_type,
       old.sequence_no, old.dependencies_json, old.payload_json, old.payload_hash)
     is distinct from row(new.import_request_id, new.workspace_id, new.operation_key, new.operation_type,
       new.sequence_no, new.dependencies_json, new.payload_json, new.payload_hash) then
    raise exception 'canonical_import_operation_plan_immutable';
  end if;
  if old.status = 'completed' and row(
       old.target_id, old.target_revision_id, old.target_hash,
       old.result_json, old.completed_at
     ) is distinct from row(
       new.target_id, new.target_revision_id, new.target_hash,
       new.result_json, new.completed_at
     ) then
    raise exception 'canonical_import_completed_operation_immutable';
  end if;
  return new;
end;
$$;

create trigger trg_canonical_import_completed_operation_immutable
before update on teachbase_app.canonical_import_operation
for each row execute function teachbase_app.protect_completed_import_operation();

create or replace function teachbase_app.reject_canonical_import_ledger_delete()
returns trigger
language plpgsql
as $$
begin
  raise exception 'canonical_import_ledger_delete_forbidden';
end;
$$;

create trigger trg_canonical_import_request_delete_forbidden
before delete on teachbase_app.canonical_import_request
for each row execute function teachbase_app.reject_canonical_import_ledger_delete();

create trigger trg_canonical_import_operation_delete_forbidden
before delete on teachbase_app.canonical_import_operation
for each row execute function teachbase_app.reject_canonical_import_ledger_delete();
-- [jooq ignore stop]
