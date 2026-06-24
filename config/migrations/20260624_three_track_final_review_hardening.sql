-- Purpose:
-- - harden the three-track validation baseline with database-backed track constraints
-- - classify unresolved legacy rows as migration warnings instead of silently defaulting to math_junior

create table if not exists subject_track (
  track_code text primary key,
  subject text not null,
  stage text not null,
  plugin_id text not null,
  difficulty_scheme text not null,
  active boolean not null default true
);

create unique index if not exists idx_subject_track_subject_stage_track
  on subject_track (subject, stage, track_code);

create unique index if not exists idx_subject_track_track_plugin
  on subject_track (track_code, plugin_id);

create unique index if not exists idx_subject_track_track_difficulty
  on subject_track (track_code, difficulty_scheme);

insert into subject_track (track_code, subject, stage, plugin_id, difficulty_scheme, active)
values
  ('math_junior', '数学', 'junior', 'subject.math.junior.v1', 'difficulty.math.junior.v1', true),
  ('math_senior', '数学', 'senior', 'subject.math.senior.v1', 'difficulty.math.senior.v1', true),
  ('english_senior', '英语', 'senior', 'subject.english.senior.v1', 'difficulty.english.senior.v1', true)
on conflict (track_code) do update
set
  subject = excluded.subject,
  stage = excluded.stage,
  plugin_id = excluded.plugin_id,
  difficulty_scheme = excluded.difficulty_scheme,
  active = excluded.active;

