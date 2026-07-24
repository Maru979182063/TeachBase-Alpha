Refine this segment of a long composite math question.

Use only the provided blocks.
Keep the segment label.
Do not repeat the label inside prompt_md, answer_md, or explanation_md; the label field already stores it.
If this is a parent segment with children, keep only the parent setup in prompt_md and do not duplicate child task text.
If answer/explanation text contains multiple answers, extract only the part relevant to this segment when clear.
If it is not clear, preserve the text and add a warning.
Use Chinese mathematical wording from the source. Do not replace "或" with English "or".
Before returning, verify:
- no answer_md/prompt_md/explanation_md has an odd number of "$";
- LaTeX commands keep their backslash after JSON parsing, especially \triangle, \angle, \frac, \sqrt, \le, \ge, \ne, \parallel, \perp;
- image tokens stay on their own readable line when they interrupt prose.

Input:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "docx_math_long_composite_segment_v0.1",
  "segment_id": "{{segment_id}}",
  "label": "{{label}}",
  "level": 1,
  "parent_id": "",
  "role": "subquestion",
  "prompt_md": "",
  "answer_md": "",
  "explanation_md": "",
  "asset_ids": [],
  "source_refs": {
    "question_block_ids": [],
    "answer_block_ids": [],
    "explanation_block_ids": []
  },
  "warnings": []
}
```
