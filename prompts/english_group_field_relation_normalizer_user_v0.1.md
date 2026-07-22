Normalize group fields and group relations for this document.

Part A: normalized_records
- For every input group, output one normalized_group_record_v0.1.
- Use only block refs that are already inside that group.
- field_refs meanings:
  - stem_refs: main task/question/prompt refs.
  - option_refs: multiple-choice/selectable option refs.
  - passage_refs: reading passage or shared article refs.
  - answer_refs: answer key/model answer refs.
  - analysis_refs: explanation/solution reasoning refs.
  - translation_refs: translation refs.
  - context_refs: knowledge, parent context, lead-in, or shared context refs needed to understand the activity.
  - instruction_refs: activity directions.
  - example_refs: worked examples or example sentences.
  - visual_refs: tables, diagrams, forms, images, visual structures.
  - writing_surface_refs: response area, blank writing lines, answer sheet, writing-specific review surface.
  - rubric_refs: scoring criteria or teacher rubric refs.
  - other_evidence_refs: refs that belong to the group but do not fit above.
- Missing fields are allowed. Mark them missing, not_applicable, uncertain, or partial. Do not block the record.
- Every `*_refs` field must be an array. If absent, use [].
- Do not use strings such as "not_applicable" inside field_refs. Only field_status may use not_applicable.

Part B: projection_graph
- For every group, output one graph node.
- project_directly_to_question means only that the group itself can be a direct draft item. It does not require answer_refs.
- If a group is a shared context, knowledge table, passage, diagram, or parent material, set a non-question projection hint unless it has its own answerable task.
- For relationships, use contains, uses_context, is_child_of, shares_stimulus, continues_on, or other.
- For every overlapping block_ref, choose a primary projection owner.
- If an overlapping block is essential to a child item as stem, task instruction, example material, answer, analysis, translation, or response surface, the child item should usually be the primary owner.
- If the same block is a true shared stimulus passage/table used by multiple child items, the stimulus parent may be primary owner and children may reference it.
- Do not delete evidence; overlap ownership only controls projection duplication.

Input:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "group_field_relation_bundle_v0.1",
  "doc_id": "{{doc_id}}",
  "prompt_version": "{{prompt_version}}",
  "normalized_records": [],
  "projection_graph": {
    "schema": "group_projection_graph_v0.1",
    "doc_id": "{{doc_id}}",
    "prompt_version": "{{prompt_version}}",
    "nodes": [],
    "relations": [],
    "overlap_resolutions": [],
    "open_issues": []
  }
}
```

Return only the JSON object. No Markdown.
