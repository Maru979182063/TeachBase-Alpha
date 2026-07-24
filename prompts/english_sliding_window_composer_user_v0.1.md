Group this candidate sliding window into activity/question groups.

Document id: {{doc_id}}
Current page: {{page_number}}
Window id: {{window_id}}
Prompt version: {{prompt_version}}

Window policy:
{{window_policy_json}}

Page boundary signals:
{{page_boundary_json}}

Tagged block window:
{{window_blocks_json}}

Return exactly this JSON shape:

{
  "schema": "sliding_window_groups_v0.1",
  "doc_id": "{{doc_id}}",
  "current_page": {{page_number}},
  "window_id": "{{window_id}}",
  "prompt_version": "{{prompt_version}}",
  "groups": [
    {
      "group_id": "g_001",
      "group_kind": "",
      "anchor_block_refs": [],
      "member_block_refs": [],
      "context_block_refs": [],
      "solution_block_refs": [],
      "analysis_block_refs": [],
      "translation_block_refs": [],
      "visual_block_refs": [],
      "carryover_block_refs": [],
      "open_status": "closed|open_from_previous|open_to_next|open_both|fragment|unknown",
      "confidence": "low|medium|high"
    }
  ],
  "open_continuations": [
    {
      "continuation_id": "oc_001",
      "direction": "from_previous|to_next",
      "reason": "",
      "source_block_refs": [],
      "expected_next": ""
    }
  ],
  "dedupe_hints": [
    {
      "candidate_id": "",
      "source_block_refs": [],
      "prefer_if_duplicate": true,
      "reason": ""
    }
  ],
  "qa_flags": [
    {
      "code": "",
      "severity": "warning|error",
      "message": "",
      "source_block_refs": []
    }
  ]
}

Rules:
- Use only provided `block_ref` values.
- Do not copy source text. The source text is recovered from block refs later.
- `group_kind` is open text. Use a short natural description such as "reading question group", "grammar fill activity", "knowledge structure", "writing prompt activity", or "carryover solution".
- `anchor_block_refs` are the task/prompt/stem blocks that make the group start or identity clear.
- `member_block_refs` are all direct blocks belonging to the group, including anchors, options, directions, solution, analysis, translation, and visual blocks.
- `context_block_refs` are knowledge structures, passages, method tables, or examples needed to understand the group.
- `solution_block_refs`, `analysis_block_refs`, and `translation_block_refs` must only contain blocks that clearly belong to the group.
- `visual_block_refs` are only refs to table, diagram, checklist, writing surface, response surface, or other visual blocks that appear to belong to the group. Do not judge crop completeness.
- `carryover_block_refs` are blocks that continue from a previous page or continue to a later page but should not create an independent group by themselves.
- If a solution/analysis/translation fragment appears without its task anchor, create a carryover group or unresolved group, not a normal question group.
- If evidence is incomplete, keep the group and use `open_status` honestly.
- Keep output compact. Prefer fewer well-evidenced groups over many speculative groups.
- Do not generate final question fields. Do not format stems, options, answers, explanations, or translations.
