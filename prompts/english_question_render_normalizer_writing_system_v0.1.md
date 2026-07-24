{{common_prompt}}

Writing-Specific Rules

Restore visible writing surfaces when they are part of the activity: email template, answer lines, checklist table, response paper, rubric, or review table.
If asset_refs.writing_surface_refs is non-empty, add "writing_surface" to rendering_blocks and keep the visible surface in stem_markdown.
If the source page image visibly contains answer lines under translation, fill-blank, or writing prompts, preserve those lines in stem_markdown even when asset_refs.writing_surface_refs is empty.
If the source page shows a checklist/table and its rows/columns are clear, render it as a Markdown table.
For text-only writing drills, use standard_question.context and standard_question.stem as the primary display stem. Do not import generic task wrappers from final_markdown unless the same wording is visible in the source page or standard_question fields.
Do not add a new task instruction, English explanation heading, or polished prompt that is not present in the packet text, final_markdown, or source image.
If the source stem is only a label such as a practice number and the available content is an answer/model essay, do not reconstruct the missing writing prompt from the answer.
If the packet is a model answer, template, example explanation, or mixed parent material, prefer non-direct admission posture rather than a standalone question.
