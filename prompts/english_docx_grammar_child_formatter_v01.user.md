Format this grammar cloze parent-child group.

Document id: {{doc_id}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}

Parent:
```json
{{parent_json}}
```

Sibling answers:
```json
{{sibling_answers_json}}
```

Blank display map:
```json
{{blank_display_map_json}}
```

Children:
```json
{{children_json}}
```

Return exactly this JSON shape:
```json
{
  "schema": "english_docx_grammar_child_formatter_v0.1",
  "doc_id": "{{doc_id}}",
  "group_id": "{{group_id}}",
  "items": [
    {
      "item_id": "...",
      "item_no": "...",
      "source_item_no": "...",
      "display_context": "...",
      "test_point": "考查...",
      "answer": "...",
      "translation": "...",
      "analysis": "...",
      "formatted_explanation": "【判断考点】...\n【答案】...\n【翻译】...\n【解析】...",
      "confidence": "high|medium|low"
    }
  ],
  "warnings": []
}
```

Hard constraints:
- Return one item for every supplied child.
- item_id, item_no, and source_item_no must match input.
- answer must exactly match the supplied child answer.
- Each child has `context_candidates`. Set display_context to one of those candidate strings exactly.
- Prefer the shortest candidate that still supports the explanation.
- Do not generate, rewrite, translate, shorten, or repair display_context yourself.
- Do not change quotes, Chinese glosses, parentheses, punctuation, blank tokens, or spacing inside words in the chosen candidate.
- formatted_explanation must contain exactly the four required sections in order: 【判断考点】, 【答案】, 【翻译】, 【解析】.
- test_point, answer, translation, and analysis must also be filled as standalone fields. Do not leave analysis empty after writing 【解析】.
- Do not output 【详解】 as a section. Its content may be used inside 【解析】.
- Do not invent grammar labels if raw_explanation already states the test point.
