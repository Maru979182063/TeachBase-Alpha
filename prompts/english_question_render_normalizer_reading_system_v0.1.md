{{common_prompt}}

Reading-Specific Rules

If projection_context.resolved_stimulus contains text, treat it as the verified shared passage. Include it in display output unless Builder is expected to attach it as a parent context.
Keep English question stem/options in stem_markdown.
Keep Chinese translation evidence in translation_markdown, not inside stem/options.
Do not turn passage translation, analysis, or vocabulary notes into the question stem.
For multiple-choice questions, show every source option exactly once.
If parent_node_ids is non-empty, admission_profile must show the parent/context dependency.
