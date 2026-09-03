-- Promote export_request into a durable PostgreSQL work queue. Workers own leases,
-- renew them with heartbeats, and permit recovery after process failure.
alter table teachbase_app.export_request
  drop constraint ck_export_request_status;

alter table teachbase_app.export_request
  add column attempt_count integer not null default 0,
  add column max_attempts integer not null default 3,
  add column available_at timestamptz not null default now(),
  add column worker_id varchar(160),
  add column claimed_at timestamptz,
  add column heartbeat_at timestamptz,
  add column lease_expires_at timestamptz,
  add column render_source_schema_version integer,
  add column render_source_json jsonb,
  add column render_source_hash char(64),
  add column output_storage_key varchar(1024),
  add constraint ck_export_request_status check (
    status in ('queued', 'running', 'completed', 'failed_retryable', 'failed_final', 'cancelled')
  ),
  add constraint ck_export_attempt_count check (attempt_count >= 0 and max_attempts between 1 and 20),
  add constraint ck_export_render_source check (
    (render_source_schema_version is null and render_source_json is null and render_source_hash is null)
    or (
      render_source_schema_version = 1
      and jsonb_typeof(render_source_json) = 'object'
      and render_source_hash ~ '^[0-9a-f]{64}$'
    )
  ),
  add constraint ck_export_output_storage_key check (
    output_storage_key is null
    or (
      length(trim(output_storage_key)) > 0
      and left(output_storage_key, 1) <> '/'
      and position(':' in output_storage_key) = 0
      and position(chr(92) in output_storage_key) = 0
      and output_storage_key not like '../%'
      and output_storage_key not like '%/../%'
      and output_storage_key <> '..'
    )
  );

-- Queue scans lead with availability so workers skip delayed retry work.
drop index teachbase_app.idx_export_request_queue;

create index idx_export_request_queue
  on teachbase_app.export_request(status, available_at, requested_at);

-- Partial index bounds expired-lease recovery to running work only.
create index idx_export_request_lease
  on teachbase_app.export_request(status, lease_expires_at)
  where status = 'running';

-- Immutable attempt history for retries, metrics, and incident reconstruction.
create table teachbase_app.export_attempt (
  export_attempt_id uuid primary key,
  export_request_id uuid not null,
  workspace_id uuid not null,
  attempt_no integer not null,
  worker_id varchar(160) not null,
  status varchar(24) not null,
  started_at timestamptz not null default now(),
  heartbeat_at timestamptz not null default now(),
  finished_at timestamptz,
  renderer_version varchar(120),
  render_source_hash char(64),
  output_sha256 char(64),
  error_json jsonb,
  constraint uq_export_attempt_number unique (export_request_id, attempt_no),
  constraint uq_export_attempt_scope unique (export_attempt_id, export_request_id, workspace_id),
  constraint fk_export_attempt_request foreign key (export_request_id, workspace_id)
    references teachbase_app.export_request(export_request_id, workspace_id),
  constraint ck_export_attempt_number check (attempt_no > 0),
  constraint ck_export_attempt_worker check (length(trim(worker_id)) > 0),
  constraint ck_export_attempt_status check (
    status in ('running', 'completed', 'failed_retryable', 'failed_final', 'abandoned')
  ),
  constraint ck_export_attempt_source_hash check (
    render_source_hash is null or render_source_hash ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_export_attempt_output_hash check (
    output_sha256 is null or output_sha256 ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_export_attempt_error check (error_json is null or jsonb_typeof(error_json) = 'object')
);

create index idx_export_attempt_request
  on teachbase_app.export_attempt(export_request_id, attempt_no desc);
