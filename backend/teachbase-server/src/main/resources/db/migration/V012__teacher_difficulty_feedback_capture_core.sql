-- DIFFICULTY-FEEDBACK-01A 只追加难度评估事实；不改写题目 revision、Review 或旧 difficulty_stars。

create table teachbase_app.difficulty_rubric_version (
  rubric_version_id uuid primary key,
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  rubric_key varchar(120) not null,
  version_code varchar(80) not null,
  subject varchar(80) not null,
  stage varchar(80) not null,
  grade varchar(80),
  scale_min smallint not null default 1,
  scale_max smallint not null default 5,
  definitions_json jsonb not null,
  rubric_hash char(64) not null,
  status varchar(24) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_difficulty_rubric_version unique (workspace_id, rubric_key, version_code),
  constraint uq_difficulty_rubric_scope unique (rubric_version_id, workspace_id, rubric_key),
  constraint fk_difficulty_rubric_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_difficulty_rubric_key check (length(trim(rubric_key)) > 0),
  constraint ck_difficulty_rubric_version check (length(trim(version_code)) > 0),
  constraint ck_difficulty_rubric_context check (
    length(trim(subject)) > 0 and length(trim(stage)) > 0
  ),
  constraint ck_difficulty_rubric_scale check (scale_min = 1 and scale_max = 5),
  constraint ck_difficulty_rubric_definitions check (jsonb_typeof(definitions_json) = 'object'),
  constraint ck_difficulty_rubric_hash check (rubric_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_difficulty_rubric_status check (status in ('active', 'retired'))
);

create index idx_difficulty_rubric_lookup
  on teachbase_app.difficulty_rubric_version(workspace_id, subject, stage, grade, rubric_key, created_at desc);

create table teachbase_app.difficulty_assessment_run (
  assessment_run_id uuid primary key,
  workspace_id uuid not null,
  external_run_key varchar(240) not null,
  rubric_key varchar(120) not null,
  rubric_version_id uuid not null,
  model_provider varchar(120) not null,
  model_name varchar(160) not null,
  model_version varchar(160) not null,
  prompt_profile_version varchar(160) not null,
  evidence_package_key varchar(240) not null,
  evidence_package_version varchar(160) not null,
  evidence_package_hash char(64) not null,
  producer_version varchar(160) not null,
  runtime_version varchar(160) not null,
  parameters_json jsonb not null default '{}'::jsonb,
  parameters_hash char(64) not null,
  run_hash char(64) not null,
  status varchar(24) not null,
  started_at timestamptz not null,
  completed_at timestamptz not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_difficulty_run_external unique (workspace_id, external_run_key),
  constraint uq_difficulty_run_scope unique (
    assessment_run_id, workspace_id, rubric_version_id, rubric_key
  ),
  constraint fk_difficulty_run_rubric foreign key (rubric_version_id, workspace_id, rubric_key)
    references teachbase_app.difficulty_rubric_version(rubric_version_id, workspace_id, rubric_key),
  constraint fk_difficulty_run_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_difficulty_run_external check (length(trim(external_run_key)) > 0),
  constraint ck_difficulty_run_model check (
    length(trim(model_provider)) > 0 and length(trim(model_name)) > 0
    and length(trim(model_version)) > 0 and length(trim(prompt_profile_version)) > 0
  ),
  constraint ck_difficulty_run_evidence check (
    length(trim(evidence_package_key)) > 0 and length(trim(evidence_package_version)) > 0
  ),
  constraint ck_difficulty_run_parameters check (jsonb_typeof(parameters_json) = 'object'),
  constraint ck_difficulty_run_hashes check (
    evidence_package_hash ~ '^[0-9a-f]{64}$'
    and parameters_hash ~ '^[0-9a-f]{64}$'
    and run_hash ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_difficulty_run_status check (status in ('completed', 'failed')),
  constraint ck_difficulty_run_time check (completed_at >= started_at)
);

create table teachbase_app.question_difficulty_snapshot (
  snapshot_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  rubric_key varchar(120) not null,
  rubric_version_id uuid not null,
  context_key varchar(160) not null,
  context_json jsonb not null,
  context_hash char(64) not null,
  snapshot_kind varchar(32) not null,
  difficulty_value smallint,
  confidence numeric(8,7),
  assessment_run_id uuid,
  model_output_context_json jsonb not null default '{}'::jsonb,
  snapshot_hash char(64) not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_question_difficulty_snapshot_hash unique (
    workspace_id, question_revision_id, rubric_version_id, context_key, snapshot_kind, snapshot_hash
  ),
  constraint uq_question_difficulty_snapshot_scope unique (
    snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_snapshot_revision foreign key (
    question_revision_id, question_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_difficulty_snapshot_rubric foreign key (
    rubric_version_id, workspace_id, rubric_key
  ) references teachbase_app.difficulty_rubric_version(rubric_version_id, workspace_id, rubric_key),
  constraint fk_question_difficulty_snapshot_run foreign key (
    assessment_run_id, workspace_id, rubric_version_id, rubric_key
  ) references teachbase_app.difficulty_assessment_run(
    assessment_run_id, workspace_id, rubric_version_id, rubric_key
  ),
  constraint fk_question_difficulty_snapshot_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_difficulty_snapshot_context check (
    length(trim(context_key)) > 0 and jsonb_typeof(context_json) = 'object'
    and jsonb_typeof(model_output_context_json) = 'object'
  ),
  constraint ck_question_difficulty_snapshot_hashes check (
    context_hash ~ '^[0-9a-f]{64}$' and snapshot_hash ~ '^[0-9a-f]{64}$'
  ),
  constraint ck_question_difficulty_snapshot_kind check (
    snapshot_kind in ('SYSTEM_SUGGESTION', 'HUMAN_FINAL')
  ),
  constraint ck_question_difficulty_snapshot_value check (
    difficulty_value is null or difficulty_value between 1 and 5
  ),
  constraint ck_question_difficulty_snapshot_confidence check (
    confidence is null or confidence between 0 and 1
  ),
  constraint ck_question_difficulty_snapshot_run_kind check (
    (snapshot_kind = 'SYSTEM_SUGGESTION' and assessment_run_id is not null
      and difficulty_value is not null and confidence is not null)
    or (snapshot_kind = 'HUMAN_FINAL' and assessment_run_id is null and confidence is null)
  )
);

create index idx_question_difficulty_snapshot_history
  on teachbase_app.question_difficulty_snapshot(
    workspace_id, question_revision_id, rubric_key, context_key, created_at, snapshot_id
  );

create table teachbase_app.question_difficulty_feedback (
  feedback_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  rubric_key varchar(120) not null,
  rubric_version_id uuid not null,
  context_key varchar(160) not null,
  before_snapshot_id uuid not null,
  after_snapshot_id uuid not null,
  outcome varchar(32) not null,
  reason_codes_json jsonb not null default '[]'::jsonb,
  note text not null default '',
  reviewer_id uuid not null,
  submitted_at timestamptz not null default now(),
  client_mutation_id varchar(160) not null,
  request_hash char(64) not null,
  expected_state_version bigint not null,
  derived_operations_json jsonb not null,
  constraint uq_question_difficulty_feedback_mutation unique (workspace_id, client_mutation_id),
  constraint uq_question_difficulty_feedback_scope unique (
    feedback_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_feedback_revision foreign key (
    question_revision_id, question_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_difficulty_feedback_rubric foreign key (
    rubric_version_id, workspace_id, rubric_key
  ) references teachbase_app.difficulty_rubric_version(rubric_version_id, workspace_id, rubric_key),
  constraint fk_question_difficulty_feedback_before foreign key (
    before_snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_snapshot(
    snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_feedback_after foreign key (
    after_snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_snapshot(
    snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_feedback_actor foreign key (workspace_id, reviewer_id)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_difficulty_feedback_outcome check (
    outcome in ('corrected', 'confirmed', 'rubric_gap')
  ),
  constraint ck_question_difficulty_feedback_json check (
    jsonb_typeof(reason_codes_json) = 'array' and jsonb_typeof(derived_operations_json) = 'array'
  ),
  constraint ck_question_difficulty_feedback_note check (length(note) <= 10000),
  constraint ck_question_difficulty_feedback_mutation check (length(trim(client_mutation_id)) > 0),
  constraint ck_question_difficulty_feedback_hash check (request_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_question_difficulty_feedback_version check (expected_state_version >= 0)
);

create index idx_question_difficulty_feedback_history
  on teachbase_app.question_difficulty_feedback(
    workspace_id, question_revision_id, rubric_key, context_key, submitted_at, feedback_id
  );

create table teachbase_app.question_difficulty_state (
  state_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  rubric_key varchar(120) not null,
  rubric_version_id uuid not null,
  context_key varchar(160) not null,
  current_snapshot_id uuid not null,
  current_feedback_id uuid,
  state_version bigint not null default 0,
  status varchar(32) not null default 'pending',
  updated_by uuid not null,
  updated_at timestamptz not null default now(),
  constraint uq_question_difficulty_state_key unique (
    workspace_id, question_revision_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_state_revision foreign key (
    question_revision_id, question_id, workspace_id
  ) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_difficulty_state_rubric foreign key (
    rubric_version_id, workspace_id, rubric_key
  ) references teachbase_app.difficulty_rubric_version(rubric_version_id, workspace_id, rubric_key),
  constraint fk_question_difficulty_state_snapshot foreign key (
    current_snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_snapshot(
    snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_state_feedback foreign key (
    current_feedback_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_feedback(
    feedback_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_question_difficulty_state_actor foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_difficulty_state_version check (state_version >= 0),
  constraint ck_question_difficulty_state_status check (
    status in ('pending', 'reviewed', 'rubric_gap', 'needs_reconciliation')
  ),
  constraint ck_question_difficulty_state_feedback check (
    (status = 'pending' and current_feedback_id is null)
    or (status <> 'pending' and current_feedback_id is not null)
  )
);

create index idx_question_difficulty_state_queue
  on teachbase_app.question_difficulty_state(workspace_id, status, updated_at, state_id);

create table teachbase_app.difficulty_rubric_gap_case (
  gap_case_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  feedback_id uuid not null,
  rubric_key varchar(120) not null,
  reported_rubric_version_id uuid not null,
  context_key varchar(160) not null,
  before_snapshot_id uuid not null,
  expected_difficulty_text varchar(1000) not null,
  teacher_explanation text not null,
  status varchar(24) not null default 'open',
  created_by uuid not null,
  created_at timestamptz not null default now(),
  constraint uq_difficulty_rubric_gap_feedback unique (feedback_id),
  constraint fk_difficulty_rubric_gap_feedback foreign key (
    feedback_id, question_revision_id, workspace_id, reported_rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_feedback(
    feedback_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_difficulty_rubric_gap_before foreign key (
    before_snapshot_id, question_revision_id, workspace_id, reported_rubric_version_id, rubric_key, context_key
  ) references teachbase_app.question_difficulty_snapshot(
    snapshot_id, question_revision_id, workspace_id, rubric_version_id, rubric_key, context_key
  ),
  constraint fk_difficulty_rubric_gap_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_difficulty_rubric_gap_text check (
    length(trim(expected_difficulty_text)) > 0
    and length(trim(teacher_explanation)) > 0 and length(teacher_explanation) <= 10000
  ),
  constraint ck_difficulty_rubric_gap_status check (
    status in ('open', 'triaged', 'resolved', 'rejected')
  )
);

create index idx_difficulty_rubric_gap_queue
  on teachbase_app.difficulty_rubric_gap_case(workspace_id, status, created_at, gap_case_id);

-- [jooq ignore start]
create or replace function teachbase_app.reject_difficulty_feedback_fact_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'difficulty_feedback_fact_immutable';
end;
$$;

create trigger trg_difficulty_rubric_version_immutable
before update or delete on teachbase_app.difficulty_rubric_version
for each row execute function teachbase_app.reject_difficulty_feedback_fact_mutation();

create trigger trg_difficulty_assessment_run_immutable
before update or delete on teachbase_app.difficulty_assessment_run
for each row execute function teachbase_app.reject_difficulty_feedback_fact_mutation();

create trigger trg_question_difficulty_snapshot_immutable
before update or delete on teachbase_app.question_difficulty_snapshot
for each row execute function teachbase_app.reject_difficulty_feedback_fact_mutation();

create trigger trg_question_difficulty_feedback_immutable
before update or delete on teachbase_app.question_difficulty_feedback
for each row execute function teachbase_app.reject_difficulty_feedback_fact_mutation();
-- [jooq ignore stop]
