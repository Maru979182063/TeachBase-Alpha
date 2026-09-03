-- 教师的教学范围属于工作空间成员关系，而不是全局用户资料。
-- 一行表示一个精确的“学科 + 学段”组合，避免两个独立多选字段产生错误的笛卡尔积。
create table teachbase_app.workspace_member_teaching_scope (
  workspace_id uuid not null,
  user_id uuid not null,
  subject varchar(80) not null,
  stage varchar(80) not null,
  is_primary boolean not null default false,
  assigned_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id, subject, stage),
  constraint fk_member_teaching_scope_member foreign key (workspace_id, user_id)
    references teachbase_app.workspace_member(workspace_id, user_id) on delete cascade,
  constraint fk_member_teaching_scope_actor foreign key (workspace_id, assigned_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_member_teaching_scope_subject check (length(trim(subject)) > 0),
  constraint ck_member_teaching_scope_stage check (length(trim(stage)) > 0)
);

-- 每位成员最多只能有一个主教学范围；没有主范围是允许的。
-- [jooq ignore start]
create unique index uq_member_primary_teaching_scope
  on teachbase_app.workspace_member_teaching_scope(workspace_id, user_id)
  where is_primary;
-- [jooq ignore stop]

create index idx_member_teaching_scope_lookup
  on teachbase_app.workspace_member_teaching_scope(workspace_id, subject, stage, user_id);
