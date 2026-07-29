Classify problem-facing fields for this question's problem zone only.

Document id: {{doc_id}}
Question group id: {{question_group_id}}
Prompt version: {{prompt_version}}

Problem-zone blocks:
{{problem_blocks_json}}

Return exactly this JSON shape:

{
  "schema": "docx_question_part_twostage_problem_v0.1",
  "doc_id": "{{doc_id}}",
  "question_group_id": "{{question_group_id}}",
  "parts": [
    {
      "part_type": "stem|subquestions|options|unknown",
      "block_ids": [],
      "confidence": "low|medium|high"
    }
  ],
  "warnings": []
}

Output constraints:
- Use explicit block_ids only.
- Every problem-zone block must appear exactly once across parts.
- Do not explain your answer.
