# Teacher Handout Unified Skill Audit v0.1

Date: 2026-06-23

## Scope

This audit checks whether the current visual-first splitter can support three common branches inside one skill:

1. English reading teacher handouts
2. Senior-math teacher handouts
3. Junior-geometry teacher handouts

The target is not OCR completeness. The target is stable visual decomposition, component ownership, and question-slice landing.

## Current Runtime Shape

The workspace runtime is now unified in:

- `tools/teacher_pdf_visual_question_split_v02.py`

The skill entrypoint now delegates to the workspace runtime instead of maintaining a second diverging copy:

- `C:\Users\EDY\.codex\skills\teacher-handout-visual-split\scripts\teacher_pdf_visual_question_split_v02.py`

Profile routing is handled inside one runtime:

- `auto`
- `english_reading_teacher`
- `senior_math_teacher`
- `junior_geometry_teacher`

## What Was Added

### Shared routing

- Auto profile detection from path and page features
- Profile-aware component anchors
- Profile-aware question-start parsing
- Safer skipping of non-question knowledge blocks
- `TEACHER_SPLIT_MAX_PAGES` for fast audit sampling

### English branch

- OCR page-line fallback when the PDF text layer is nearly empty
- Preview OCR disabled by default for English so structure can finish first
- Output now records `line_source`

### Junior geometry branch

- Text-row anchors for `【例】`, `【变式】`, `能力进阶`, `课后练习`
- Question-start parsing expanded beyond plain `1.` style numbering

## Sample Results

### 1. Senior math

Source:

- `解三角形综合 - 教师版.pdf`

Last stable full run:

- profile: `senior_math_teacher`
- anchors: `19`
- segments: `49`
- questions: `47`

Assessment:

- The senior-math branch remains the most stable branch.
- Blue component anchors plus `考点N` are enough for full slicing on the current standard handout style.

### 2. Junior geometry

Source:

- `第2讲 倍长中线与截长补短（教师版）.pdf`

Last stable full run:

- profile: `junior_geometry_teacher`
- anchors: `40`
- segments: `68`
- questions: `34`

Assessment:

- The junior branch improved materially after adding text-row anchors.
- This confirms that middle-school geometry should not be forced into the senior-math `考点 + 蓝挂件` rule alone.

### 3. English reading

Source:

- `阅读理解体裁训练之记叙文-教师版.pdf`

Full document facts:

- total pages: `43`
- PDF text layer is effectively unusable for structure
- blue-anchor detection currently finds `0` usable component anchors on sampled pages

Latest successful sample run:

- run: `codex_profile_english_v05_sample8_20260623`
- sample pages: first `8`
- profile: `english_reading_teacher`
- line_source: `ocr_page_lines_fallback`
- anchors: `4`
- segments: `10`
- questions: `4`
- wall-clock runtime: about `308s` for 8 pages

Assessment:

- The English branch is now logically viable inside the unified skill.
- Structure can be recovered from OCR page lines when the PDF text layer is empty.
- The main issue is not correctness first. The main issue is throughput.

## Gap To Requirement

### Already close

- One skill can now host all three common branches.
- Senior math is usable.
- Junior geometry is usable.
- English can produce correct-looking structure on sampled pages.

### Still far

- English full-doc throughput is not yet production-friendly.
- The current English fallback is sequential page OCR. On the 43-page sample, it is too slow for routine use.
- The current English branch should be treated as “structure-valid, speed-not-yet-valid”.

## Root Cause Summary

### Senior math

- Best-fit branch for the original runtime assumptions.

### Junior geometry

- Needs text-row anchors because component starts are often not only blue blocks.

### English reading

- Fails both classic assumptions:
  - text layer is not reliable
  - blue component detector does not generalize to this layout

That means English currently survives only because OCR is used as a fallback for page lines. This is acceptable as a temporary bridge, but not as the final production shape.

## Recommended Next Moves

### Must go into runtime next

1. Add a lighter English title detector so we do not OCR every full page at runtime.
2. Separate “structure OCR” from “preview OCR” everywhere, not only in English.
3. Promote question-bundle mode for reading handouts when a passage plus subquestions should land as one pedagogic item.
4. Keep `line_source`, profile, and low-confidence markers in JSON so audit UI can route only hard cases out for review.

### Can wait for the audit UI

1. Teacher edits to rename component labels
2. Manual boundary correction for edge cases
3. Manual text补录 on low-confidence blocks

## Bottom Line

One unified skill is now the right direction and is partially working:

- senior math: ready
- junior geometry: ready
- English reading: structurally promising, throughput still not ready

So the current distance to your requirement is no longer “wrong architecture”. It is now mostly “English branch speed engineering”.
