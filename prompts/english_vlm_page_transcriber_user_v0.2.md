Transcribe this single page image into the controlled Node1 JSON contract.

Document id: {{doc_id}}
Page number: {{page_number}}
Prompt version: {{prompt_version}}

Return exactly this JSON shape:

{
  "schema": "vlm_page_transcription_v0.2",
  "doc_id": "{{doc_id}}",
  "page": {{page_number}},
  "page_start": {
    "starts_new_part": true,
    "continues_previous": false,
    "continuation_type": "none|text_continuation|table_continuation|passage_continuation|question_continuation|answer_continuation|analysis_continuation|unknown",
    "confidence": "low|medium|high",
    "note": ""
  },
  "page_end": {
    "ends_complete": true,
    "tail_cutoff": false,
    "open_tail_type": "none|text_continuation|table_continuation|passage_continuation|question_continuation|answer_continuation|analysis_continuation|unknown",
    "confidence": "low|medium|high",
    "note": ""
  },
  "page_visual_flags": {
    "has_table": false,
    "has_diagram": false,
    "has_image": false,
    "has_writing_surface": false,
    "has_non_text_visual": false,
    "visual_review_required": false,
    "confidence": "low|medium|high"
  },
  "blocks": [
    {
      "block_id": "b1",
      "label": "header_footer|section_heading|knowledge_text|passage_text|question_text|option_text|answer_text|analysis_text|translation_text|example_text|exercise_text|table_text|diagram_text|image_caption|unknown_text",
      "text": "",
      "bbox_hint": "",
      "is_complete": true
    }
  ],
  "qa_flags": [
    {
      "code": "",
      "severity": "warning|error",
      "message": "",
      "block_ids": []
    }
  ]
}

Rules:
- `block_id` must be sequential: b1, b2, b3...
- Preserve the original language and visible punctuation as much as possible.
- For tables, transcribe visible table content in a readable table-like text form.
- For diagrams, transcribe visible text but mark the block as `diagram_text`; do not flatten the diagram as if it were ordinary prose.
- `page_visual_flags` are page-level observations only:
  - `has_table`: true if the page visibly contains a table, grid, checklist, or form.
  - `has_diagram`: true if the page visibly contains a tree diagram, flowchart, mind map, or similar visual structure.
  - `has_image`: true if the page visibly contains a photo, illustration, QR code, or non-text picture.
  - `has_writing_surface`: true if the page visibly contains blank writing lines, answer boxes, writing paper, or response area.
  - `has_non_text_visual`: true if any important object cannot be preserved by plain text alone.
  - `visual_review_required`: true whenever `has_table`, `has_diagram`, `has_image`, `has_writing_surface`, or `has_non_text_visual` is true. Otherwise false.
- If text is unclear, copy the readable part and add a `qa_flags` item.
- If the page has no issue, use an empty `qa_flags` array.
