Refine this one source-backed math draft.

Task boundary:
- This is one draft only.
- Use only the text, block ids, and asset ids present in the input.
- The output Markdown should be suitable for frontend rendering and later database storage.
- Protect formula semantics: do not change mathematical meaning.
- Protect asset tokens: every output image token must use an input asset_id.
- Protect source refs: every source_refs value must come from input field block_ids or source_refs.
- If the draft is an original worksheet with no answer, keep answer/explanation empty and use solution_policy to decide status.
- If answer text is embedded in explanation, move the answer content into answer_md only when it is explicitly present.
- If a draft is a composite method/reading task, keep it as one composite question and organize its material, examples, and tasks clearly.
- If condition groups or equation systems appear, add condition_groups entries and also render them cleanly in Markdown.
- If subquestions are explicit, put only the shared scenario/instruction in stem_md and put each task in subquestions. Do not duplicate the same subquestion in stem_md and subquestions.
- Before returning, scan the output and fix bare LaTeX command text such as sqrt{...}, frac{...}{...}, times, div, le, ne, angle, triangle.
- Use only these question_type values: single_choice, multiple_choice, fill_blank, solution, composite.
- Do not output placeholder array items. If there are no subquestions, output "subquestions": []. If there are no options, output "options": [].
- Only single_choice and multiple_choice may contain options.
- Every subquestion item must have non-empty markdown.
- Every option item must have a non-empty label and non-empty markdown.

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
