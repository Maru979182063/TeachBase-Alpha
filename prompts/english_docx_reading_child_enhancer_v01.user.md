Enhance this reading parent-child group.

Document id: {{doc_id}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}

Parent:
```json
{{parent_json}}
```

Children:
```json
{{children_json}}
```

Return exactly this JSON shape:
```json
{
  "schema": "english_docx_reading_child_enhancer_v0.1",
  "doc_id": "{{doc_id}}",
  "group_id": "{{group_id}}",
  "items": [
    {
      "item_id": "...",
      "item_no": "...",
      "source_item_no": "...",
      "evidence_scope": "第一段|第二段|最后一段|表格某行|...",
      "evidence_text": "...",
      "circle_keywords": ["..."],
      "compare_type": "原词复现|同义转换|原文概括",
      "translation_pairs": [
        {
          "role": "question",
          "label": "",
          "original": "...",
          "translation": "..."
        },
        {
          "role": "option",
          "label": "A",
          "original": "...",
          "translation": "..."
        }
      ],
      "formatted_explanation": "【圈】...\n\n【找】...\n\n【比】...\n\n【答案】...\n\n【翻译】...",
      "confidence": "high|medium|low"
    }
  ],
  "warnings": []
}
```

Hard constraints:
- Return one item for every supplied child.
- item_id, item_no, and source_item_no must match the input.
- circle_keywords and the 【圈】 section may only use words or phrases that appear in the child question field. Do not circle option words or evidence words.
- compare_type must be one of the three allowed Chinese values.
- Do not overuse 原词复现. Use 原文概括 for calculation/table-summary questions; use 同义转换 when the correct option paraphrases the source.
- The 【找】 section must be a teacher-handout style explanation: source position + source evidence + Chinese paraphrase + reasoning bridge to the correct option. For 同义转换, explicitly name what source expression maps to what option expression.
- evidence_scope must identify the source location used by 【找】.
- evidence_text must be the complete source unit from the parent material. If raw_explanation says 第一段/第二段/最后一段, use the whole paragraph. If the answer comes from a table, use the relevant full row/cell group, not a clipped phrase.
- formatted_explanation must contain exactly the five required sections in order.
- In 【翻译】, translate the question and every option into Chinese. Include the English original plus the Chinese translation for the question and A/B/C/D separately.
- translation_pairs must include one question pair and every option pair.
- In 【翻译】 do not use "Question:", "问题：", "题干：", "选项A：", "Option A:", "->", or "→". Use only clean paired lines:
  English question
  中文译文
  A. English option
  中文译文
- Stop at 【翻译】. Do not include 长难句分析 or 选项词汇清单.
