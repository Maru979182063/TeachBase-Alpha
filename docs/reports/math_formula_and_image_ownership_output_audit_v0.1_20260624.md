# Math Formula And Image Ownership Output Audit v0.1

Date: 2026-06-24

## Question

Do the current visual-split outputs already contain question-level results, and can they support evaluation of:

1. formula transcription quality
2. image and diagram ownership

## Short Answer

Yes, the current outputs already contain question-level results.

But they currently support the two evaluation targets differently:

- image and diagram ownership: can already be evaluated
- formula transcription: can only be evaluated qualitatively or semi-manually, not as a strict structured pass/fail output yet

## Evidence From Existing Runs

### Senior math

Run:

- `outputs/ingress_splitter_v0.1/codex_profile_senior_math_v03_20260623`

Observed:

- `question_count = 47`
- `review_status`: `46 VISUAL_REVIEWED_V02`, `1 NEEDS_MANUAL_REVIEW`
- `text_preview_source`: `47 ocr_fallback`
- `multi_page questions = 28 / 47`

### Junior geometry

Run:

- `outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_v03_20260623`

Observed:

- `question_count = 34`
- `review_status`: `28 VISUAL_REVIEWED_V02`, `6 NEEDS_MANUAL_REVIEW`
- `text_preview_source`: `27 ocr_fallback`, `7 pdf_text_layer`
- `multi_page questions = 24 / 34`

## What The Current Output Already Has

Each question record already has:

- `question_id`
- `checkpoint`
- `component_kind`
- `component_label`
- `local_number`
- `visual_pages`
- `fragments`
- `crop_path`
- `review_status`
- `text_preview`
- `text_preview_pdf`
- `text_preview_ocr`
- `text_preview_source`

This means the system already outputs:

1. a question crop image
2. the page ownership chain
3. the crop bounding fragments across pages
4. a rough text preview

## What Counts As "Question-Level Result" Right Now

The current question-level result is:

- visual question crop as the primary result
- JSON or XLSX metadata as the indexing result
- rough OCR or text-layer preview as an auxiliary result

It is not yet:

- structured standard answer extraction
- structured analysis extraction
- strict formula LaTeX transcription

## Can We Evaluate Image Ownership Now

Yes.

Reason:

- `crop_path` gives the final owned question image
- `fragments` record which page regions belong to the same question
- cross-page questions are already stitched
- contact sheets allow fast human review

This is enough to test whether:

- a geometry figure stayed with the right question
- a formula block stayed with the right question
- a continuation page was attached to the right question
- the next question or next section was swallowed incorrectly

## Can We Evaluate Formula Transcription Now

Partially, but not as a reliable structured benchmark yet.

Reason:

- the current `text_preview` is mostly `ocr_fallback`
- math symbols are frequently degraded
- there is no canonical `latex_transcription` field
- there is no formula-level span alignment

### Example of the current limitation

In senior math run `tq_003`, the visual crop clearly shows:

- `cos C = 2/3`
- `AC = 4`
- `BC = 3`
- answer options `A-D`

But the current text preview is only:

- `3．（2020-新课标ⅢI）在△ABC中，cosC=2 AC=4，BC=3，则tanB=（ A.√5 B.2√5 C.4√5 D.8√`

So the structure is visible, but the fraction and expression fidelity are not preserved well enough for exact formula scoring.

## Bottom-Line Capability Judgment

### Already usable for testing

- question slicing success
- image or diagram ownership
- cross-page ownership
- section ownership
- manual-review rate

### Not yet fully usable for hard scoring

- exact formula transcription
- exact mathematical symbol fidelity
- exact answer and analysis extraction as structured fields

## Recommendation For The 3-Day Test Window

Use the current system in two separate test tracks:

### Track A: visual ownership benchmark

Use existing outputs directly.

Judge:

- whether the right diagram belongs to the right question
- whether formulas remain inside the right question crop
- whether cross-page continuation is correct
- whether section boundaries are respected

### Track B: formula transcription benchmark

Do not use the current `text_preview` as final quality output.

Instead:

- sample a smaller formula-heavy subset
- compare crop image against manual gold transcription
- label error types such as missing fraction, root sign loss, superscript loss, merged options, diagram text drop

## Product Gap To Close

To support strict formula evaluation later, the runtime still needs:

1. a dedicated `transcription_raw` field
2. a dedicated `transcription_latex` or normalized math field
3. formula-region span metadata
4. figure ownership confidence
5. explicit `answer_text` and `analysis_text` extraction if that is part of acceptance

## Conclusion

The current outputs already have real question-level results.

They are good enough to start a serious image-ownership test set now.

They are not yet good enough to claim exact formula-transcription quality from the existing text fields alone.
