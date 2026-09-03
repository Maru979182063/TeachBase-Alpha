Tag the cloze-choice child items in this English parent group.

Document key: {{doc_key}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}
Parent kind: {{parent_kind}}

Children:
```json
{{children_json}}
```

Return exactly this JSON shape:
```json
{
  "schema": "english_docx_child_skill_tagger_v0.1",
  "doc_id": "{{doc_key}}",
  "group_id": "{{group_id}}",
  "items": [
    {
      "item_id": "",
      "item_no": "",
      "relevant_context": "",
      "primary_label_zh": "",
      "primary_label_en": "",
      "category": "vocabulary|mixed",
      "secondary_tags_zh": [],
      "evidence": "short reason in Chinese",
      "confidence": "high|medium|low"
    }
  ],
  "warnings": []
}
```

Output constraints:
- Include one item record for every supplied cloze-choice child item.
- Use the same item_id and item_no as supplied.
- `primary_label_zh` must be exactly one allowed `词性｜解题策略` label from the system prompt.
- `relevant_context` must preserve and include the supplied `[[CURRENT_BLANK_n]]` token.
- Do not use `...` or `…` as an omission placeholder.
- `evidence` should briefly explain the clue from the original text or explanation.
