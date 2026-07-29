Create a local-number edit plan for this normalized parent group.

Document key: {{doc_key}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}
Parent kind: {{parent_kind}}

Child items:
```json
{{items_json}}
```

Fields:
```json
{{fields_json}}
```

Return exactly this JSON shape:
```json
{
  "schema": "english_docx_group_local_number_normalizer_v0.1",
  "doc_id": "{{doc_key}}",
  "group_id": "{{group_id}}",
  "edits": [
    {
      "field": "passage|question_items|options|answer|guide|explanation|sample_answer|teaching_note|instruction",
      "role": "question_number|option_row_number|answer_number|explanation_number|blank_marker_number|other_item_number",
      "source_item_no": "",
      "item_no": "",
      "original_token": "exact visible numbering token copied from the field, e.g. 21. or （21）",
      "replacement_token": "same numbering style with item_no, e.g. 6. or （6）",
      "confidence": "high|medium|low"
    }
  ],
  "warnings": []
}
```

Output constraints:
- Use edits only for source_item_no values that differ from item_no.
- original_token must be copied exactly from the supplied field text.
- replacement_token must preserve the numbering style of original_token.
- Do not include edits for ordinary numbers that are not child-item labels.
