Normalize display formatting for this one question packet.

Prompt version: {{prompt_version}}
Document: {{doc_id}}
Source packet: {{source_packet_id}}
Source group: {{source_group_id}}

Input JSON:

{{input_json}}

Return one JSON object with:

{
  "schema": "rendered_question_record_v0.1",
  "doc_id": "...",
  "source_packet_id": "...",
  "source_group_id": "...",
  "prompt_version": "...",
  "render_status": "READY | NEEDS_REVIEW | SOURCE_IMAGE_REQUIRED | BLOCKED",
  "display_question": {
    "title": "...",
    "stem_markdown": "...",
    "answer_markdown": "...",
    "analysis_markdown": "...",
    "translation_markdown": "...",
    "items": [
      {
        "index": "1",
        "prompt": "...",
        "answer": "...",
        "answer_span": "...",
        "answer_type": "...",
        "source_refs": []
      }
    ],
    "rendering_blocks": ["ordered_items", "fill_blank", "markdown_table"]
  },
  "source_refs_used": [],
  "unresolved_issues": [],
  "normalization_actions": []
}
