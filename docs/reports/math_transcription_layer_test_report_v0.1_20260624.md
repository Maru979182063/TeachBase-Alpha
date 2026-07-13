# Math Transcription Layer Test Report v0.1

Date: 2026-06-24

## Scope

This round adds a first-pass question transcription layer on top of the existing visual-first splitter.

Target business fields:

- `题干`
- `题干图片`
- `答案`
- `解析`
- `解析图片`

The test uses two math teacher handouts already provided in the workspace context:

1. Senior math: `解三角形综合 - 教师版.pdf`
2. Junior geometry: `第2讲 倍长中线与截长补短（教师版）.pdf`

## Runtime Change

Updated runtime:

- `tools/teacher_pdf_visual_question_split_v02.py`

New output files per run:

- `teacher_visual_question_transcription_v0.1.json`
- `teacher_visual_question_transcription_v0.1.xlsx`
- `stem_images/*.png`
- `analysis_images/*.png`

## Final Test Runs

### Senior math

Run directory:

- `outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624`

Summary:

- questions: `47`
- transcription_source: `47 ocr_full_text`
- confidence: `46 medium`, `1 low`
- `stem_image` generated: `47 / 47`
- `analysis_image` generated: `35 / 47`
- `answer_text` extracted: `29 / 47`
- `analysis_text` extracted: `35 / 47`

### Junior geometry

Run directory:

- `outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624`

Summary:

- questions: `34`
- transcription_source: `29 ocr_full_text`, `5 pdf_text_layer`
- confidence: `26 medium`, `2 high`, `6 low`
- `stem_image` generated: `34 / 34`
- `analysis_image` generated: `29 / 34`
- `answer_text` extracted: `16 / 34`
- `analysis_text` extracted: `29 / 34`

## Visual Check

Representative visual checks were reviewed directly from output images:

- Senior math `tq_003`
  - `stem_image` preserves question text and options correctly enough for visual ownership review.
  - `analysis_image` preserves the derivation block and formulas in the right ownership region.
- Junior geometry `tq_003`
  - `stem_image` preserves theorem statement plus all three geometry figures.
  - `analysis_image` preserves the proof text and continuation across the next page.

## What Works Now

1. The visual splitter can now emit business-shaped candidate fields instead of only one rough preview string.
2. `题干图片` and `解析图片` are now materialized as separate review assets.
3. Image and diagram ownership is strong enough to start a serious test set immediately.
4. Proof-style geometry questions benefit more from this layer than formula-dense senior-math calculation questions.

## What Is Still Weak

1. Formula transcription still degrades heavily in OCR-heavy questions.
2. Fractions, powers, radicals, and angle symbols are often flattened or distorted.
3. Answer extraction is still incomplete when the source layout does not expose a clean `答案` marker.
4. Some senior-math outputs still rely on OCR-only text even though the visual cut is correct.

## Bottom-Line Judgment

This first transcription layer is already useful for:

- building a visual ownership test set
- exporting candidate `题干 / 答案 / 解析`
- producing teacher-reviewable assets fast

It is not yet strong enough to claim:

- exact formula transcription
- production-grade math text landing without review

## Recommended Next Step

Use this output as the first evaluation substrate:

1. score `题干图片/解析图片` ownership now
2. sample formula-heavy questions for manual gold transcription
3. measure formula error types separately from visual ownership

That keeps the test set honest: visual success and formula success should not be mixed into one number yet.
