Create child item groups for this normalized English DOCX group.

Document id: {{doc_id}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}
Normalized kind: {{normalized_kind}}

Field block ids:
```json
{{field_block_ids_json}}
```

Fields:
```json
{{fields_json}}
```

Source blocks for this group:
```json
{{source_blocks_json}}
```

Return exactly this JSON shape:
```json
{
  "schema": "english_docx_group_itemizer_v0.1",
  "doc_id": "{{doc_id}}",
  "group_id": "{{group_id}}",
  "parent_kind": "{{normalized_kind}}",
  "shared_fields": {
    "source_label": true,
    "instruction": true,
    "passage": true,
    "options": true,
    "guide": true,
    "sample_answer": true,
    "teaching_note": true
  },
  "items": [
    {
      "item_id": "stable id like eg_0001_q_001",
      "item_no": "parent-local display number, starting at 1",
      "source_item_no": "source number or blank number if different",
      "item_kind": "grammar_blank|cloze_choice|reading_question|seven_choice_blank|writing_task|continuation_writing_task|unknown",
      "anchor": "short source anchor, e.g. [[BLANK_1]], 31., paragraph 1",
      "question_block_ids": [],
      "option_block_ids": [],
      "response_area_block_ids": [],
      "answer_text": "",
      "explanation_block_ids": [],
      "confidence": "high|medium|low"
    }
  ],
  "unassigned_item_block_ids": [],
  "warnings": []
}
```

Output constraints:
- Use only block ids present in source_blocks.
- item_id values must be unique within this group.
- item_no is the display number inside this parent group, starting from 1.
- source_item_no can keep the original source number, such as 16 or 31.
- Keep block id arrays in source order.
- answer_text should be copied exactly from the provided answer field, as a short answer for this one item.
- For shared option banks, leave option_block_ids empty and set shared_fields.options to true.
- For item-owned A/B/C/D options, put those option block ids on the item.
- Keep warnings short.
