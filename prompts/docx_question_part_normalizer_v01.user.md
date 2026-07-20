Normalize this already-grouped DOCX question into question parts.

Document id: {{doc_id}}
Question group id: {{question_group_id}}
Prompt version: {{prompt_version}}
Document solution policy hint: {{solution_policy_hint}}

Section context blocks, not part of the question body:
{{section_context_json}}

Question blocks:
{{question_blocks_json}}

Return exactly this JSON shape:

{
  "schema": "docx_question_part_normalizer_v0.1",
  "doc_id": "{{doc_id}}",
  "question_group_id": "{{question_group_id}}",
  "solution_policy": "required|optional|absent_expected|unknown",
  "parts": [
    {
      "part_type": "stem|options|subquestions|answer|explanation|teaching_note|unknown",
      "block_ids": [],
      "confidence": "low|medium|high"
    }
  ],
  "unassigned_block_ids": [],
  "warnings": []
}

Output constraints:
- Use explicit block_ids only.
- Keep block_ids in DOCX source order inside each part.
- A block_id must not appear in more than one part.
- Put unsure question-owned blocks into `unknown` or `unassigned_block_ids`.
- Do not include section_context block_ids in parts.
