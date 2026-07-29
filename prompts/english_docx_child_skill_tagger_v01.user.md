Tag the child items in this English parent group.

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
      "primary_label_zh": "",
      "primary_label_en": "",
      "category": "grammar|vocabulary|reading_comprehension|discourse|writing|continuation_writing|mixed|unknown",
      "secondary_tags_zh": [],
      "evidence": "short reason in Chinese",
      "confidence": "high|medium|low"
    }
  ],
  "warnings": []
}
```

Output constraints:
- Include one item record for every supplied child item.
- Use the same item_id and item_no as supplied.
- Keep labels short.
- Evidence should be one short Chinese phrase or sentence.
