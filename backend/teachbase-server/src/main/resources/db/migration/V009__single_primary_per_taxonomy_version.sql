-- G1 已确认范围：同一题目修订、同一 taxonomy 版本最多一个主标签。
-- 跨版本历史保留；不推断树内分支的教学维度，也不自动删除或降级冲突数据。
-- [jooq ignore start]
lock table teachbase_app.question_taxonomy_link in share row exclusive mode;

do $$
declare
  conflicts jsonb;
begin
  select jsonb_agg(to_jsonb(g)) into conflicts from (
    select workspace_id, question_revision_id, taxonomy_version_id,
           count(*) as primary_count,
           array_agg(question_taxonomy_link_id order by question_taxonomy_link_id) as link_ids
    from teachbase_app.question_taxonomy_link
    where relation_type = 'primary'
    group by workspace_id, question_revision_id, taxonomy_version_id
    having count(*) > 1
    order by workspace_id, question_revision_id, taxonomy_version_id
    limit 50
  ) g;
  if conflicts is not null then
    raise exception using
      errcode = '23505',
      message = 'taxonomy_primary_conflicts_before_v009',
      detail = conflicts::text,
      hint = 'Run scan_taxonomy_primary_conflicts.mjs for the complete conflict list. No automatic repair.';
  end if;
end $$;

create unique index uq_question_primary_per_taxonomy_version
  on teachbase_app.question_taxonomy_link(question_revision_id, taxonomy_version_id)
  where relation_type = 'primary';
-- [jooq ignore stop]
