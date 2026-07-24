from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import fitz
from PIL import Image


PROVIDER_LIMITS = {
    "doubao": {
        "master_dpi": 300,
        "max_vlm_pixels": 9_000_000,
        "detail": "high",
        "tile_when_exceed_limit": True,
    }
}


@dataclass
class PageManifestV03:
    doc_key: str
    page: int
    source_page: int
    width_px: int
    height_px: int
    target_dpi: int
    render_scale: float
    provider: str
    provider_detail: str
    max_vlm_pixels: int
    page_image_master: str
    page_image_vlm: str
    vlm_width_px: int
    vlm_height_px: int
    coordinate_space: str = "master_px"


def _save_vlm_image(master_path: Path, vlm_path: Path, max_pixels: int) -> tuple[int, int]:
    img = Image.open(master_path).convert("RGB")
    width, height = img.size
    if width * height <= max_pixels:
        img.save(vlm_path, quality=95)
        return width, height
    scale = math.sqrt(max_pixels / float(width * height))
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    img.resize(new_size, Image.Resampling.LANCZOS).save(vlm_path, quality=95)
    return new_size


def render_pdf_pages_v03(
    pdf_path: str,
    out_dir: Path,
    doc_key: str,
    pages: list[int] | None = None,
    provider: str = "doubao",
) -> list[PageManifestV03]:
    limits = PROVIDER_LIMITS.get(provider, PROVIDER_LIMITS["doubao"])
    target_dpi = int(limits["master_dpi"])
    render_scale = target_dpi / 72.0
    max_pixels = int(limits["max_vlm_pixels"])
    detail = str(limits["detail"])

    out_dir.mkdir(parents=True, exist_ok=True)
    master_dir = out_dir / doc_key / "master"
    vlm_dir = out_dir / doc_key / "vlm"
    master_dir.mkdir(parents=True, exist_ok=True)
    vlm_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    page_numbers = pages or list(range(1, doc.page_count + 1))
    manifests: list[PageManifestV03] = []
    for page_no in page_numbers:
        if page_no < 1 or page_no > doc.page_count:
            continue
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
        master_path = master_dir / f"p{page_no:03d}_master.png"
        vlm_path = vlm_dir / f"p{page_no:03d}_vlm.png"
        pix.save(str(master_path))
        vlm_w, vlm_h = _save_vlm_image(master_path, vlm_path, max_pixels)
        manifests.append(
            PageManifestV03(
                doc_key=doc_key,
                page=page_no,
                source_page=page_no,
                width_px=pix.width,
                height_px=pix.height,
                target_dpi=target_dpi,
                render_scale=render_scale,
                provider=provider,
                provider_detail=detail,
                max_vlm_pixels=max_pixels,
                page_image_master=str(master_path),
                page_image_vlm=str(vlm_path),
                vlm_width_px=vlm_w,
                vlm_height_px=vlm_h,
            )
        )
    return manifests


def write_page_manifests(path: Path, manifests: list[PageManifestV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "page_manifest_v0.3", "pages": [asdict(m) for m in manifests]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
