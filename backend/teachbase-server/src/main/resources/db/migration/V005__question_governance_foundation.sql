-- Governance boundary for immutable question content, human approval, and
-- versioned knowledge taxonomies. Difficulty remains an optional imported value;
-- this migration deliberately defines no difficulty rubric or inference rule.

-- Separate semantic content identity from the source packet and the operational
-- import envelope. Existing rows cannot be reconstructed, so their previous hash
-- is used as a documented migration fallback; every new import writes all three.
alter table teachbase_app.question_revision
  add column source_payload_hash char(64),
  add column import_envelope_hash char(64);

update teachbase_app.question_revision
set source_payload_hash = content_hash,
    import_envelope_hash = content_hash;

alter table teachbase_app.question_revision
  alter column source_payload_hash set not null;
alter table teachbase_app.question_revision
  alter column import_envelope_hash set not null;
alter table teachbase_app.question_revision
  add constraint ck_question_revision_source_payload_hash
    check (source_payload_hash ~ '^[0-9a-f]{64}$');
alter table teachbase_app.question_revision
  add constraint ck_question_revision_import_envelope_hash
    check (import_envelope_hash ~ '^[0-9a-f]{64}$');

-- Every received envelope is retained even when semantic idempotency reuses an
-- existing revision. This makes retries and changed upstream metadata observable.
create table teachbase_app.question_import_observation (
  question_import_observation_id uuid primary key,
  question_id uuid not null,
  question_revision_id uuid not null,
  workspace_id uuid not null,
  source_payload_hash char(64) not null,
  import_envelope_hash char(64) not null,
  provenance_json jsonb not null default '{}'::jsonb,
  observed_by uuid not null,
  observed_at timestamptz not null default now(),
  constraint uq_question_import_envelope unique (question_revision_id, import_envelope_hash),
  constraint fk_question_import_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_import_actor foreign key (workspace_id, observed_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_import_source_hash check (source_payload_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_question_import_envelope_hash check (import_envelope_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_question_import_provenance check (jsonb_typeof(provenance_json) = 'object')
);

create index idx_question_import_observation_source
  on teachbase_app.question_import_observation(workspace_id, source_payload_hash, observed_at desc);

-- A review case freezes the expected semantic hash. A later content revision must
-- open a different case and cannot accidentally inherit an earlier approval.
create table teachbase_app.review_case (
  review_case_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  expected_content_hash char(64) not null,
  status varchar(24) not null default 'open',
  assigned_to uuid,
  opened_by uuid not null,
  opened_at timestamptz not null default now(),
  decided_at timestamptz,
  constraint uq_review_case_scope unique (review_case_id, workspace_id),
  constraint fk_review_case_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_review_case_opener foreign key (workspace_id, opened_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint fk_review_case_assignee foreign key (workspace_id, assigned_to)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_review_case_hash check (expected_content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_review_case_status check (status in ('open', 'approved', 'rejected', 'cancelled')),
  constraint ck_review_case_decided_at check (
    (status = 'open' and decided_at is null)
    or (status <> 'open' and decided_at is not null)
  )
);

-- PostgreSQL's partial uniqueness expresses exactly one active case per revision.
-- [jooq ignore start]
create unique index uq_review_case_open_revision
  on teachbase_app.review_case(question_revision_id) where status = 'open';
-- [jooq ignore stop]
create index idx_review_case_queue
  on teachbase_app.review_case(workspace_id, status, opened_at, review_case_id);

-- Decisions are append-only evidence. The unique case key prevents a race from
-- recording two terminal decisions for one case.
create table teachbase_app.review_decision (
  review_decision_id uuid primary key,
  review_case_id uuid not null,
  workspace_id uuid not null,
  decision varchar(24) not null,
  note text not null default '',
  expected_content_hash char(64) not null,
  policy_version varchar(120) not null,
  decision_source varchar(40) not null,
  evidence_json jsonb not null default '{}'::jsonb,
  evidence_occurred_at timestamptz,
  decided_by uuid not null,
  decided_at timestamptz not null default now(),
  constraint uq_review_decision_case unique (review_case_id),
  constraint fk_review_decision_case foreign key (review_case_id, workspace_id)
    references teachbase_app.review_case(review_case_id, workspace_id),
  constraint fk_review_decision_actor foreign key (workspace_id, decided_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_review_decision_value check (decision in ('approved', 'rejected')),
  constraint ck_review_decision_note check (length(note) <= 10000),
  constraint ck_review_decision_hash check (expected_content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_review_decision_policy check (length(trim(policy_version)) > 0),
  constraint ck_review_decision_source check (decision_source in ('human_ui', 'release_seed', 'api')),
  constraint ck_review_decision_evidence check (jsonb_typeof(evidence_json) = 'object')
);

-- A taxonomy key is stable while versions are immutable snapshots of its nodes.
create table teachbase_app.taxonomy_version (
  taxonomy_version_id uuid primary key,
  workspace_id uuid not null,
  taxonomy_key varchar(120) not null,
  version_key varchar(120) not null,
  subject varchar(80) not null,
  stage varchar(80) not null default '',
  status varchar(24) not null default 'draft',
  schema_version integer not null default 1,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  constraint uq_taxonomy_version_scope unique (taxonomy_version_id, workspace_id),
  constraint uq_taxonomy_version_key unique (workspace_id, taxonomy_key, version_key),
  constraint fk_taxonomy_version_actor foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_taxonomy_key check (length(trim(taxonomy_key)) > 0),
  constraint ck_taxonomy_version_key check (length(trim(version_key)) > 0),
  constraint ck_taxonomy_subject check (length(trim(subject)) > 0),
  constraint ck_taxonomy_status check (status in ('draft', 'active', 'retired')),
  constraint ck_taxonomy_schema_version check (schema_version > 0),
  constraint ck_taxonomy_activation check (
    (status = 'draft' and activated_at is null)
    or (status in ('active', 'retired') and activated_at is not null)
  )
);

-- One active version per workspace/taxonomy keeps writes deterministic while old
-- question links continue to point at retired immutable versions.
-- [jooq ignore start]
create unique index uq_taxonomy_active
  on teachbase_app.taxonomy_version(workspace_id, taxonomy_key) where status = 'active';
-- [jooq ignore stop]

create table teachbase_app.taxonomy_node (
  taxonomy_node_id uuid primary key,
  taxonomy_version_id uuid not null,
  workspace_id uuid not null,
  knowledge_code varchar(240) not null,
  display_name varchar(512) not null,
  parent_node_id uuid,
  sort_order integer not null default 0,
  metadata_json jsonb not null default '{}'::jsonb,
  constraint uq_taxonomy_node_scope unique (taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint uq_taxonomy_node_code unique (taxonomy_version_id, knowledge_code),
  constraint fk_taxonomy_node_version foreign key (taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_version(taxonomy_version_id, workspace_id),
  constraint fk_taxonomy_node_parent foreign key (parent_node_id, taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint ck_taxonomy_node_code check (length(trim(knowledge_code)) > 0),
  constraint ck_taxonomy_node_name check (length(trim(display_name)) > 0),
  constraint ck_taxonomy_node_order check (sort_order >= 0),
  constraint ck_taxonomy_node_metadata check (jsonb_typeof(metadata_json) = 'object'),
  constraint ck_taxonomy_node_not_parent check (parent_node_id is null or parent_node_id <> taxonomy_node_id)
);

create index idx_taxonomy_node_tree
  on teachbase_app.taxonomy_node(taxonomy_version_id, parent_node_id, sort_order, taxonomy_node_id);

create table teachbase_app.taxonomy_alias (
  taxonomy_alias_id uuid primary key,
  taxonomy_node_id uuid not null,
  taxonomy_version_id uuid not null,
  workspace_id uuid not null,
  display_alias varchar(512) not null,
  normalized_alias varchar(512) not null,
  constraint uq_taxonomy_alias unique (taxonomy_version_id, normalized_alias),
  constraint fk_taxonomy_alias_node foreign key (taxonomy_node_id, taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint ck_taxonomy_alias_display check (length(trim(display_alias)) > 0),
  constraint ck_taxonomy_alias_normalized check (length(trim(normalized_alias)) > 0)
);

-- Links target immutable question revisions and immutable taxonomy versions. A
-- confidence is optional because manually curated seed data may not have one.
create table teachbase_app.question_taxonomy_link (
  question_taxonomy_link_id uuid primary key,
  workspace_id uuid not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  taxonomy_node_id uuid not null,
  taxonomy_version_id uuid not null,
  relation_type varchar(24) not null,
  assignment_source varchar(24) not null,
  confidence numeric(5,4),
  assigned_by uuid not null,
  assigned_at timestamptz not null default now(),
  constraint uq_question_taxonomy_link unique (question_revision_id, taxonomy_node_id, relation_type),
  constraint fk_question_taxonomy_revision foreign key (question_revision_id, question_id, workspace_id)
    references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  constraint fk_question_taxonomy_node foreign key (taxonomy_node_id, taxonomy_version_id, workspace_id)
    references teachbase_app.taxonomy_node(taxonomy_node_id, taxonomy_version_id, workspace_id),
  constraint fk_question_taxonomy_actor foreign key (workspace_id, assigned_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_question_taxonomy_relation check (relation_type in ('primary', 'secondary')),
  constraint ck_question_taxonomy_source check (assignment_source in ('human', 'model', 'import')),
  constraint ck_question_taxonomy_confidence check (confidence is null or confidence between 0 and 1)
);

create index idx_question_taxonomy_lookup
  on teachbase_app.question_taxonomy_link(workspace_id, taxonomy_node_id, question_revision_id);