create table if not exists runtime_migration_warning (
  warning_id bigserial primary key,
  migration_name text not null,
  entity_table text not null,
  entity_id text not null,
  warning_code text not null,
  detail_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists idx_runtime_migration_warning_entity_code
  on runtime_migration_warning (migration_name, entity_table, entity_id, warning_code);

update lesson
set
  stage = case
    when stage = '初中' then 'junior'
    when stage = '高中' then 'senior'
    else stage
  end,
  track_code = case
    when subject = '数学' and stage = 'junior' then 'math_junior'
    when subject = '数学' and stage = 'senior' then 'math_senior'
    when subject = '英语' and stage = 'senior' then 'english_senior'
    else track_code
  end
where
  stage in ('初中', '高中')
  or (
    subject in ('数学', '英语')
    and stage in ('junior', 'senior')
    and (
      track_code is null
      or track_code = ''
      or (subject = '数学' and stage = 'junior' and track_code <> 'math_junior')
      or (subject = '数学' and stage = 'senior' and track_code <> 'math_senior')
      or (subject = '英语' and stage = 'senior' and track_code <> 'english_senior')
    )
  );

update task_projection projection
set
  subject = coalesce(projection.subject, lesson.subject),
  stage = coalesce(projection.stage, lesson.stage),
  track_code = case
    when coalesce(projection.subject, lesson.subject) = '数学' and coalesce(projection.stage, lesson.stage) = 'junior' then 'math_junior'
    when coalesce(projection.subject, lesson.subject) = '数学' and coalesce(projection.stage, lesson.stage) = 'senior' then 'math_senior'
    when coalesce(projection.subject, lesson.subject) = '英语' and coalesce(projection.stage, lesson.stage) = 'senior' then 'english_senior'
    else coalesce(projection.track_code, lesson.track_code)
  end
from lesson
where lesson.lesson_id = projection.lesson_id;

update question_bank_item item
set
  subject = coalesce(item.subject, lesson.subject),
  stage = coalesce(item.stage, lesson.stage),
  track_code = case
    when coalesce(item.subject, lesson.subject) = '数学' and coalesce(item.stage, lesson.stage) = 'junior' then 'math_junior'
    when coalesce(item.subject, lesson.subject) = '数学' and coalesce(item.stage, lesson.stage) = 'senior' then 'math_senior'
    when coalesce(item.subject, lesson.subject) = '英语' and coalesce(item.stage, lesson.stage) = 'senior' then 'english_senior'
    else coalesce(item.track_code, lesson.track_code)
  end,
  grade = coalesce(item.grade, lesson.grade)
from lesson
where lesson.lesson_id in (
  select link.lesson_id
  from question_bank_source_link link
  join question_bank_item_revision revision
    on revision.question_bank_item_revision_id = link.question_bank_item_revision_id
  where revision.question_bank_item_id = item.question_bank_item_id
)
and lesson.lesson_id = (
  select link.lesson_id
  from question_bank_source_link link
  join question_bank_item_revision revision
    on revision.question_bank_item_revision_id = link.question_bank_item_revision_id
  where revision.question_bank_item_id = item.question_bank_item_id
  order by link.created_at desc nulls last
  limit 1
);

update question_bank_item_revision revision
set
  subject = coalesce(revision.subject, owner.subject),
  stage = coalesce(revision.stage, owner.stage),
  track_code = case
    when coalesce(revision.subject, owner.subject) = '数学' and coalesce(revision.stage, owner.stage) = 'junior' then 'math_junior'
    when coalesce(revision.subject, owner.subject) = '数学' and coalesce(revision.stage, owner.stage) = 'senior' then 'math_senior'
    when coalesce(revision.subject, owner.subject) = '英语' and coalesce(revision.stage, owner.stage) = 'senior' then 'english_senior'
    else coalesce(revision.track_code, owner.track_code)
  end
from question_bank_item owner
where owner.question_bank_item_id = revision.question_bank_item_id;

update material_build build
set
  subject = coalesce(build.subject, lesson.subject),
  stage = coalesce(build.stage, lesson.stage),
  track_code = case
    when coalesce(build.subject, lesson.subject) = '数学' and coalesce(build.stage, lesson.stage) = 'junior' then 'math_junior'
    when coalesce(build.subject, lesson.subject) = '数学' and coalesce(build.stage, lesson.stage) = 'senior' then 'math_senior'
    when coalesce(build.subject, lesson.subject) = '英语' and coalesce(build.stage, lesson.stage) = 'senior' then 'english_senior'
    else coalesce(build.track_code, lesson.track_code)
  end
from lesson
where lesson.lesson_id = build.lesson_id;

update task_subject_ext ext
set
  subject = coalesce(ext.subject, lesson.subject),
  stage = coalesce(ext.stage, lesson.stage),
  track_code = case
    when coalesce(ext.subject, lesson.subject) = '数学' and coalesce(ext.stage, lesson.stage) = 'junior' then 'math_junior'
    when coalesce(ext.subject, lesson.subject) = '数学' and coalesce(ext.stage, lesson.stage) = 'senior' then 'math_senior'
    when coalesce(ext.subject, lesson.subject) = '英语' and coalesce(ext.stage, lesson.stage) = 'senior' then 'english_senior'
    else coalesce(ext.track_code, lesson.track_code)
  end
from task_revision task_revision
join lesson_revision lesson_revision
  on lesson_revision.lesson_revision_id = task_revision.lesson_revision_id
join lesson
  on lesson.lesson_id = lesson_revision.lesson_id
where task_revision.task_revision_id = ext.task_revision_id;

update task_subject_ext ext
set
  plugin_id = track.plugin_id,
  payload_json =
    coalesce(ext.payload_json, '{}'::jsonb) ||
    jsonb_build_object(
      'subject', track.subject,
      'stage', track.stage,
      'track_code', track.track_code,
      'plugin_id', track.plugin_id
    )
from subject_track track
where ext.track_code = track.track_code
  and ext.plugin_id is distinct from track.plugin_id;

update task_projection projection
set difficulty_scheme = track.difficulty_scheme
from subject_track track
where projection.track_code = track.track_code
  and projection.difficulty_scheme is distinct from track.difficulty_scheme;

update question_bank_item_revision revision
set difficulty_scheme = track.difficulty_scheme
from subject_track track
where revision.track_code = track.track_code
  and revision.difficulty_scheme is distinct from track.difficulty_scheme;

update task_projection
set difficulty_level = null
where difficulty_source in ('unknown', 'legacy_unknown', 'migration_unknown', 'unmapped');

update question_bank_item_revision
set difficulty_level = null
where difficulty_source in ('unknown', 'legacy_unknown', 'migration_unknown', 'unmapped');

insert into runtime_migration_warning (migration_name, entity_table, entity_id, warning_code, detail_json)
select
  '20260624_three_track_final_review_hardening.sql',
  'lesson',
  lesson_id,
  'unresolved_track_scope',
  jsonb_build_object('subject', subject, 'stage', stage, 'track_code', track_code)
from lesson
where (subject is not null or stage is not null or track_code is not null)
  and not exists (
    select 1
    from subject_track track
    where track.subject = lesson.subject
      and track.stage = lesson.stage
      and track.track_code = lesson.track_code
  )
on conflict do nothing;

insert into runtime_migration_warning (migration_name, entity_table, entity_id, warning_code, detail_json)
select
  '20260624_three_track_final_review_hardening.sql',
  'task_subject_ext',
  task_revision_id,
  'unresolved_track_scope',
  jsonb_build_object('subject', subject, 'stage', stage, 'track_code', track_code, 'plugin_id', plugin_id)
from task_subject_ext
where (subject is not null or stage is not null or track_code is not null)
  and not exists (
    select 1
    from subject_track track
    where track.subject = task_subject_ext.subject
      and track.stage = task_subject_ext.stage
      and track.track_code = task_subject_ext.track_code
  )
on conflict do nothing;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'fk_lesson_subject_track_scope'
  ) then
    alter table lesson
      add constraint fk_lesson_subject_track_scope
      foreign key (subject, stage, track_code)
      references subject_track(subject, stage, track_code);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_task_projection_subject_track_scope'
  ) then
    alter table task_projection
      add constraint fk_task_projection_subject_track_scope
      foreign key (subject, stage, track_code)
      references subject_track(subject, stage, track_code);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_task_projection_track_difficulty_scheme'
  ) then
    alter table task_projection
      add constraint fk_task_projection_track_difficulty_scheme
      foreign key (track_code, difficulty_scheme)
      references subject_track(track_code, difficulty_scheme);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_question_bank_item_subject_track_scope'
  ) then
    alter table question_bank_item
      add constraint fk_question_bank_item_subject_track_scope
      foreign key (subject, stage, track_code)
      references subject_track(subject, stage, track_code);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_question_bank_revision_subject_track_scope'
  ) then
    alter table question_bank_item_revision
      add constraint fk_question_bank_revision_subject_track_scope
      foreign key (subject, stage, track_code)
      references subject_track(subject, stage, track_code);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_question_bank_revision_track_difficulty_scheme'
  ) then
    alter table question_bank_item_revision
      add constraint fk_question_bank_revision_track_difficulty_scheme
      foreign key (track_code, difficulty_scheme)
      references subject_track(track_code, difficulty_scheme);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_material_build_subject_track_scope'
  ) then
    alter table material_build
      add constraint fk_material_build_subject_track_scope
      foreign key (subject, stage, track_code)
      references subject_track(subject, stage, track_code);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_task_subject_ext_subject_track_scope'
  ) then
    alter table task_subject_ext
      add constraint fk_task_subject_ext_subject_track_scope
      foreign key (subject, stage, track_code)
      references subject_track(subject, stage, track_code);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'fk_task_subject_ext_track_plugin'
  ) then
    alter table task_subject_ext
      add constraint fk_task_subject_ext_track_plugin
      foreign key (track_code, plugin_id)
      references subject_track(track_code, plugin_id);
  end if;
end $$;
