Group this DOCX question-content sliding window into draft question packets.

Document id: {{doc_id}}
Window id: {{window_id}}
Prompt version: {{prompt_version}}

Window policy:
{{window_policy_json}}

Block window:
{{window_blocks_json}}

Return exactly this JSON shape:

{
  "schema": "docx_question_grouper_v0.1",
  "doc_id": "{{doc_id}}",
  "window_id": "{{window_id}}",
  "prompt_version": "{{prompt_version}}",
  "draft_packets": [
    {
      "draft_id": "dq_001",
      "source_block_ids": [],
      "start_block_id": "",
      "end_block_id": "",
      "completion_status": "complete|continues_from_previous|continues_to_next|fragment|unknown",
      "confidence": "low|medium|high",
      "reason": ""
    }
  ],
  "open_continuations": [
    {
      "continuation_id": "oc_001",
      "direction": "from_previous|to_next",
      "source_block_ids": [],
      "reason": ""
    }
  ],
  "dedupe_hints": [
    {
      "candidate_id": "",
      "source_block_ids": [],
      "prefer_if_duplicate": true,
      "reason": ""
    }
  ],
  "qa_flags": [
    {
      "code": "",
      "severity": "warning|error",
      "message": "",
      "source_block_ids": []
    }
  ]
}

Rules:
- `previous_tail_blocks` and `next_head_blocks` are context. Prefer packets anchored by `current_blocks`.
- `start_block_id` and `end_block_id` must cover the continuous DOCX range of the draft packet.
- `source_block_ids` should list the core question-content evidence blocks you used for the packet. It may skip blank or internal heading blocks because the assembler expands the final packet by start/end.
- Include all nearby `question_content` blocks that belong to the same question, including images, tables, options, answers, and explanations.
- Keep separate numbered questions as separate packets.
- If a current block is clearly continuation from the previous window, include it in a packet with `completion_status="continues_from_previous"`.
- If a current packet clearly continues beyond the current window, use `completion_status="continues_to_next"`.
- If evidence is incomplete, output the packet and add a `qa_flags` warning instead of dropping it.
