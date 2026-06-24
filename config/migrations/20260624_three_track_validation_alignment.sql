-- 用途：
-- - 对齐三轨验证基线所需的 track/difficulty/默认考点继承结构。
-- - 这是 validation baseline 迁移，不代表已经完成生产唯一事实源改造。

alter table if exists lesson
  add column if not exists track_code text;

alter table if exists task_projection
  add column if not exists stage text;

alter table if exists task_projection
  add column if not exists track_code text;

alter table if exists question_bank_item
  add column if not exists stage text;

alter table if exists question_bank_item
  add column if not exists track_code text;

alter table if exists question_bank_item_revision
  add column if not exists subject text;

alter table if exists question_bank_item_revision
  add column if not exists stage text;

alter table if exists question_bank_item_revision
  add column if not exists track_code text;

alter table if exists material_build
  add column if not exists subject text;

alter table if exists material_build
  add column if not exists stage text;

alter table if exists material_build
  add column if not exists track_code text;

alter table if exists task_subject_ext
  add column if not exists stage text;

alter table if exists task_subject_ext
  add column if not exists track_code text;

update lesson
set
  stage = case
    when stage = '初中' then 'junior'
    when stage = '高中' then 'senior'
    else stage
  end,
  track_code = case
    when track_code is not null and track_code <> '' then track_code
    when subject = '数学' and stage in ('junior', '初中') then 'math_junior'
    when subject = '数学' and stage in ('senior', '高中') then 'math_senior'
    when subject = '英语' and stage in ('senior', '高中') then 'english_senior'
    else track_code
  end;

update task_projection projection
set
  subject = coalesce(projection.subject, lesson.subject),
  stage = coalesce(projection.stage, lesson.stage),
  track_code = coalesce(projection.track_code, lesson.track_code)
from lesson
where lesson.lesson_id = projection.lesson_id;

update question_bank_item item
set
  subject = coalesce(item.subject, lesson.subject),
  stage = coalesce(item.stage, lesson.stage),
  track_code = coalesce(item.track_code, lesson.track_code),
  grade = coalesce(item.grade, lesson.grade)
from (
  select distinct on (link.question_bank_item_revision_id)
    link.question_bank_item_revision_id,
    owner.question_bank_item_id,
    lesson.lesson_id,
    lesson.subject,
    lesson.stage,
    lesson.track_code,
    lesson.grade
  from question_bank_source_link link
  join question_bank_item_revision revision
    on revision.question_bank_item_revision_id = link.question_bank_item_revision_id
  join question_bank_item owner
    on owner.question_bank_item_id = revision.question_bank_item_id
  join lesson
    on lesson.lesson_id = link.lesson_id
  order by link.question_bank_item_revision_id, link.created_at desc nulls last
) lesson
where lesson.question_bank_item_id = item.question_bank_item_id;

update question_bank_item_revision revision
set
  subject = coalesce(revision.subject, owner.subject),
  stage = coalesce(revision.stage, owner.stage),
  track_code = coalesce(revision.track_code, owner.track_code)
from question_bank_item owner
where owner.question_bank_item_id = revision.question_bank_item_id;

update material_build build
set
  subject = coalesce(build.subject, lesson.subject),
  stage = coalesce(build.stage, lesson.stage),
  track_code = coalesce(build.track_code, lesson.track_code)
from lesson
where lesson.lesson_id = build.lesson_id;

update task_subject_ext ext
set
  subject = coalesce(ext.subject, lesson.subject),
  stage = coalesce(ext.stage, lesson.stage),
  track_code = coalesce(ext.track_code, lesson.track_code)
from task_revision task_revision
join lesson_revision lesson_revision
  on lesson_revision.lesson_revision_id = task_revision.lesson_revision_id
join lesson
  on lesson.lesson_id = lesson_revision.lesson_id
where task_revision.task_revision_id = ext.task_revision_id;

alter table if exists task_projection
  alter column difficulty_level type smallint
  using case
    when difficulty_level::text ~ '^[1-5]$' then difficulty_level::smallint
    when difficulty_level::text in ('低风险', 'easy') then 2
    when difficulty_level::text in ('中风险', 'medium') then 3
    when difficulty_level::text in ('高风险', 'hard') then 4
    else 3
  end;

alter table if exists question_bank_item_revision
  alter column difficulty_level type smallint
  using case
    when difficulty_level::text ~ '^[1-5]$' then difficulty_level::smallint
    when difficulty_level::text in ('低风险', 'easy') then 2
    when difficulty_level::text in ('中风险', 'medium') then 3
    when difficulty_level::text in ('高风险', 'hard') then 4
    else 3
  end;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'ck_lesson_track_code_validation'
  ) then
    alter table lesson
      add constraint ck_lesson_track_code_validation
      check (track_code is null or track_code in ('math_junior', 'math_senior', 'english_senior'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_task_projection_track_code_validation'
  ) then
    alter table task_projection
      add constraint ck_task_projection_track_code_validation
      check (track_code is null or track_code in ('math_junior', 'math_senior', 'english_senior'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_question_bank_item_track_code_validation'
  ) then
    alter table question_bank_item
      add constraint ck_question_bank_item_track_code_validation
      check (track_code is null or track_code in ('math_junior', 'math_senior', 'english_senior'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_question_bank_item_revision_track_code_validation'
  ) then
    alter table question_bank_item_revision
      add constraint ck_question_bank_item_revision_track_code_validation
      check (track_code is null or track_code in ('math_junior', 'math_senior', 'english_senior'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_material_build_track_code_validation'
  ) then
    alter table material_build
      add constraint ck_material_build_track_code_validation
      check (track_code is null or track_code in ('math_junior', 'math_senior', 'english_senior'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_task_subject_ext_track_code_validation'
  ) then
    alter table task_subject_ext
      add constraint ck_task_subject_ext_track_code_validation
      check (track_code is null or track_code in ('math_junior', 'math_senior', 'english_senior'));
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_task_projection_difficulty_level_validation'
  ) then
    alter table task_projection
      add constraint ck_task_projection_difficulty_level_validation
      check (difficulty_level between 1 and 5);
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'ck_question_bank_item_revision_difficulty_level_validation'
  ) then
    alter table question_bank_item_revision
      add constraint ck_question_bank_item_revision_difficulty_level_validation
      check (difficulty_level between 1 and 5);
  end if;
end $$;

create index if not exists idx_lesson_track_code on lesson (track_code);
create index if not exists idx_task_projection_stage on task_projection (stage);
create index if not exists idx_task_projection_track_code on task_projection (track_code);
create index if not exists idx_task_projection_subject_stage_track on task_projection (subject, stage, track_code);
create index if not exists idx_question_bank_item_track_code on question_bank_item (track_code);
create index if not exists idx_question_bank_item_revision_track_code on question_bank_item_revision (track_code);
create index if not exists idx_material_build_track_code on material_build (track_code);
