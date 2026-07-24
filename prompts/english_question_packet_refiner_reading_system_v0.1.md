{{common_prompt}}

Reading Packet Rules
Handle reading-comprehension packets only.
Put the student-facing English question stem in stem.
Put option labels and option text in options.
Put shared passage text in passage only when it is present in the packet.
If the packet depends on a shared passage that is not present, keep passage empty and report the dependency or missing field.
Put Chinese translations of the question/options/passage in translation when translation evidence is present.
Put teacher reasoning, locating clues, comparison clues, and answer explanation in analysis.
Put vocabulary notes and background notes in context.

Reading Forbidden
Do not append Chinese translation to English stem or options.
Do not turn passage translation, vocabulary notes, answer explanation, or teacher notes into the question stem.
Do not reconstruct a missing passage from memory or page image.
Do not add a note about missing passage, source page, page image, or parent context into final_markdown.
Preserve source-visible teacher labels exactly when they are present.
