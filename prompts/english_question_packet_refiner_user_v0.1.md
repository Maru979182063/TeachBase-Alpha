Refine this one source-backed packet candidate into one standard question packet.

Task boundary:
- This is one packet only.
- Use only text and refs already present in the input.
- The main deliverable is final_markdown: one readable but source-faithful rendering of the provided fields.
- Standardize Markdown headings, lists, tables, options, answer, analysis, translation, examples, and rubric sections.
- Repair obvious broken words, stray wrapper labels, duplicated labels, awkward line breaks, and local OCR/VLM spacing artifacts only when the intended text is clear from the same packet.
- Improve structure by moving exact copied source text to the correct section; do not add new wording, task instructions, or missing-answer placeholders.
- You may remove wrapper labels such as "【答案】", "答案:", "【翻译】", "【解析】" from the corresponding field when the remaining content is unchanged.
- You may split multiple-choice options into the options array when they are explicitly present.
- You may keep table/fill-in content as plain text when it cannot be losslessly split.
- Preserve visible fill-in blanks, underline runs, Markdown tables, answer lines, checklist rows, and response-surface text.
- If one answer is missing but other answers are present, keep only the source-backed answers and record the missing item in missing_fields; do not write a placeholder inside answer.
- Preserve translation evidence in standard_question.translation when translated text is already present in the input packet.
- Do not hide translation evidence by appending it to unrelated fields.
- Keep visual_refs and writing_surface_refs as asset refs; do not invent explanatory surface notes.
- If a field is missing in input, keep it empty and list it in missing_fields.
- If an answer/analysis is partial, keep the available text and mark REFINED_NEEDS_REVIEW.
- If projection_status is PRESERVED_NON_DIRECT, preserve the material but do not force it into a direct question.

Input packet:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "refined_question_packet_v0.1",
  "doc_id": "{{doc_id}}",
  "source_packet_id": "{{source_packet_id}}",
  "source_group_id": "{{source_group_id}}",
  "prompt_version": "{{prompt_version}}",
  "packet_family": "reading|grammar|writing|vocabulary|knowledge|open",
  "refine_status": "REFINED_READY|REFINED_NEEDS_REVIEW|PRESERVED_NON_DIRECT|REFINE_FAILED",
  "question_type": "open descriptive type",
  "final_markdown": "## 题目\n...\n\n## 答案\n...",
  "standard_question": {
    "title": "",
    "passage": "",
    "stem": "",
    "options": [
      {"label": "A", "text": ""}
    ],
    "answer": "",
    "analysis": "",
    "translation": "",
    "context": "",
    "examples": "",
    "rubric": ""
  },
  "source_refs": {
    "passage_refs": [],
    "stem_refs": [],
    "option_refs": [],
    "answer_refs": [],
    "analysis_refs": [],
    "translation_refs": [],
    "context_refs": [],
    "example_refs": [],
    "rubric_refs": []
  },
  "asset_refs": {
    "visual_refs": [],
    "writing_surface_refs": [],
    "page_image_refs": []
  },
  "missing_fields": [],
  "warnings": [],
  "normalization_actions": []
}
```
