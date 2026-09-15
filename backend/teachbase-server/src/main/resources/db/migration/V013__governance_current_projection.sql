-- GOVERNANCE-PROJECTION-01：只追加可重建读模型与事务 outbox，不改写任何治理事实。

create table teachbase_app.question_tag_current_projection (
  projection_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  question_id uuid not null,
  question_revision_id uuid not null,
  taxonomy_key varchar(120) not null,
  taxonomy_version_id uuid not null,
  current_snapshot_id uuid not null,
  primary_node_id uuid,
  decision_source varchar(32) not null,
  tag_status varchar(32) not null,
  authority_state_version bigint not null,
  label_set_hash char(64) not null,
  projection_semantic_hash char(64) not null,
  projected_at timestamptz not null default now(),
  constraint uq_tag_current_projection_key unique (
    workspace_id, question_revision_id, taxonomy_key
  ),
  constraint uq_tag_current_projection_scope unique (projection_id, workspace_id),
  constraint fk_tag_current_projection_revision foreign key (
    question_revision_id, question_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_tag_current_projection_taxonomy foreign key (
    taxonomy_version_id, workspace_id
  ) references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint fk_tag_current_projection_snapshot foreign key (
    current_snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ) references teachbase_app.question_tag_snapshot(
    snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_tag_current_projection_primary foreign key (
    primary_node_id, taxonomy_version_id, workspace_id
  ) references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint ck_tag_current_projection_key check (length(trim(taxonomy_key)) > 0),
  constraint ck_tag_current_projection_source check (
    decision_source in ('SYSTEM_SUGGESTION', 'HUMAN_FINAL')
  ),
  constraint ck_tag_current_projection_status check (
    tag_status in ('pending', 'reviewed', 'taxonomy_gap', 'needs_reconciliation')
  ),
  constraint ck_tag_current_projection_version check (authority_state_version >= 0),
  constraint ck_tag_current_projection_hashes check (
    label_set_hash ~ '^[0-9a-f]{64}$'
    and projection_semantic_hash ~ '^[0-9a-f]{64}$'
  )
);

create index idx_tag_current_projection_primary
  on teachbase_app.question_tag_current_projection(
    workspace_id, taxonomy_key, primary_node_id, question_revision_id
  );
create index idx_tag_current_projection_revision
  on teachbase_app.question_tag_current_projection(workspace_id, question_revision_id);

create table teachbase_app.question_tag_current_projection_secondary (
  projection_id uuid not null,
  workspace_id uuid not null,
  taxonomy_version_id uuid not null,
  taxonomy_node_id uuid not null,
  position_index integer not null,
  primary key (projection_id, taxonomy_node_id),
  constraint uq_tag_current_projection_secondary_position unique (projection_id, position_index),
  constraint fk_tag_current_projection_secondary_parent foreign key (projection_id, workspace_id)
    references teachbase_app.question_tag_current_projection(projection_id, workspace_id)
    on delete cascade,
  constraint fk_tag_current_projection_secondary_node foreign key (
    taxonomy_node_id, taxonomy_version_id, workspace_id
  ) references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint ck_tag_current_projection_secondary_position check (position_index >= 0)
);

create index idx_tag_current_projection_secondary_node
  on teachbase_app.question_tag_current_projection_secondary(
    workspace_id, taxonomy_node_id, projection_id
  );

create table teachbase_app.question_difficulty_current_projection (
  projection_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  question_id uuid not null,
  question_revision_id uuid not null,
  rubric_key varchar(120) not null,
  rubric_version_id uuid not null,
  context_key varchar(160) not null,
  context_hash char(64) not null,
  current_snapshot_id uuid not null,
  difficulty_value smallint,
  decision_source varchar(32) not null,
  difficulty_status varchar(32) not null,
  authority_state_version bigint not null,
  projection_semantic_hash char(64) not null,
  projected_at timestamptz not null default now(),
  constraint uq_difficulty_current_projection_key unique (
    workspace_id, question_revision_id, rubric_key, context_key
  ),
  constraint uq_difficulty_current_projection_scope unique (projection_id, workspace_id),
  constraint fk_difficulty_current_projection_revision foreign key (
    question_revision_id, question_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_difficulty_current_projection_rubric foreign key (
    rubric_version_id, workspace_id, rubric_key
  ) references teachbase_app.difficulty_rubric_version(rubric_version_id, workspace_id, rubric_key),
  constraint fk_difficulty_current_projection_snapshot foreign key (
    current_snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_snapshot(
    snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint ck_difficulty_current_projection_keys check (
    length(trim(rubric_key)) > 0 and length(trim(context_key)) > 0
  ),
  constraint ck_difficulty_current_projection_value check (
    difficulty_value is null or difficulty_value between 1 and 5
  ),
  constraint ck_difficulty_current_projection_source check (
    decision_source in ('SYSTEM_SUGGESTION', 'HUMAN_FINAL')
  ),
  constraint ck_difficulty_current_projection_status check (
    difficulty_status in ('pending', 'reviewed', 'rubric_gap', 'needs_reconciliation')
  ),
  constraint ck_difficulty_current_projection_version check (authority_state_version >= 0),
  constraint ck_difficulty_current_projection_hashes check (
    context_hash ~ '^[0-9a-f]{64}$'
    and projection_semantic_hash ~ '^[0-9a-f]{64}$'
  )
);

create index idx_difficulty_current_projection_value
  on teachbase_app.question_difficulty_current_projection(
    workspace_id, rubric_key, context_key, difficulty_value, question_revision_id
  );
create index idx_difficulty_current_projection_revision
  on teachbase_app.question_difficulty_current_projection(workspace_id, question_revision_id);

create table teachbase_app.governance_projection_outbox (
  event_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  question_revision_id uuid not null,
  domain varchar(24) not null,
  authority_state_id uuid not null,
  authority_state_version bigint not null,
  event_key char(64) not null,
  status varchar(24) not null default 'pending',
  attempt_count integer not null default 0,
  available_at timestamptz not null default now(),
  lease_owner varchar(160),
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  processed_at timestamptz,
  last_error varchar(2000),
  constraint uq_governance_projection_outbox_event_key unique (event_key),
  constraint uq_governance_projection_outbox_state unique (
    domain, authority_state_id, authority_state_version
  ),
  constraint fk_governance_projection_outbox_revision foreign key (
    question_revision_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, workspace_id),
  constraint ck_governance_projection_outbox_domain check (domain in ('TAG', 'DIFFICULTY')),
  constraint ck_governance_projection_outbox_version check (authority_state_version >= 0),
  constraint ck_governance_projection_outbox_event_key check (event_key ~ '^[0-9a-f]{64}$'),
  constraint ck_governance_projection_outbox_status check (
    status in ('pending', 'processing', 'failed', 'processed')
  ),
  constraint ck_governance_projection_outbox_attempt check (attempt_count >= 0),
  constraint ck_governance_projection_outbox_lease check (
    (status = 'processing' and lease_owner is not null and lease_until is not null)
    or (status <> 'processing' and lease_owner is null and lease_until is null)
  ),
  constraint ck_governance_projection_outbox_processed check (
    (status = 'processed' and processed_at is not null)
    or (status <> 'processed' and processed_at is null)
  )
);

create index idx_governance_projection_outbox_claim
  on teachbase_app.governance_projection_outbox(status, available_at, created_at, event_id)
  where status in ('pending', 'failed');
create index idx_governance_projection_outbox_expired
  on teachbase_app.governance_projection_outbox(lease_until, event_id)
  where status = 'processing';
create index idx_governance_projection_outbox_workspace
  on teachbase_app.governance_projection_outbox(workspace_id, status, created_at);

-- [jooq ignore start]
create or replace function teachbase_app.guard_governance_projection_write()
returns trigger
language plpgsql
as $$
begin
  if coalesce(current_setting('teachbase.governance_projection_writer', true), '') <> 'on' then
    raise exception 'governance_projection_direct_write_forbidden';
  end if;
  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;

create trigger trg_tag_current_projection_writer_guard
before insert or update or delete on teachbase_app.question_tag_current_projection
for each row execute function teachbase_app.guard_governance_projection_write();

create trigger trg_tag_current_projection_secondary_writer_guard
before insert or update or delete on teachbase_app.question_tag_current_projection_secondary
for each row execute function teachbase_app.guard_governance_projection_write();

create trigger trg_difficulty_current_projection_writer_guard
before insert or update or delete on teachbase_app.question_difficulty_current_projection
for each row execute function teachbase_app.guard_governance_projection_write();

create or replace function teachbase_app.enqueue_governance_projection_event()
returns trigger
language plpgsql
as $$
declare
  event_domain varchar(24);
  material text;
  stable_key char(64);
begin
  if tg_table_name = 'question_tag_state' then
    event_domain := 'TAG';
  elsif tg_table_name = 'question_difficulty_state' then
    event_domain := 'DIFFICULTY';
  else
    raise exception 'governance_projection_authority_unknown';
  end if;

  material := event_domain || ':' || new.state_id::text || ':' || new.state_version::text;
  stable_key := md5(material) || md5('event:' || material);
  insert into teachbase_app.governance_projection_outbox(
    event_id, workspace_id, question_revision_id, domain, authority_state_id,
    authority_state_version, event_key, status, available_at, created_at
  ) values (
    md5(stable_key)::uuid, new.workspace_id, new.question_revision_id, event_domain,
    new.state_id, new.state_version, stable_key, 'pending', now(), now()
  ) on conflict (domain, authority_state_id, authority_state_version) do nothing;
  return new;
end;
$$;

create trigger trg_question_tag_state_projection_outbox
after insert or update of current_snapshot_id, state_version, status, taxonomy_version_id
on teachbase_app.question_tag_state
for each row execute function teachbase_app.enqueue_governance_projection_event();

create trigger trg_question_difficulty_state_projection_outbox
after insert or update of current_snapshot_id, state_version, status, rubric_version_id
on teachbase_app.question_difficulty_state
for each row execute function teachbase_app.enqueue_governance_projection_event();
-- [jooq ignore stop]

-- 升级时为既有 authority state 生成可重放事件；不把 legacy 字段提升为 authority。
-- [jooq ignore start]
insert into teachbase_app.governance_projection_outbox(
  event_id, workspace_id, question_revision_id, domain, authority_state_id,
  authority_state_version, event_key, status, available_at, created_at
)
select md5(keys.event_key)::uuid, states.workspace_id, states.question_revision_id,
       'TAG', states.state_id, states.state_version, keys.event_key, 'pending', now(), now()
from teachbase_app.question_tag_state states
cross join lateral (
  select (md5('TAG:' || states.state_id::text || ':' || states.state_version::text)
    || md5('event:TAG:' || states.state_id::text || ':' || states.state_version::text))::char(64)
    as event_key
) keys
on conflict (domain, authority_state_id, authority_state_version) do nothing;

insert into teachbase_app.governance_projection_outbox(
  event_id, workspace_id, question_revision_id, domain, authority_state_id,
  authority_state_version, event_key, status, available_at, created_at
)
select md5(keys.event_key)::uuid, states.workspace_id, states.question_revision_id,
       'DIFFICULTY', states.state_id, states.state_version, keys.event_key, 'pending', now(), now()
from teachbase_app.question_difficulty_state states
cross join lateral (
  select (md5('DIFFICULTY:' || states.state_id::text || ':' || states.state_version::text)
    || md5('event:DIFFICULTY:' || states.state_id::text || ':' || states.state_version::text))::char(64)
    as event_key
) keys
on conflict (domain, authority_state_id, authority_state_version) do nothing;
-- [jooq ignore stop]
