Transcribe this single page image into the controlled Node1 JSON contract with block content attributes.

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
  "blocks": [
    {
      "block_id": "b1",
      "label": "header_footer|section_heading|knowledge_text|passage_text|question_text|option_text|answer_text|analysis_text|translation_text|example_text|exercise_text|table_text|diagram_text|image_caption|unknown_text",
      "text": "",
      "bbox_hint": "",
      "is_complete": true,
      "content_attributes": {
        "visual_form": "plain_text|heading|list|table|diagram|question_stem|options|answer_key|worked_example|writing_surface|unknown",
        "learning_function": "navigation|knowledge_explanation|passage|activity_instruction|student_task|solution_reference|teacher_annotation|visual_structure|surface_for_response|unknown",
        "requires_visual_preservation": false,
        "attribute_confidence": "low|medium|high",
        "evidence_note": ""
      }
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
- Keep `text` as visible transcription only; attributes must not change or summarize the text.
- `content_attributes` are page-local observations, not final semantic facts.
- For tables, transcribe visible table content in readable table-like form and set `visual_form` to `table`.
- For diagrams, transcribe visible text but set `visual_form` to `diagram`.
- If a block is a blank response area, writing paper, check table, rubric table, or visual surface needed to perform an activity, set `requires_visual_preservation` to true.
- If a block is just ordinary prose text, set `requires_visual_preservation` to false.
- If unclear, set `attribute_confidence` to `low` and add a `qa_flags` item.
- If the page has no issue, use an empty `qa_flags` array.
