Normalize this already-cut English DOCX group into field parts.

Document id: {{doc_id}}
Group id: {{group_id}}
Prompt version: {{prompt_version}}
Upstream group kind: {{group_kind}}

Section context blocks, not part of the group:
```json
{{section_context_json}}
```

Group blocks:
```json
{{group_blocks_json}}
```

Return exactly this JSON shape:
```json
{
  "schema": "english_docx_group_field_normalizer_v0.1",
  "doc_id": "{{doc_id}}",
  "group_id": "{{group_id}}",
  "normalized_kind": "grammar_cloze|cloze|reading|seven_choices_five|writing_letter|continuation_writing|mixed_or_unknown",
  "parts": [
    {
      "part_type": "source_label|instruction|passage|question_items|options|response_area|answer|guide|explanation|sample_answer|teaching_note|unknown",
      "block_ids": [],
      "confidence": "high|medium|low"
    }
  ],
  "unassigned_block_ids": [],
  "warnings": []
}
```

Output constraints:
- Use explicit block_ids only.
- A block_id must not appear in more than one part.
- Account for every group block exactly once.
- Keep evidence out of the output; use warnings only for short issues.
