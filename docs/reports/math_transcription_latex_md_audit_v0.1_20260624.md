# Math Transcription LaTeX+Markdown Audit v0.1

Date: 2026-06-24

## Audit Standard

This audit does **not** judge whether the pipeline "produced some text".

It judges whether the current outputs are acceptable as:

- standard Markdown body text
- standard LaTeX math expressions
- database-ready `题干 / 答案 / 解析`

## Verdict

The current transcription outputs are **not acceptable** under a `LaTeX + Markdown` standard.

The problem is not only OCR quality.

The problem is a combination of:

1. source extraction fragmentation
2. 2D formula flattening
3. line-level marker splitting
4. no math normalization layer

## Representative Failures

### 1. Senior math `tq_002`

Visual truth:

- [tq_002_考点1：正余弦定理及其应用_例题讲解_Q2.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/question_crops/tq_002_考点1：正余弦定理及其应用_例题讲解_Q2.png)

Observed issue:

- The image clearly contains `【答案】3/4`.
- Exported `stem_text` still contains `【答案】`.
- Exported `answer_text` is empty.

Interpretation:

- This is not a mere OCR typo.
- The field boundary logic failed, so `题干/答案` separation is structurally wrong.

### 2. Senior math `tq_003`

Visual truth:

- [tq_003_stem.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/stem_images/tq_003_stem.png)

Observed issue:

- The visual question shows `cos C = 2/3`.
- Exported text degrades into `cosC=2 AC=4，BC=3`.

Interpretation:

- This is fatal for LaTeX-grade transcription.
- The fraction structure is gone before any Markdown formatting could help.

### 3. Junior geometry `tq_002`

Visual truth:

- [tq_002_考点1_倍长中线与中位线_强化训练_Q变式1-1.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624/question_crops/tq_002_考点1_倍长中线与中位线_强化训练_Q变式1-1.png)

Observed issue:

- Options are laid out clearly left-to-right in the visual question.
- Exported text becomes `A.1<AC<11 D.1<AC<4 B.1<AC<8 C.2<AC<8`.

Interpretation:

- Multi-column option structure is being flattened.
- Markdown formatting cannot recover the original logical order once this happens.

### 4. Junior geometry raw text layer

Observed issue:

- The PDF text layer contains many private-use or symbol-font glyphs such as `\uf051`, `\uf05c`, `\uf0ec`, `\uf0ef`.

Interpretation:

- Even before OCR, the embedded text layer is not directly database-safe.
- A plain "prefer PDF text layer" rule is insufficient.

## Root Causes In Runtime

### A. OCR line merge destroys 2D math layout

Runtime:

- [teacher_pdf_visual_question_split_v02.py](/C:/Users/EDY/Documents/教研基建/tools/teacher_pdf_visual_question_split_v02.py:318)

Issue:

- `merge_ocr_lines()` merges text boxes into pseudo-lines using only row and x-gap heuristics.
- Fractions, stacked formulas, and option columns are forced into linear text.

Why it matters:

- LaTeX needs mathematical structure.
- This step removes the structure first and only then asks later code to serialize it.

### B. Source chooser systematically prefers OCR on senior math

Runtime:

- [teacher_pdf_visual_question_split_v02.py](/C:/Users/EDY/Documents/教研基建/tools/teacher_pdf_visual_question_split_v02.py:839)
- [teacher_pdf_visual_question_split_v02.py](/C:/Users/EDY/Documents/教研基建/tools/teacher_pdf_visual_question_split_v02.py:1005)

Issue:

- The score biases toward whichever text looks longer and less noisy.
- In senior math this causes `47/47` questions to choose `ocr_full_text`.

Why it matters:

- Once OCR wins globally, all exact formula symbols depend on OCR survival.

### C. Answer and analysis splitting still assumes clean marker rows

Runtime:

- [teacher_pdf_visual_question_split_v02.py](/C:/Users/EDY/Documents/教研基建/tools/teacher_pdf_visual_question_split_v02.py:1015)
- [teacher_pdf_visual_question_split_v02.py](/C:/Users/EDY/Documents/教研基建/tools/teacher_pdf_visual_question_split_v02.py:1115)

Issue:

- The splitter looks for answer and analysis markers at line level.
- If a marker shares a row with nearby content, the field boundary becomes unstable.

Why it matters:

- A database field split must be semantically stable, not just visually approximate.

### D. The data model is still plain-string only

Runtime:

- [teacher_pdf_visual_question_split_v02.py](/C:/Users/EDY/Documents/教研基建/tools/teacher_pdf_visual_question_split_v02.py:109)

Issue:

- Output fields are `stem_text`, `answer_text`, `analysis_text`, but there is no:
  - math span representation
  - formula block representation
  - table/option structure representation
  - image-anchor references inside text

Why it matters:

- Standard Markdown plus LaTeX needs more than one flattened string.

## What This Means For The Requirement

The user requirement can and should be tightened to:

- output body text in Markdown
- output math in standard LaTeX
- keep diagrams and geometry figures as referenced assets

But the current runtime is **not yet capable** of meeting that requirement simply by changing output formatting.

Formatting is not the main blocker.

Extraction quality and structure preservation are the blockers.

## Practical Bottom Line

### What is already valid

- visual question slicing
- image ownership
- stem-image and analysis-image review assets

### What is not valid yet

- exact formula transcription
- standard LaTeX emission
- database-ready Markdown answer and analysis

## Recommendation

Do not frame the next task as:

- "convert current text to markdown and latex"

Frame it as:

1. preserve formula structure before flattening
2. split `题干 / 答案 / 解析` at block level, not only line level
3. emit Markdown and LaTeX only after math-aware reconstruction exists

Otherwise the result will only be "pretty formatting around broken content".
