Resolve parent/child and projection relationships for this document.

The document may contain many groups. Keep output compact enough to finish in one response.
Use terse phrases, not explanations:
- node.reason: 3-10 words.
- relation.reason: 3-10 words.
- overlap_resolution.reason: 3-10 words.
- evidence_refs: 1-3 refs only.
- open_issues: only unresolved issues that change downstream projection.

Important distinction:
- A parent stimulus/description/context group may contain knowledge tables, diagrams, passages, method charts, or shared instructions.
- A child question/activity group is the unit that can become a directly answerable item.
- A block may be cited by both parent and child, but it must have one primary owner for projection.
- Parent groups may be saved as stimulus/description/knowledge nodes and referenced by child items.
- Child groups may project to question/activity items when fields are sufficient.

For each group:
- semantic_role: open text, e.g. "stimulus parent: relative clause table", "child activity: relative clause example analysis", "knowledge description only", "incomplete continuation".
- projection_target_hint: open text, e.g. "stimulus_description", "question_item", "knowledge_node", "do_not_project_directly", "needs_continuation".
- project_directly_to_question: true only if this group itself should become a direct question/activity item.
- If projection_target_hint is stimulus_description, knowledge_node, do_not_project_directly, or needs_continuation, project_directly_to_question must be false.
- If a parent group has its own answerable table and also has child activities, use projection_target_hint "composite_parent_item" or "stimulus_with_own_interaction"; explain the ambiguity in reason. Do not call it stimulus_description while also setting project_directly_to_question true.
- A parent context group can be preserved and referenced even when it is not directly projected as a question item.

For relationships:
- Use contains when a parent group contains a child activity.
- Use is_child_of when a child group belongs under a parent group.
- Use uses_context when a child needs a parent/context group but is not literally contained by it.
- Use shares_stimulus when several child items share a passage/table/stimulus.
- Use continues_on for cross-page continuation relationships.

For overlap_resolutions:
- For every block_ref that appears in more than one group, choose primary_owner_group_id.
- secondary_usage should explain whether the other group may keep it as context_ref, child_ref, stimulus_ref, or should drop it before question projection.
- Do not delete evidence. This only controls projection ownership.
- If an overlapping block is essential to an answerable child item as stem, task instruction, example material, answer, analysis, translation, or response surface, the child item should usually be the primary projection owner.
- A parent stimulus/context group may still reference that block as child_ref or context_ref, but should not take primary projection ownership of child task material merely because the block appears adjacent to the parent.
- If the same block is truly a shared stimulus passage/table used by multiple child items, the stimulus parent may be primary owner and children may reference it as shared_stimulus.
- If overlap is harmless duplicate context and does not affect projection ownership, omit it.

Input:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "group_projection_graph_v0.1",
  "doc_id": "{{doc_id}}",
  "prompt_version": "{{prompt_version}}",
  "nodes": [
    {
      "document_group_id": "dg_001",
      "semantic_role": "open role",
      "projection_target_hint": "open projection target",
      "project_directly_to_question": false,
      "reason": "",
      "evidence_refs": []
    }
  ],
  "relations": [
    {
      "subject_group_id": "dg_002",
      "predicate": "is_child_of",
      "object_group_id": "dg_001",
      "predicate_open_text": "",
      "evidence_refs": [],
      "confidence": "low|medium|high",
      "reason": ""
    }
  ],
  "overlap_resolutions": [
    {
      "block_ref": "",
      "primary_owner_group_id": "",
      "secondary_group_ids": [],
      "secondary_usage": "",
      "reason": ""
    }
  ],
  "open_issues": []
}
```
