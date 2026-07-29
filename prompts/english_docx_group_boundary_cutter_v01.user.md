Identify source-supported group boundaries for this English DOCX sliding window.

Document id: {{doc_id}}
Window id: {{window_id}}

Window payload:
```json
{{window_payload_json}}
```

Return this JSON shape:
```json
{
  "window_id": "same window id",
  "group_start_events": [
    {
      "block_id": "b_000001",
      "group_kind": "grammar_cloze|cloze|reading|seven_choices_five|writing_letter|continuation_writing|mixed_or_unknown",
      "confidence": "high|medium|low",
      "evidence_block_ids": ["b_000001"],
      "evidence": "short reason"
    }
  ],
  "group_end_events": [
    {
      "block_id": "b_000020",
      "group_start_block_id_if_visible": "b_000001 or null",
      "confidence": "high|medium|low",
      "evidence_block_ids": ["b_000018", "b_000020"],
      "evidence": "short reason"
    }
  ],
  "block_accounting": [
    {
      "block_id": "b_000002",
      "role": "document_title|section_heading|group_heading|passage|question_items|options|answer_marker|answer|guide|analysis|instruction|response_area|image|continuation|waste|uncertain",
      "boundary_role": "opening_anchor|unit_content|support_anchor|region_context|document_context|spacer|waste|uncertain",
      "belongs_to": "new_group_in_current|previous_group|visible_group_start|context_only|waste|uncertain",
      "group_start_block_id_if_visible": "b_000001 or null",
      "confidence": "high|medium|low",
      "evidence": "short reason"
    }
  ],
  "uncertain_blocks": [
    {
      "block_id": "b_000005",
      "evidence": "why uncertain"
    }
  ],
  "qa_flags": []
}
```

Judgment guide:
- Account for every id in current_blocks exactly once in block_accounting.
- Use previous_tail_blocks and next_head_blocks only as context.
- Reference only current block ids in group_start_events and group_end_events.
- Emit a boundary event when the current block is supported by local source evidence as the opening or closure of a complete content unit.
- Leave starts or ends empty when the window only contains context, continuation, or incomplete evidence.
- Assign roles by content function inside the unit: task opening, passage, questions, options, answer marker, answer, guide, analysis, response area, image, continuation, context, or uncertainty.
- Assign boundary_role by cutting function: opening anchor, unit content, support material, region context, document context, spacer, waste, or uncertainty.
- Interpret numbering and repeated labels within their surrounding source region.
- Treat region headings as context for subsequent units.
- Treat concrete exercise/source labels as opening anchors when they introduce the passage or prompt that follows.
- Attach a source/provenance line to the following passage or prompt when they form one source-local unit.
- Attach answer keys, guide notes, explanations, vocabulary notes, sentence notes, and sample-answer markers to the unit they support.
- Use the last substantive answer, analysis, guide, or sample-answer block as the closure point when a unit ends before a spacer or the next unit.
- Keep evidence short and source-based.
