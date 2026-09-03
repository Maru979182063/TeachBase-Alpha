Cut boundaries for this DOCX sliding window.

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
  "new_question_starts": [
    {
      "block_id": "b_000001",
      "confidence": "high|medium|low",
      "evidence": "short reason based on the block content"
    }
  ],
  "continuation_groups": [
    {
      "block_ids": ["b_000002"],
      "belongs_to": "previous_question|visible_question_start",
      "question_start_block_id": "b_000001 or null",
      "confidence": "high|medium|low",
      "evidence": "short reason"
    }
  ],
  "context_only_blocks": [
    {
      "block_ids": ["b_000003"],
      "confidence": "high|medium|low",
      "evidence": "short reason"
    }
  ],
  "decorative_or_waste_blocks": [
    {
      "block_ids": ["b_000004"],
      "confidence": "high|medium|low",
      "evidence": "short reason"
    }
  ],
  "uncertain_blocks": [
    {
      "block_ids": ["b_000005"],
      "evidence": "why uncertain"
    }
  ],
  "qa_flags": []
}
```

Rules:
- Every id in current_blocks must appear exactly once across new_question_starts, continuation_groups, context_only_blocks, decorative_or_waste_blocks, or uncertain_blocks.
- previous_tail_blocks and next_head_blocks are context only. Do not account for them unless they explain evidence.
- If a current block is only answer/analysis/solution/comment for a question that started before the current window, use continuation_of_previous.
- If a current block is only a subquestion answer, solution step, or commentary for an existing question, do not mark it as new_question_start.
- In answer/solution regions, do not start a new packet from numbered answer text unless the block itself contains a complete new standalone question stem.
- In answer/solution regions, if the current block begins a complete answer or explanation for a different main question, mark it as a new_question_start so separate main-question solutions do not collapse into one packet.
- If a current block clearly starts a new question, put it in new_question_starts even if the rest of the question continues later.
- Keep evidence short. Do not output rewritten content.
