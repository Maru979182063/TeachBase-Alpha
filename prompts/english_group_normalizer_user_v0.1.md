Normalize this document_group into field refs.

Task boundary:
- You are not building the final question.
- You are only identifying which existing block refs serve which field.
- If a field is absent in the evidence, mark it missing or not_applicable. Do not fill it.
- A block ref may appear in more than one field only when it genuinely serves both roles, for example an instruction that is also the visible stem.
- Do not duplicate a block ref across stem/answer/analysis/translation/example just because the group is related.
- Assign each block ref to the most specific visible role indicated by its own content and printed label.
- If one block physically contains mixed roles and cannot be split, put the ref in the primary field and add a `normalizer_warnings` item with code `mixed_role_block`.
- Never put answer-key refs into stem_refs, analysis_refs into stem_refs, translation_refs into stem_refs, or example_refs into answer_refs unless the same printed block is physically indivisible.
- Keep visual/table/diagram/writing-surface refs if they carry information that text alone may not preserve.

Field meanings:
- stem_refs: main task/question/prompt refs.
- option_refs: multiple-choice or selectable option refs.
- passage_refs: reading passage or shared article refs.
- answer_refs: answer key/model answer refs.
- analysis_refs: explanation/solution reasoning refs.
- translation_refs: translation refs.
- context_refs: knowledge, parent context, lead-in, or shared context refs needed to understand the activity.
- instruction_refs: activity directions such as "fill in the table", "underline", "write an email".
- example_refs: worked example refs that are part of the group.
- visual_refs: tables, diagrams, image-like structures, checklist/forms, or visual structures.
- writing_surface_refs: blank lines, answer sheet, writing area, review table, or response surface refs.
- For grammar/reading tables, use visual_refs, not writing_surface_refs.
- Use writing_surface_refs only when the block is a response area, blank writing lines, answer sheet, or writing-specific review surface.
- rubric_refs: scoring criteria or teacher rubric refs.
- other_evidence_refs: refs that belong to the group but do not fit above.
- open_issues and normalizer_warnings must be arrays of objects, never strings.
- Each issue object must have code, message, and source_block_refs.
- field_status must include every required key, including answer.

Input:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "normalized_group_record_v0.1",
  "doc_id": "{{doc_id}}",
  "document_group_id": "{{document_group_id}}",
  "prompt_version": "{{prompt_version}}",
  "record_kind": "open descriptive kind",
  "field_refs": {
    "stem_refs": [],
    "option_refs": [],
    "passage_refs": [],
    "answer_refs": [],
    "analysis_refs": [],
    "translation_refs": [],
    "context_refs": [],
    "instruction_refs": [],
    "example_refs": [],
    "visual_refs": [],
    "writing_surface_refs": [],
    "rubric_refs": [],
    "other_evidence_refs": []
  },
  "field_status": {
    "stem": "present|missing|not_applicable|uncertain|partial",
    "options": "present|missing|not_applicable|uncertain|partial",
    "passage": "present|missing|not_applicable|uncertain|partial",
    "answer": "present|missing|not_applicable|uncertain|partial",
    "analysis": "present|missing|not_applicable|uncertain|partial",
    "translation": "present|missing|not_applicable|uncertain|partial",
    "context": "present|missing|not_applicable|uncertain|partial",
    "visual_asset": "required|not_required|uncertain",
    "writing_surface": "required|not_required|uncertain"
  },
  "open_issues": [],
  "normalizer_warnings": []
}
```
