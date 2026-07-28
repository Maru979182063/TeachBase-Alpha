Classify broad zones for this already-grouped DOCX question.

Document id: {{doc_id}}
Question group id: {{question_group_id}}
Prompt version: {{prompt_version}}
Solution policy hint: {{solution_policy_hint}}

Section context blocks, not part of the question body:
{{section_context_json}}

Question blocks:
{{question_blocks_json}}

Return exactly this JSON shape:

{
  "schema": "docx_question_part_twostage_zone_v0.1",
  "doc_id": "{{doc_id}}",
  "question_group_id": "{{question_group_id}}",
  "solution_policy": "required|optional|absent_expected|unknown",
  "zones": [
    {
      "zone_type": "problem_zone|answer_zone|explanation_zone|teaching_zone|other_evidence",
      "block_ids": [],
      "confidence": "low|medium|high"
    }
  ],
  "warnings": []
}

Output constraints:
- Use explicit block_ids only.
- Every question block must appear exactly once across zones.
- Do not include section_context block_ids.
- Do not explain your answer.
