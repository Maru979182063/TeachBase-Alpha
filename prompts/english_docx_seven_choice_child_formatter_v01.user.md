Format this seven-choice-five parent-child group.

Document id: {{doc_id}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}

Parent:
```json
{{parent_json}}
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
  "schema": "english_docx_seven_choice_child_formatter_v0.1",
  "doc_id": "{{doc_id}}",
  "group_id": "{{group_id}}",
  "items": [
    {
      "item_id": "...",
      "item_no": "...",
      "source_item_no": "...",
      "display_context": "...",
      "selected_option_letters": ["A", "C", "E", "G"],
      "excluded_option_letters": ["B", "D", "F"],
      "options": "...",
      "answer": "A|B|C|D|E|F|G",
      "answer_option_text": "...",
      "analysis": "...",
      "formatted_explanation": "【答案】...\n【解析】...",
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
- Set display_context by selecting source text from the parent passage. It may be a continuous local paragraph/sentence group, or multiple source fragments joined by ` ... ` when the useful evidence is far apart.
- Prefer `source_paragraph_context` as display_context when it is supplied, reasonably short, and contains the evidence needed by raw_explanation.
- If multiple blanks appear in that paragraph, keep them in the paragraph: later blanks remain blank; earlier blanks appear as filled underlined answers.
- display_context must contain `[[CURRENT_BLANK_n]]` for the current local blank number.
- display_context must include the source sentence(s) quoted or clearly used by raw_explanation when those sentences appear in the parent passage.
- If a child contains `source_evidence_quotes`, display_context must include every quote in that list, plus the current blank. If the quote and current blank are separated, join source fragments with ` ... `.
- Do not summarize, translate, or rewrite display_context. It must be source text, with optional ` ... ` only between source-backed fragments.
- selected_option_letters must contain exactly 4 unique option letters from A-G.
- excluded_option_letters must contain exactly 3 unique option letters from A-G.
- selected_option_letters must include the supplied answer.
- excluded_option_letters must not include the supplied answer.
- selected_option_letters and excluded_option_letters together must cover all A-G letters exactly once.
- Choose excluded_option_letters by excluding the three wrong answers least relevant to the local context and raw_explanation.
- options must contain exactly the selected 4 options, copied from the parent option pool without rewriting text.
- formatted_explanation must contain exactly two sections in order: 【答案】, 【解析】.
- analysis and 【解析】 must be Chinese. Use raw_explanation as the base; do not rewrite it into English.
- analysis must explicitly use clue(s) from raw_explanation/local context and explain why the answer option fits.
- 【解析】 must retain the key English source sentence quote(s) used by raw_explanation, especially blank-before / blank-after sentences.
- Do not merely summarize the clue. If raw_explanation provides source wording, quote that source wording inside 【解析】 before giving the reasoning.
- If raw_explanation contains Chinese translation/gloss text in parentheses after an English evidence sentence or option, keep that Chinese translation/gloss in 【解析】 together with the English text.
