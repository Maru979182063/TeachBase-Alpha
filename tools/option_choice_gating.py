from __future__ import annotations

import re


CHOICE_MARKER_PATTERNS = (
    re.compile(r"(?:^|\s)([A-D])\.", re.MULTILINE),
    re.compile(r"(?:^|\s)([A-D])、", re.MULTILINE),
    re.compile(r"[（(]([A-D])[）)]", re.MULTILINE),
)

CHOICE_CUE_RE = re.compile(
    r"(?:下列|正确的是|不正确的是|错误的是|图象中|选项|符合题意|说法正确|说法错误|选择题)",
    re.UNICODE,
)

NON_CHOICE_CUE_RE = re.compile(
    r"(?:填空题|解答题|证明题|计算题|求值|求证|作图题|阅读理解|实验探究)",
    re.UNICODE,
)


def _extract_choice_markers(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in CHOICE_MARKER_PATTERNS:
        hits.extend(pattern.findall(text or ""))
    seen: set[str] = set()
    ordered: list[str] = []
    for marker in hits:
        value = str(marker or "").strip().upper()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def evaluate_choice_gating(
    *,
    question_uid: str,
    option_anchor_mode: str = "auto",
    question_type: str = "",
    stem_text: str = "",
    raw_ocr_text: str = "",
    question_image_path: str = "",
    stem_image_path: str = "",
) -> dict:
    mode = str(option_anchor_mode or "auto").strip().lower()
    if mode not in {"auto", "always", "off"}:
        mode = "auto"

    question_type_value = str(question_type or "").strip().lower()
    combined_text = "\n".join(part for part in (stem_text, raw_ocr_text) if str(part or "").strip())
    choice_markers = _extract_choice_markers(combined_text)
    text_regex_hit = len(choice_markers) >= 2
    question_type_hit = question_type_value in {"single_choice", "multiple_choice", "choice"}
    visual_marker_hit = bool(stem_image_path or question_image_path)
    choice_cue_hit = bool(CHOICE_CUE_RE.search(combined_text or ""))
    non_choice_hit = bool(NON_CHOICE_CUE_RE.search(combined_text or ""))

    should_run = False
    reason = "not_choice_like"
    confidence = 0.88
    review_flags: list[str] = []

    if mode == "off":
        should_run = False
        reason = "mode_off"
        confidence = 1.0
    elif mode == "always":
        should_run = True
        reason = "mode_always"
        confidence = 1.0
    else:
        if question_type_hit:
            should_run = True
            reason = "question_type_choice"
            confidence = 0.96
        elif text_regex_hit:
            should_run = True
            reason = "choice_markers_detected"
            confidence = 0.91
        elif choice_cue_hit and visual_marker_hit and not non_choice_hit:
            should_run = True
            reason = "choice_cue_plus_visual"
            confidence = 0.78
        elif non_choice_hit:
            should_run = False
            reason = "non_choice_cue_detected"
            confidence = 0.9
        else:
            should_run = False
            reason = "insufficient_signals"
            confidence = 0.72

    return {
        "mode": mode,
        "should_run_option_detection": should_run,
        "reason": reason,
        "confidence": confidence,
        "signals": {
            "question_uid": question_uid,
            "question_type": question_type_value or "",
            "choice_markers": choice_markers,
            "text_regex_hit": text_regex_hit,
            "visual_marker_hit": visual_marker_hit,
            "choice_cue_hit": choice_cue_hit,
            "non_choice_cue_hit": non_choice_hit,
        },
        "review_flags": review_flags,
    }
