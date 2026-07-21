Repair this one refined math packet.

You are given:
- the original source-backed draft;
- the previous model output;
- local validation errors.

Your job:
- Return one corrected JSON packet using schema docx_math_refined_question_packet_v0.1.
- Preserve the original meaning and all valid source-backed content.
- Fix only field placement, Markdown quality, invalid enum values, empty array items, invalid asset refs, invalid source refs, and obvious formula markup.
- If validation errors include bad_left_brace_delimiter, bad_right_missing_delimiter, or possible_equation_group_flattened, repair the marked formula structure in place. Prefer valid `cases` or `aligned` Markdown math, using only source-visible equations.
- Do not add facts, numbers, answers, diagrams, or solution steps.
- Do not merge with another draft.
- Do not output placeholder subquestions or placeholder options.
- Use only these question_type values: single_choice, multiple_choice, fill_blank, solution, composite.
- Use [] for subquestions when there are no explicit subquestions.
- Use [] for options unless question_type is single_choice or multiple_choice.
- Every subquestion item must have non-empty markdown.
- Every option item must have non-empty label and non-empty markdown.
- Every source_refs value must come from the original draft source refs or field block_ids.
- Every output image token must use an input asset_id.

Original source-backed draft:
```json
{{input_json}}
```

Previous output:
```json
{{previous_output_json}}
```

Validation errors:
```json
{{validation_errors_json}}
```

Return JSON only.
