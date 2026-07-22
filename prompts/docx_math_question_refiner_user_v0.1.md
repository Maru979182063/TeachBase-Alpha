Refine this one source-backed math draft.

Task boundary:
- This is one draft only.
- The upstream builder has already grouped the question and assigned fields.
- Preserve upstream field boundaries: context stays context, stem stays stem, subquestions stay subquestions, options stay options, answer stays answer, explanation stays explanation, teaching_note stays teaching_note.
- Use only the text, block ids, and asset ids present in the input.
- The output Markdown should be suitable for frontend rendering and later database storage.
- Protect formula semantics: do not change mathematical meaning.
- Protect asset tokens: every output image token must use an input asset_id.
- Protect source refs: every source_refs value must come from input field block_ids or source_refs.
- If the draft is an original worksheet with no answer, keep answer/explanation empty and use solution_policy to decide status.
- Do not move answer text out of explanation unless the upstream answer field is empty and the explanation field begins with an explicit answer wrapper such as "【答案】".
- If a draft is a composite method/reading task, preserve the upstream composite structure. Do not split or regroup it.
- If condition groups or equation systems appear, add condition_groups entries and also render them cleanly in Markdown.
- If formula_risk_spans is non-empty, repair those exact spans in the relevant field. Do not ignore them. Convert malformed `\left{... \right` or flattened equation groups into valid `cases` or `aligned` Markdown math. If you cannot safely repair a marked span from source evidence, return REFINED_NEEDS_REVIEW and explain it in warnings.
- If upstream subquestions are explicit, preserve them in subquestions. Do not move them into stem_md. If upstream subquestions are empty, do not invent subquestions from stem/explanation.
- Preserve every visible subquestion label from the source in each subquestion item. Do not remove `(1)`, `（2）`, `①`, `②`, or similar labels.
- Do not summarize, compress, or rewrite long solution steps. Clean notation in place.
- Before returning, scan the output and fix bare LaTeX command text such as sqrt{...}, frac{...}{...}, times, div, le, ne, angle, triangle.
- Before returning, scan the output and ensure no unresolved `\left{`, no `\right` without delimiter, and no flattened equation group remains.
- Use only these question_type values: single_choice, multiple_choice, fill_blank, solution, composite.
- Do not output placeholder array items. If there are no subquestions, output "subquestions": []. If there are no options, output "options": [].
- Only single_choice and multiple_choice may contain options.
- Every subquestion item must have non-empty markdown.
- Every option item must have a non-empty label and non-empty markdown.
- Do not compose the final display body. `standard_question.render_markdown` is a code-generated projection field. Return it as an empty string; the local pipeline will synthesize it from title/stem/subquestions/options/answer/explanation/teaching_note after validation.

Input draft:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "docx_math_refined_question_packet_v0.1",
  "doc_id": "{{doc_id}}",
  "source_draft_id": "{{source_draft_id}}",
  "source_group_id": "{{source_group_id}}",
  "prompt_version": "{{prompt_version}}",
  "refine_status": "REFINED_READY|REFINED_NEEDS_REVIEW|REFINE_FAILED",
  "question_type": "single_choice|multiple_choice|fill_blank|solution|composite",
  "solution_policy": "required|absent_expected|partial_solution_expected|unknown",
  "standard_question": {
    "title": "",
    "stem_md": "",
    "subquestions": [],
    "options": [],
    "answer_md": "",
    "explanation_md": "",
    "teaching_note_md": "",
    "context_md": "",
    "render_markdown": ""
  },
  "condition_groups": [
    {
      "group_id": "cg_001",
      "kind": "conditions|equations|piecewise|aligned|unknown",
      "markdown": "",
      "items": ["item 1", "item 2"],
      "source_block_ids": []
    }
  ],
  "source_refs": {
    "context_refs": [],
    "stem_refs": [],
    "subquestion_refs": [],
    "option_refs": [],
    "answer_refs": [],
    "explanation_refs": [],
    "teaching_note_refs": [],
    "asset_block_refs": []
  },
  "asset_refs": {
    "visual_refs": []
  },
  "missing_fields": [],
  "warnings": [
    {"code": "", "message": "", "refs": []}
  ],
  "normalization_actions": []
}
```
