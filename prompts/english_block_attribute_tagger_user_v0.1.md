Tag attributes for the existing Node1a blocks on this single page.

Document id: {{doc_id}}
Page number: {{page_number}}
Prompt version: {{prompt_version}}

Important:
- The `blocks` below are fixed evidence from Node1a.
- The `page_visual_flags` below are page-level observations from Node1a.
- You must not change text.
- You must not output text.
- You must not output evidence notes or free-text explanations.
- Return one tag for each block_id, and only those block_id values.

Page visual flags:
{{page_visual_flags_json}}

Node1a blocks:
{{blocks_json}}

Return exactly this JSON shape:

{
  "schema": "block_attribute_tags_v0.3",
  "doc_id": "{{doc_id}}",
  "page": {{page_number}},
  "prompt_version": "{{prompt_version}}",
  "tags": [
    {
      "block_id": "b1",
      "visual_form": "plain_text|heading|list|table|diagram|question_stem|options|answer_key|worked_example|writing_surface|image|mixed|unknown",
      "content_role": "navigation|knowledge_explanation|reading_passage|activity_instruction|student_task|solution_reference|analysis_explanation|translation|example|visual_structure|response_surface|teacher_note|unknown",
      "relation_hint": "none|introduces_following|depends_on_previous|answer_for_previous|analysis_for_previous|surface_for_previous|context_for_following|unknown",
      "composition_relevance": "main_candidate|context_candidate|evidence_only|unknown",
      "relevance_confidence": "low|medium|high",
      "requires_visual_preservation": false,
      "preservation_reason": "none|table_layout_needed|diagram_layout_needed|writing_surface_needed|checklist_or_form_needed|image_content_needed|spatial_relation_needed|unknown",
      "confidence": "low|medium|high"
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
- `tags.length` must equal the number of input blocks.
- Every input `block_id` must appear exactly once.
- Do not output any `text` field.
- Do not output any `evidence_note` field.
- `requires_visual_preservation` should be true only when plain text is insufficient to preserve important layout/visual information.
- For ordinary headings and prose, use `requires_visual_preservation=false`.
- For tables, diagrams, checklists, forms, response areas, writing paper, or images, usually use `requires_visual_preservation=true`.
- `composition_relevance` is a routing hint for later composition, not a final question/release decision.
- Use `main_candidate` for direct question/activity material: passage, task, options, answer, analysis, translation, response surface, writing paper, table/diagram/form needed by an activity.
- Use `context_candidate` for nearby supporting context: activity headings, worked examples, grammar method structures, problem-solving frameworks, or knowledge blocks that prepare following tasks.
- Use `evidence_only` for page chrome, general course goals, general introductions, and remote background text not tied to a visible activity on this page.
- Broad lesson title, course objective, course connection, importance paragraph, and generic knowledge introduction are usually `evidence_only` unless they directly attach to a visible activity.
- Method steps, problem-solving frameworks, grammar decision structures, activity headings, and instructions attached to visible exercises are usually `context_candidate`.
- `composition_relevance=evidence_only` does not mean `content_role=unknown`; keep the best content role.
- Use `navigation` only for page chrome such as header, footer, page number, repeated brand strip, or decorative page-level elements.
- Do not use `navigation` for content section headings such as "强化训练", "审题", "答案", "例题讲解", or lesson titles. Tag them by teaching role instead.
- If unsure, use `unknown` and confidence `low`.
- If the page has no issue, use an empty `qa_flags` array.
