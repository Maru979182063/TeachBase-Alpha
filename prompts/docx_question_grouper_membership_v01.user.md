Group these DOCX blocks by explicit membership.

Document id: {{doc_id}}
Sample id: {{sample_id}}
Prompt version: {{prompt_version}}

Blocks:
{{blocks_json}}

Return exactly this JSON shape:

{
  "schema": "docx_question_grouper_membership_v0.1",
  "doc_id": "{{doc_id}}",
  "sample_id": "{{sample_id}}",
  "groups": [
    {
      "group_id": "g_001",
      "block_ids": [],
      "confidence": "low|medium|high"
    }
  ],
  "ungrouped_block_ids": []
}

Rules:
- `block_ids` are explicit membership only.
- A block that starts a new question or new question group must start a new group.
- Do not include a new question's first block in the previous group.
- Do not include image-only blocks in the previous group if they belong to the next visible question.
- Keep each group internally ordered by DOCX block order.
- If unsure whether a block belongs to a neighboring group, prefer a separate group over merging two questions.
