-- 只读全量扫描；不把跨版本历史视为冲突，不选择主标签胜者。
select workspace_id, question_revision_id, taxonomy_version_id,
       count(*)::integer as primary_count,
       array_agg(question_taxonomy_link_id order by question_taxonomy_link_id) as link_ids,
       array_agg(taxonomy_node_id order by taxonomy_node_id) as node_ids
from teachbase_app.question_taxonomy_link
where relation_type = 'primary'
group by workspace_id, question_revision_id, taxonomy_version_id
having count(*) > 1
order by workspace_id, question_revision_id, taxonomy_version_id;
