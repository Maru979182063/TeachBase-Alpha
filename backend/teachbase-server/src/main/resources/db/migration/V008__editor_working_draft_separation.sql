-- WP-01 扩展迁移：immutable revision 继续作为发布边界；浏览器自动保存只更新每文档唯一的可变草稿。
alter table teachbase_app.editor_document
  add column writer_mode varchar(24) not null default 'legacy';

alter table teachbase_app.editor_document
  add constraint ck_editor_document_writer_mode
    check (writer_mode in ('legacy', 'working_draft'));

create table teachbase_app.editor_working_draft (
  editor_document_id uuid primary key,
  workspace_id uuid not null,
  base_revision_id uuid,
  draft_version bigint not null,
  content_json jsonb not null,
  content_hash char(64) not null,
  content_bytes integer not null,
  updated_by uuid not null,
  updated_at timestamptz not null default now(),
  constraint uq_editor_working_draft_scope unique (editor_document_id, workspace_id),
  constraint fk_editor_working_draft_document foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_document(editor_document_id, workspace_id),
  constraint fk_editor_working_draft_base_revision foreign key (
    base_revision_id, editor_document_id, workspace_id
  ) references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_editor_working_draft_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_working_draft_version check (draft_version > 0),
  constraint ck_editor_working_draft_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_editor_working_draft_hash check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_editor_working_draft_bytes check (content_bytes > 0)
);

create table teachbase_app.editor_autosave_mutation (
  editor_autosave_mutation_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  client_mutation_id varchar(128) not null,
  expected_draft_version bigint not null,
  resulting_draft_version bigint not null,
  base_revision_id uuid,
  content_json jsonb not null,
  content_hash char(64) not null,
  content_bytes integer not null,
  updated_by uuid not null,
  updated_at timestamptz not null,
  expires_at timestamptz not null,
  constraint uq_editor_autosave_mutation unique (
    workspace_id, editor_document_id, client_mutation_id
  ),
  constraint fk_editor_autosave_mutation_draft foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_working_draft(editor_document_id, workspace_id) on delete cascade,
  constraint fk_editor_autosave_mutation_base_revision foreign key (
    base_revision_id, editor_document_id, workspace_id
  ) references teachbase_app.editor_revision(editor_revision_id, editor_document_id, workspace_id),
  constraint fk_editor_autosave_mutation_updater foreign key (workspace_id, updated_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_autosave_mutation_id check (length(trim(client_mutation_id)) > 0),
  constraint ck_editor_autosave_mutation_versions check (
    expected_draft_version > 0 and resulting_draft_version = expected_draft_version + 1
  ),
  constraint ck_editor_autosave_mutation_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_editor_autosave_mutation_hash check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_editor_autosave_mutation_bytes check (content_bytes > 0)
);

-- PostgreSQL 存储参数不参与 jOOQ 类型生成；这里只调整大 JSON 热更新表的 vacuum 触发阈值。
-- [jooq ignore start]
alter table teachbase_app.editor_working_draft set (
  fillfactor = 80,
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.05
);
alter table teachbase_app.editor_autosave_mutation set (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.05
);
-- [jooq ignore stop]

create index idx_editor_autosave_mutation_expiry
  on teachbase_app.editor_autosave_mutation(expires_at, editor_autosave_mutation_id);

create table teachbase_app.editor_draft_checkpoint (
  editor_draft_checkpoint_id uuid primary key,
  editor_document_id uuid not null,
  workspace_id uuid not null,
  draft_version bigint not null,
  checkpoint_kind varchar(32) not null,
  content_json jsonb not null,
  content_hash char(64) not null,
  content_bytes integer not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  constraint fk_editor_draft_checkpoint_draft foreign key (editor_document_id, workspace_id)
    references teachbase_app.editor_working_draft(editor_document_id, workspace_id) on delete cascade,
  constraint fk_editor_draft_checkpoint_creator foreign key (workspace_id, created_by)
    references teachbase_app.workspace_member(workspace_id, user_id),
  constraint ck_editor_draft_checkpoint_version check (draft_version > 0),
  constraint ck_editor_draft_checkpoint_kind check (
    checkpoint_kind in ('autosave', 'conflict_recovery', 'pre_transition')
  ),
  constraint ck_editor_draft_checkpoint_content check (jsonb_typeof(content_json) = 'object'),
  constraint ck_editor_draft_checkpoint_hash check (content_hash ~ '^[0-9a-f]{64}$'),
  constraint ck_editor_draft_checkpoint_bytes check (content_bytes > 0)
);

create index idx_editor_draft_checkpoint_retention
  on teachbase_app.editor_draft_checkpoint(editor_document_id, created_at desc);
create index idx_editor_draft_checkpoint_expiry
  on teachbase_app.editor_draft_checkpoint(expires_at);

-- 触发器隔离仍会移动 editor_draft 的旧版本进程；文档切换后，旧写事务整体失败，不能形成第二真相源。
-- [jooq ignore start]
create or replace function teachbase_app.fence_legacy_editor_draft_writer()
returns trigger
language plpgsql
as $$
declare
  target_document_id uuid;
  target_workspace_id uuid;
begin
  if tg_op = 'DELETE' then
    target_document_id := old.editor_document_id;
    target_workspace_id := old.workspace_id;
  else
    target_document_id := new.editor_document_id;
    target_workspace_id := new.workspace_id;
  end if;
  if exists (
    select 1
      from teachbase_app.editor_document
     where editor_document_id = target_document_id
       and workspace_id = target_workspace_id
       and writer_mode <> 'legacy'
  ) then
    raise exception 'legacy_editor_writer_fenced'
      using errcode = 'TB001',
            detail = 'editor_draft is read-only after writer_mode switches to working_draft',
            hint = 'materialize rollback and switch writer_mode to legacy before using the legacy writer';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create trigger trg_fence_legacy_editor_draft_writer
before insert or update or delete on teachbase_app.editor_draft
for each row execute function teachbase_app.fence_legacy_editor_draft_writer();
-- [jooq ignore stop]
