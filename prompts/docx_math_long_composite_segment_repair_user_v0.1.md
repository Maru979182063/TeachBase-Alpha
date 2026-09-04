Repair this refined long-composite segment.

You are given:
- the original segment input;
- the previous segment output;
- validation errors.

Fix only field shape and Markdown syntax.
Do not change mathematical meaning.
Do not add facts, numbers, answers, diagrams, block ids, or asset ids.
Preserve the segment label and role.
Make sure answer_md, prompt_md, and explanation_md have balanced "$" delimiters.
Escape LaTeX backslashes correctly for JSON so the parsed text contains commands such as \triangle, \angle, \frac, \sqrt, \parallel, and \perp.

Original segment input:
```json
{{input_json}}
```

Previous segment output:
```json
{{previous_output_json}}
```

Validation errors:
```json
{{validation_errors_json}}
```

Return JSON only using schema docx_math_long_composite_segment_v0.1.
