-- TAG-FEEDBACK-01A 只追加教师标签反馈事实，不改写题目、审核或旧 taxonomy assignment。

create table teachbase_app.tagging_run (
  tagging_run_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  external_run_key varchar(240) not null,
  taxonomy_version_id uuid not null,
  model_provider varchar(120) not null,
  model_name varchar(160) not null,
  model_version varchar(160) not null,
  prompt_profile_version varchar(160) not null,
  candidate_package_key varchar(240) not null,
  candidate_package_version varchar(160) not null,
  candidate_package_hash char(64) not null,
  producer_version varchar(160) not null,
  runtime_version varchar(160) not null,
  parameters_json jsonb not null default '{}'::jsonb,
  parameters_hash char(64) not null,
  run_hash char(64) not null,
  status varchar(24) not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  canonical_import_request_id uuid,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_tagging_run_external_key unique (workspace_id, external_run_key),
  constraint uq_tagging_run_scope unique (tagging_run_id, workspace_id, taxonomy_version_id),
  constraint fk_tagging_run_taxonomy foreign key (taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint fk_tagging_run_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_tagging_run_import foreign key (canonical_import_request_id, workspace_id)
    references teachbase_app.canonical_import_request(import_request_id, workspace_id),
  constraint ck_tagging_run_external_key check (length(trim(external_run_key)) > 0),
  constraint ck_tagging_run_model check (
    length(trim(model_provider)) > 0 and length(trim(model_name)) > 0
    and length(trim(model_version)) > 0
  ),
  constraint ck_tagging_run_versions check (
    length(trim(prompt_profile_version)) > 0
    and length(trim(candidate_package_key)) > 0
    and length(trim(candidate_package_version)) > 0
    and length(trim(producer_version)) > 0
    and length(trim(runtime_version)) > 0
  ),
  constraint ck_tagging_run_parameters check (jsonb_typeof(parameters_json) = 'object'),
  constraint ck_tagging_run_hashes check (
    candidate_package_hash ~ '^[0-9a-f]{64}$'
    and parameters_hash ~ '^[0-9a-f]{64}$'
    and run_hash ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_tagging_run_status check (status in ('completed', 'failed')),
  constraint ck_tagging_run_completion check (
    completed_at is not null
  ),
  constraint ck_tagging_run_time_order check (completed_at is null or completed_at >= started_at)
);

create index idx_tagging_run_taxonomy_time
  on teachbase_app.tagging_run(workspace_id, taxonomy_version_id, started_at desc, tagging_run_id);
create index idx_tagging_run_import
  on teachbase_app.tagging_run(canonical_import_request_id)
  where canonical_import_request_id is not null;

create table teachbase_app.question_tag_snapshot (
  snapshot_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  taxonomy_key varchar(120) not null,
  taxonomy_version_id uuid not null,
  snapshot_kind varchar(32) not null,
  label_set_hash char(64) not null,
  snapshot_hash char(64) not null,
  item_count integer not null,
  tagging_run_id uuid,
  model_output_context_json jsonb not null default '{}'::jsonb,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_question_tag_snapshot_hash unique (
    workspace_id, question_revision_id, taxonomy_version_id, snapshot_kind, snapshot_hash
  ),
  constraint uq_question_tag_snapshot_scope unique (
    snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint uq_question_tag_snapshot_taxonomy_scope unique (
    snapshot_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_question_tag_snapshot_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_tag_snapshot_taxonomy foreign key (taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint fk_question_tag_snapshot_run foreign key (tagging_run_id, workspace_id, taxonomy_version_id)
    references teachbase_app.tagging_run(tagging_run_id, workspace_id, taxonomy_version_id),
  constraint fk_question_tag_snapshot_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_tag_snapshot_taxonomy_key check (length(trim(taxonomy_key)) > 0),
  constraint ck_question_tag_snapshot_kind check (
    snapshot_kind in ('SYSTEM_SUGGESTION', 'HUMAN_FINAL')
  ),
  constraint ck_question_tag_snapshot_hashes check (
    label_set_hash ~ '^[0-9a-f]{64}$' and snapshot_hash ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_question_tag_snapshot_item_count check (item_count >= 0),
  constraint ck_question_tag_snapshot_context check (jsonb_typeof(model_output_context_json) = 'object'),
  constraint ck_question_tag_snapshot_run_kind check (
    (snapshot_kind = 'SYSTEM_SUGGESTION' and tagging_run_id is not null)
    or (snapshot_kind = 'HUMAN_FINAL' and tagging_run_id is null)
  )
);

create index idx_question_tag_snapshot_history
  on teachbase_app.question_tag_snapshot(
    workspace_id, question_revision_id, taxonomy_key, created_at, snapshot_id
  );

create table teachbase_app.question_tag_snapshot_item (
  snapshot_item_id uuid primary key,
  snapshot_id uuid not null,
  workspace_id uuid not null,
  taxonomy_version_id uuid not null,
  taxonomy_node_id uuid not null,
  relation_type varchar(24) not null,
  position_index integer not null,
  confidence numeric(8,7),
  candidate_rank integer,
  constraint uq_question_tag_snapshot_item_node unique (snapshot_id, taxonomy_node_id),
  constraint uq_question_tag_snapshot_item_position unique (snapshot_id, relation_type, position_index),
  constraint fk_question_tag_snapshot_item_snapshot foreign key (
    snapshot_id, workspace_id, taxonomy_version_id
  ) references teachbase_app.question_tag_snapshot(snapshot_id, workspace_id, taxonomy_version_id),
  constraint fk_question_tag_snapshot_item_node foreign key (
    taxonomy_node_id, taxonomy_version_id, workspace_id
  ) references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint ck_question_tag_snapshot_item_relation check (relation_type in ('primary', 'secondary')),
  constraint ck_question_tag_snapshot_item_position check (position_index >= 0),
  constraint ck_question_tag_snapshot_item_confidence check (
    confidence is null or confidence between 0 and 1
  ),
  constraint ck_question_tag_snapshot_item_rank check (candidate_rank is null or candidate_rank > 0)
);

-- [jooq ignore start]
create unique index uq_question_tag_snapshot_one_primary
  on teachbase_app.question_tag_snapshot_item(snapshot_id)
  where relation_type = 'primary';
-- [jooq ignore stop]

create table teachbase_app.question_tag_feedback (
  feedback_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  taxonomy_key varchar(120) not null,
  taxonomy_version_id uuid not null,
  before_snapshot_id uuid not null,
  after_snapshot_id uuid,
  outcome varchar(32) not null,
  reason_codes_json jsonb not null default '[]'::jsonb,
  note text not null default '',
  reviewer_id uuid not null,
  submitted_at timestamptz not null default now(),
  client_mutation_id varchar(160) not null,
  request_hash char(64) not null,
  expected_state_version bigint not null,
  derived_operations_json jsonb not null,
  constraint uq_question_tag_feedback_mutation unique (workspace_id, client_mutation_id),
  constraint uq_question_tag_feedback_scope unique (
    feedback_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_question_tag_feedback_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_tag_feedback_taxonomy foreign key (taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint fk_question_tag_feedback_before foreign key (
    before_snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ) references teachbase_app.question_tag_snapshot(
    snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_question_tag_feedback_after foreign key (
    after_snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ) references teachbase_app.question_tag_snapshot(
    snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_question_tag_feedback_actor foreign key (workspace_id, reviewer_id)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_tag_feedback_taxonomy_key check (length(trim(taxonomy_key)) > 0),
  constraint ck_question_tag_feedback_outcome check (
    outcome in ('corrected', 'confirmed', 'taxonomy_gap')
  ),
  constraint ck_question_tag_feedback_reason_codes check (jsonb_typeof(reason_codes_json) = 'array'),
  constraint ck_question_tag_feedback_note check (length(note) <= 10000),
  constraint ck_question_tag_feedback_mutation check (length(trim(client_mutation_id)) > 0),
  constraint ck_question_tag_feedback_request_hash check (request_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_question_tag_feedback_state_version check (expected_state_version >= 0),
  constraint ck_question_tag_feedback_operations check (jsonb_typeof(derived_operations_json) = 'array'),
  constraint ck_question_tag_feedback_after check (after_snapshot_id is not null)
);

create index idx_question_tag_feedback_history
  on teachbase_app.question_tag_feedback(
    workspace_id, question_revision_id, taxonomy_key, submitted_at, feedback_id
  );

create table teachbase_app.question_tag_state (
  state_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  taxonomy_key varchar(120) not null,
  taxonomy_version_id uuid not null,
  current_snapshot_id uuid not null,
  current_feedback_id uuid,
  state_version bigint not null default 0,
  status varchar(32) not null default 'pending',
  updated_by uuid not null,
  updated_at timestamptz not null default now(),
  constraint uq_question_tag_state_key unique (workspace_id, question_revision_id, taxonomy_key),
  constraint fk_question_tag_state_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_tag_state_taxonomy foreign key (taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint fk_question_tag_state_snapshot foreign key (
    current_snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ) references teachbase_app.question_tag_snapshot(
    snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_question_tag_state_feedback foreign key (
    current_feedback_id, question_revision_id, workspace_id, taxonomy_version_id
  ) references teachbase_app.question_tag_feedback(
    feedback_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_question_tag_state_actor foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_tag_state_taxonomy_key check (length(trim(taxonomy_key)) > 0),
  constraint ck_question_tag_state_version check (state_version >= 0),
  constraint ck_question_tag_state_status check (
    status in ('pending', 'reviewed', 'taxonomy_gap', 'needs_reconciliation')
  ),
  constraint ck_question_tag_state_feedback_status check (
    (status = 'pending' and current_feedback_id is null)
    or (status <> 'pending' and current_feedback_id is not null)
  )
);

create index idx_question_tag_state_review_queue
  on teachbase_app.question_tag_state(workspace_id, status, updated_at, state_id);

create table teachbase_app.taxonomy_gap_case (
  gap_case_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  feedback_id uuid not null,
  reported_taxonomy_version_id uuid not null,
  before_snapshot_id uuid not null,
  expected_label_text varchar(1000) not null,
  teacher_explanation text not null,
  status varchar(24) not null default 'open',
  resolved_taxonomy_version_id uuid,
  resolved_taxonomy_node_id uuid,
  resolution_note text,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  resolved_by uuid,
  resolved_at timestamptz,
  constraint uq_taxonomy_gap_feedback unique (feedback_id),
  constraint fk_taxonomy_gap_feedback foreign key (
    feedback_id, question_revision_id, workspace_id, reported_taxonomy_version_id
  ) references teachbase_app.question_tag_feedback(
    feedback_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_taxonomy_gap_before foreign key (
    before_snapshot_id, question_revision_id, workspace_id, reported_taxonomy_version_id
  ) references teachbase_app.question_tag_snapshot(
    snapshot_id, question_revision_id, workspace_id, taxonomy_version_id
  ),
  constraint fk_taxonomy_gap_resolved_node foreign key (
    resolved_taxonomy_node_id, resolved_taxonomy_version_id, workspace_id
  ) references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint fk_taxonomy_gap_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_taxonomy_gap_resolver foreign key (workspace_id, resolved_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_taxonomy_gap_expected_label check (length(trim(expected_label_text)) > 0),
  constraint ck_taxonomy_gap_explanation check (
    length(trim(teacher_explanation)) > 0 and length(teacher_explanation) <= 10000
  ),
  constraint ck_taxonomy_gap_status check (status in ('open', 'triaged', 'resolved', 'rejected')),
  constraint ck_taxonomy_gap_resolution check (
    (status in ('open', 'triaged') and resolved_at is null and resolved_by is null
      and resolved_taxonomy_version_id is null and resolved_taxonomy_node_id is null)
    or (status in ('resolved', 'rejected') and resolved_at is not null and resolved_by is not null)
  )
);

create index idx_taxonomy_gap_queue
  on teachbase_app.taxonomy_gap_case(workspace_id, status, created_at, gap_case_id);

-- [jooq ignore start]
create or replace function teachbase_app.reject_tag_feedback_fact_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'tag_feedback_fact_immutable';
end;
$$;

create or replace function teachbase_app.guard_question_tag_snapshot_item_insert()
returns trigger
language plpgsql
as $$
declare
  expected_count integer;
  current_count integer;
begin
  select item_count into expected_count
  from teachbase_app.question_tag_snapshot
  where snapshot_id = new.snapshot_id
  for update;
  select count(*) into current_count
  from teachbase_app.question_tag_snapshot_item
  where snapshot_id = new.snapshot_id;
  if current_count >= expected_count then
    raise exception 'tag_feedback_snapshot_item_append_forbidden';
  end if;
  return new;
end;
$$;

create or replace function teachbase_app.assert_question_tag_snapshot_complete()
returns trigger
language plpgsql
as $$
begin
  if (select count(*) from teachbase_app.question_tag_snapshot_item
      where snapshot_id = new.snapshot_id) <> new.item_count then
    raise exception 'tag_feedback_snapshot_item_count_mismatch';
  end if;
  return new;
end;
$$;

create trigger trg_tagging_run_immutable
before update or delete on teachbase_app.tagging_run
for each row execute function teachbase_app.reject_tag_feedback_fact_mutation();

create trigger trg_question_tag_snapshot_immutable
before update or delete on teachbase_app.question_tag_snapshot
for each row execute function teachbase_app.reject_tag_feedback_fact_mutation();

create trigger trg_question_tag_snapshot_item_immutable
before update or delete on teachbase_app.question_tag_snapshot_item
for each row execute function teachbase_app.reject_tag_feedback_fact_mutation();

create trigger trg_question_tag_snapshot_item_insert_guard
before insert on teachbase_app.question_tag_snapshot_item
for each row execute function teachbase_app.guard_question_tag_snapshot_item_insert();

create constraint trigger trg_question_tag_snapshot_complete
after insert on teachbase_app.question_tag_snapshot
deferrable initially deferred
for each row execute function teachbase_app.assert_question_tag_snapshot_complete();

create trigger trg_question_tag_feedback_immutable
before update or delete on teachbase_app.question_tag_feedback
for each row execute function teachbase_app.reject_tag_feedback_fact_mutation();
-- [jooq ignore stop]
