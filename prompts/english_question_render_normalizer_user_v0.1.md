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
  "admission_profile": {
    "admission_mode": "READY_DIRECT | READY_DIRECT_WITH_SURFACE | READY_WITH_PARENT_CONTEXT | READY_AS_EXAMPLE_CHILD | READY_WITH_VISUAL_PARENT | FIELD_REPAIR_THEN_READY | FIELD_REPAIR_OR_SOURCE_REVIEW | SPLIT_OR_PARENT_CLUSTER_REQUIRED | DO_NOT_IMPORT_DUPLICATE_COMPOSITE | NOT_RENDERABLE",
    "direct_import_allowed": true,
    "builder_action": "build_direct_packet",
    "parent_required": false,
    "source_review_required": false,
    "split_required": false,
    "surface_required": false,
    "visual_parent_required": false,
    "field_repairs": [],
    "reason": "short source-backed reason"
  },
  "source_refs_used": [],
  "unresolved_issues": [],
  "normalization_actions": []
}
