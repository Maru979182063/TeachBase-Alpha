Create a render instruction plan for this one refined packet.

Prompt version: {{prompt_version}}
Document: {{doc_id}}
Source packet: {{source_packet_id}}
Source group: {{source_group_id}}

Input JSON:

{{input_json}}

Return one JSON object:

{
  "schema": "render_instruction_plan_v0.1",
  "doc_id": "...",
  "source_packet_id": "...",
  "source_group_id": "...",
  "planner_version": "...",
  "plan_status": "PLAN_READY | PLAN_NEEDS_REVIEW | PLAN_BLOCKED",
  "operations": [
    {
      "op": "attach_parent_context | attach_stimulus | attach_visual_surface | attach_writing_surface | preserve_material_only | mark_review_required",
      "target_field": "",
      "source_fields": [],
      "source_refs": [],
      "reason": "short source-backed reason"
    }
  ],
  "layout_sections": [
    {
      "section_id": "s001",
      "display_area": "stem_markdown | answer_markdown | analysis_markdown | translation_markdown",
      "source_fields": ["passage | context | stem | options | answer | analysis | translation | examples | rubric | resolved_stimulus"],
      "render_as": "source_markdown | paragraph | list | table | supplement | surface",
      "reason": "why this existing field belongs in this display area"
    }
  ],
  "visual_recovered_sections": [
    {
      "section_id": "vr001",
      "display_area": "stem_markdown | answer_markdown | analysis_markdown | translation_markdown",
      "render_as": "source_markdown | paragraph | list | table | supplement | surface",
      "source_page_refs": ["page image/path or source ref used"],
      "bbox_hint": "plain visual location, e.g. middle checklist table",
      "recovered_markdown": "only text/table actually visible in the page image",
      "confidence": "high | medium | low",
      "recovery_reason": "why visual recovery is needed instead of copying packet fields"
    }
  ],
  "binding_decisions": {
    "parent_context": {
      "required": false,
      "resolved_refs": [],
      "asset_refs": [],
      "status": "BOUND | NOT_REQUIRED | UNRESOLVED | SOURCE_IMAGE_REQUIRED",
      "reason": ""
    },
    "stimulus": {
      "required": false,
      "resolved_refs": [],
      "asset_refs": [],
      "status": "BOUND | NOT_REQUIRED | UNRESOLVED | SOURCE_IMAGE_REQUIRED",
      "reason": ""
    },
    "visual_surface": {
      "required": false,
      "resolved_refs": [],
      "asset_refs": [],
      "status": "BOUND | NOT_REQUIRED | UNRESOLVED | SOURCE_IMAGE_REQUIRED",
      "reason": ""
    },
    "writing_surface": {
      "required": false,
      "resolved_refs": [],
      "asset_refs": [],
      "status": "BOUND | NOT_REQUIRED | UNRESOLVED | SOURCE_IMAGE_REQUIRED",
      "reason": ""
    }
  },
  "review_requirements": [
    {
      "code": "...",
      "message": "...",
      "source_refs": []
    }
  ]
}
