from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import pymupdf as fitz


@dataclass
class PreflightResultV03:
    doc_key: str
    path: str
    exists: bool
    page_count: int = 0
    text_chars_sample: int = 0
    classification: str = "missing"
    reason: str = ""


def classify_pdf_v03(doc_key: str, pdf_path: str, sample_pages: int = 5) -> PreflightResultV03:
    path = Path(pdf_path)
    if not path.exists():
        return PreflightResultV03(doc_key=doc_key, path=pdf_path, exists=False, reason="file_missing")
    doc = fitz.open(pdf_path)
    text_chars = 0
    for idx in range(min(sample_pages, doc.page_count)):
        text_chars += len((doc[idx].get_text("text") or "").strip())
    lowered = str(path).lower()
    if doc_key == "english" or "英语" in str(path) or "词法" in str(path):
        classification = "image_like_pdf" if text_chars < 3000 else "mixed_pdf"
        if classification == "mixed_pdf":
            # English handouts often have visually reliable text but unstable structure. Never mark as good_text_pdf.
            reason = "english_profile_forced_not_good_text_pdf"
        else:
            reason = "low_text_or_english_profile"
    elif text_chars == 0:
        classification = "image_pdf"
        reason = "no_text_layer_sample"
    elif text_chars < 600:
        classification = "mixed_pdf"
        reason = "sparse_text_layer"
    else:
        classification = "good_text_pdf"
        reason = "usable_text_layer_sample"
    return PreflightResultV03(
        doc_key=doc_key,
        path=pdf_path,
        exists=True,
        page_count=doc.page_count,
        text_chars_sample=text_chars,
        classification=classification,
        reason=reason,
    )


def write_preflight_report(path: Path, results: list[PreflightResultV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "preflight_report_v0.3", "documents": [asdict(r) for r in results]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
