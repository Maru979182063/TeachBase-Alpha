# 用途：
# - 运行双通道英语教师版 PDF 抽取器，区分例题和问题。
# - OCR 清洗、范围查找和裁图调度有意集中在这里。

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR


SCALE = 1.45
SIDE_MARGIN = 72
TOP_SAFE = 88
BOTTOM_SAFE = 72


@dataclass
class OcrLine:
    page: int
    x0: int
    y0: int
    x1: int
    y1: int
    text: str
    score: float


@dataclass
class RangeBlock:
    block_id: str
    kind: str
    label: str
    start_page: int
    start_y: int
    end_page: int
    end_y: int
    crop_path: str = ""
    transcript_path: str = ""
    text_preview: str = ""


def norm(text: str) -> str:
    text = str(text or "")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【 ", "【").replace(" 】", "】")
    return re.sub(r"\s+", " ", text).strip()


def load_font(size: int):
    for path in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_pdf(pdf_path: Path, pages_dir: Path) -> list[Path]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    rendered: list[Path] = []
    for page_no, page in enumerate(doc, start=1):
        out_path = pages_dir / f"page_{page_no:03d}.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), alpha=False)
        pix.save(str(out_path))
        rendered.append(out_path)
    return rendered


def content_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    arr = np.asarray(image.convert("RGB"))
    nonwhite = np.any(arr < 244, axis=2)
    ys, xs = np.where(nonwhite)
    if len(xs) == 0 or len(ys) == 0:
        return SIDE_MARGIN, TOP_SAFE, image.width - SIDE_MARGIN, image.height - BOTTOM_SAFE
    x0 = max(24, int(xs.min()) - 24)
    y0 = max(TOP_SAFE, int(ys.min()) - 20)
    x1 = min(image.width - 24, int(xs.max()) + 24)
    y1 = min(image.height - 24, int(ys.max()) + 24)
    return x0, y0, x1, y1


def ocr_pages(page_paths: list[Path]) -> dict[int, list[OcrLine]]:
    engine = RapidOCR()
    pages: dict[int, list[OcrLine]] = {}
    for index, page_path in enumerate(page_paths, start=1):
        result, _ = engine(str(page_path))
        lines: list[OcrLine] = []
        for item in result or []:
            if len(item) < 3:
                continue
            box, text, score = item
            clean = norm(text)
            if not clean or score < 0.45:
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            lines.append(
                OcrLine(
                    page=index,
                    x0=int(min(xs)),
                    y0=int(min(ys)),
                    x1=int(max(xs)),
                    y1=int(max(ys)),
                    text=clean,
                    score=float(score),
                )
            )
        pages[index] = sorted(lines, key=lambda line: (line.y0, line.x0))
    return pages


def find_first(lines: list[OcrLine], predicate) -> OcrLine | None:
    for line in lines:
        if predicate(line):
            return line
    return None


def contains_any(text: str, keys: list[str]) -> bool:
    return any(key in text for key in keys)


def detect_example_starts(ocr_by_page: dict[int, list[OcrLine]]) -> list[OcrLine]:
    starts: list[OcrLine] = []
    for page, lines in ocr_by_page.items():
        for line in lines:
            if "【例" in line.text or re.match(r"^\[?例\s*\d+\]?$", line.text):
                starts.append(line)
    starts.sort(key=lambda item: (item.page, item.y0))
    deduped: list[OcrLine] = []
    for line in starts:
        if deduped and line.page == deduped[-1].page and abs(line.y0 - deduped[-1].y0) < 28:
            continue
        deduped.append(line)
    return deduped


def detect_question_starts(ocr_by_page: dict[int, list[OcrLine]], example_blocks: list[RangeBlock]) -> list[OcrLine]:
    starts: list[OcrLine] = []
    for block in example_blocks:
        for page in range(block.start_page, block.end_page + 1):
            for line in ocr_by_page.get(page, []):
                if not (line.text[:2].isdigit() or (line.text[:1].isdigit() and "." in line.text[:4])):
                    continue
                if not re.match(r"^\d{1,2}\.", line.text):
                    continue
                if page == block.start_page and line.y0 < block.start_y:
                    continue
                if page == block.end_page and line.y0 > block.end_y:
                    continue
                if line.x0 > 220:
                    continue
                starts.append(line)
    starts.sort(key=lambda item: (item.page, item.y0))
    deduped: list[OcrLine] = []
    for line in starts:
        if deduped and line.page == deduped[-1].page and abs(line.y0 - deduped[-1].y0) < 24:
            continue
        deduped.append(line)
    return deduped


def crop_range(block: RangeBlock, page_paths: list[Path], out_path: Path) -> Path:
    images = [Image.open(path).convert("RGB") for path in page_paths]
    page_slices: list[Image.Image] = []
    for page in range(block.start_page, block.end_page + 1):
        img = images[page - 1]
        x0, base_y0, x1, base_y1 = content_bounds(img)
        y0 = block.start_y if page == block.start_page else base_y0
        y1 = block.end_y if page == block.end_page else base_y1
        y0 = max(base_y0, y0 - 12)
        y1 = min(base_y1, y1 + 12)
        if y1 <= y0 + 24:
            continue
        page_slices.append(img.crop((x0, y0, x1, y1)))
    if not page_slices:
        raise RuntimeError(f"Empty crop for {block.block_id}")
    width = max(piece.width for piece in page_slices)
    total_height = sum(piece.height for piece in page_slices) + max(0, len(page_slices) - 1) * 18
    canvas = Image.new("RGB", (width, total_height), "white")
    cursor = 0
    for idx, piece in enumerate(page_slices):
        canvas.paste(piece, (0, cursor))
        cursor += piece.height
        if idx < len(page_slices) - 1:
            draw = ImageDraw.Draw(canvas)
            draw.line((0, cursor + 8, width, cursor + 8), fill=(210, 210, 210), width=2)
            cursor += 18
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def range_text_from_page_ocr(block: RangeBlock, ocr_by_page: dict[int, list[OcrLine]]) -> str:
    rows: list[str] = []
    for page in range(block.start_page, block.end_page + 1):
        page_rows: list[OcrLine] = []
        for line in ocr_by_page.get(page, []):
            if page == block.start_page and line.y1 < block.start_y:
                continue
            if page == block.end_page and line.y0 > block.end_y:
                continue
            page_rows.append(line)
        page_rows.sort(key=lambda item: (item.y0, item.x0))
        for line in page_rows:
            rows.append(line.text)
    return "\n".join(rows)


def preview(text: str, limit: int = 220) -> str:
    return norm(text).replace("\n", " ")[:limit]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def contact_sheet(blocks: list[RangeBlock], title: str, out_path: Path) -> None:
    font = load_font(18)
    thumbs: list[Image.Image] = []
    for block in blocks:
        if not block.crop_path or not Path(block.crop_path).exists():
            continue
        img = Image.open(block.crop_path).convert("RGB")
        img.thumbnail((360, 260))
        card = Image.new("RGB", (400, 340), "white")
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle((4, 4, 396, 336), radius=10, outline=(210, 220, 235), width=2)
        draw.text((14, 12), block.label[:34], fill=(20, 28, 40), font=font)
        draw.text((14, 38), f"{block.kind} | P{block.start_page}-{block.end_page}", fill=(92, 110, 130), font=font)
        card.paste(img, ((400 - img.width) // 2, 70))
        thumbs.append(card)
    if not thumbs:
        return
    cols = 3
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * 400, rows * 340 + 60), (246, 248, 252))
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 16), title, fill=(18, 26, 38), font=load_font(26))
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * 400, (idx // cols) * 340 + 60))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def html_gallery(components: list[RangeBlock], questions: list[RangeBlock], out_path: Path) -> None:
    def card(block: RangeBlock) -> str:
        rel = Path(block.crop_path).name
        txt = Path(block.transcript_path).name if block.transcript_path else ""
        return f"""
        <article class="card">
          <div class="meta">
            <strong>{block.label}</strong>
            <span>{block.kind} | P{block.start_page}-{block.end_page}</span>
          </div>
          <img src="./{Path(block.crop_path).parent.name}/{rel}" alt="{block.label}">
          <p>{block.text_preview}</p>
          <a href="./{Path(block.transcript_path).parent.name}/{txt}" target="_blank">查看转录</a>
        </article>
        """

    component_cards = "\n".join(card(block) for block in components)
    question_cards = "\n".join(card(block) for block in questions)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>英语教师版讲义拆分预览</title>
  <style>
    body {{ font-family: "Microsoft YaHei", Arial, sans-serif; margin: 0; background: #f4f7fb; color: #142032; }}
    header {{ padding: 28px 32px; background: white; box-shadow: 0 8px 24px rgba(32, 56, 90, 0.08); position: sticky; top: 0; z-index: 2; }}
    h1 {{ margin: 0; font-size: 30px; }}
    .sub {{ margin-top: 8px; color: #5f6f84; }}
    main {{ padding: 24px 28px 60px; }}
    h2 {{ margin: 28px 0 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; }}
    .card {{ background: white; border: 1px solid #dce6f3; border-radius: 14px; padding: 14px; box-shadow: 0 10px 24px rgba(33, 52, 82, 0.06); }}
    .card img {{ width: 100%; border-radius: 10px; border: 1px solid #e6edf7; background: #fff; }}
    .meta {{ display: flex; gap: 6px; flex-direction: column; margin-bottom: 10px; }}
    .meta span {{ color: #66768b; font-size: 13px; }}
    .card p {{ color: #334158; font-size: 14px; line-height: 1.6; min-height: 64px; }}
    a {{ color: #2257f3; text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <header>
    <h1>阅读理解体裁训练之记叙文（教师版）</h1>
    <div class="sub">图片化组件保留 + 单题转录双轨输出</div>
  </header>
  <main>
    <h2>常规组件</h2>
    <section class="grid">{component_cards}</section>
    <h2>单题切片</h2>
    <section class="grid">{question_cards}</section>
  </main>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def find_anchor_y(line: OcrLine | None, fallback: int) -> int:
    return fallback if line is None else max(TOP_SAFE, line.y0 - 12)


def build_components(page_paths: list[Path], ocr_by_page: dict[int, list[OcrLine]], example_starts: list[OcrLine]) -> list[RangeBlock]:
    p1 = ocr_by_page.get(1, [])
    p4 = ocr_by_page.get(4, [])
    course = find_first(p1, lambda line: "课程目标" in line.text)
    knowledge = find_first(p1, lambda line: "知识梳理" in line.text)
    reading = find_first(p4, lambda line: "阅读解题思路" in line.text)
    example_lecture = find_first(p4, lambda line: "例题讲解" in line.text)
    page4_img = Image.open(page_paths[3]).convert("RGB")
    _, p4y0, _, p4y1 = content_bounds(page4_img)
    blocks = [
        RangeBlock(
            block_id="comp_001",
            kind="regular_component",
            label="课程目标",
            start_page=1,
            start_y=find_anchor_y(course, 120),
            end_page=1,
            end_y=max(find_anchor_y(knowledge, 560) - 18, 320),
        ),
        RangeBlock(
            block_id="comp_002",
            kind="regular_component",
            label="知识梳理",
            start_page=1,
            start_y=find_anchor_y(knowledge, 540),
            end_page=4,
            end_y=max(find_anchor_y(reading, 300) - 20, p4y0 + 120),
        ),
        RangeBlock(
            block_id="comp_003",
            kind="regular_component",
            label="阅读解题思路",
            start_page=4,
            start_y=find_anchor_y(reading, p4y0 + 40),
            end_page=4,
            end_y=max(find_anchor_y(example_lecture, p4y1 - 500) - 20, p4y0 + 180),
        ),
    ]
    for idx, start in enumerate(example_starts, start=1):
        if idx < len(example_starts):
            next_start = example_starts[idx]
            end_page = next_start.page
            end_y = next_start.y0 - 24
        else:
            end_page = len(page_paths)
            tail_img = Image.open(page_paths[-1]).convert("RGB")
            _, _, _, tail_y1 = content_bounds(tail_img)
            end_y = tail_y1
        blocks.append(
            RangeBlock(
                block_id=f"example_{idx:03d}",
                kind="example_group",
                label=f"例题 {idx}",
                start_page=start.page,
                start_y=max(TOP_SAFE, start.y0 - 18),
                end_page=end_page,
                end_y=end_y,
            )
        )
    return blocks


def build_question_blocks(ocr_by_page: dict[int, list[OcrLine]], example_blocks: list[RangeBlock], page_paths: list[Path]) -> list[RangeBlock]:
    q_starts = detect_question_starts(ocr_by_page, example_blocks)
    questions: list[RangeBlock] = []
    for idx, start in enumerate(q_starts, start=1):
        next_start = q_starts[idx] if idx < len(q_starts) else None
        parent = next(
            block for block in example_blocks
            if (block.start_page < start.page or (block.start_page == start.page and block.start_y <= start.y0))
            and (block.end_page > start.page or (block.end_page == start.page and block.end_y >= start.y0))
        )
        if next_start:
            end_page = next_start.page
            end_y = next_start.y0 - 18
        else:
            end_page = parent.end_page
            end_y = parent.end_y
        if end_page > parent.end_page or (end_page == parent.end_page and end_y > parent.end_y):
            end_page = parent.end_page
            end_y = parent.end_y
        number_match = re.match(r"^(\d{1,2})\.", start.text)
        q_no = number_match.group(1) if number_match else str(idx)
        questions.append(
            RangeBlock(
                block_id=f"q_{idx:03d}",
                kind="question_slice",
                label=f"{parent.label} - 题 {q_no}",
                start_page=start.page,
                start_y=max(TOP_SAFE, start.y0 - 18),
                end_page=end_page,
                end_y=end_y,
            )
        )
    return questions


def persist_block_set(
    blocks: list[RangeBlock],
    page_paths: list[Path],
    ocr_by_page: dict[int, list[OcrLine]],
    crop_dir: Path,
    text_dir: Path,
) -> None:
    for block in blocks:
        crop_path = crop_dir / f"{block.block_id}.png"
        crop_range(block, page_paths, crop_path)
        block.crop_path = str(crop_path)
        transcript = range_text_from_page_ocr(block, ocr_by_page)
        block.text_preview = preview(transcript)
        transcript_path = text_dir / f"{block.block_id}.md"
        write_text(transcript_path, f"# {block.label}\n\n{transcript}")
        block.transcript_path = str(transcript_path)


def write_manifest(
    source_pdf: Path,
    components: list[RangeBlock],
    questions: list[RangeBlock],
    out_dir: Path,
) -> None:
    manifest = {
        "source_pdf": str(source_pdf),
        "principle": "visual-first with OCR grounding: rendered page images define crops; OCR only helps locate component and question anchors",
        "components": [asdict(block) for block in components],
        "questions": [asdict(block) for block in questions],
    }
    (out_dir / "dual_extract_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 英语教师版讲义拆分报告",
        "",
        f"- 源文件：`{source_pdf}`",
        f"- 常规组件数：{len(components)}",
        f"- 单题切片数：{len(questions)}",
        "",
        "## 常规组件",
        "",
        "| 组件 | 页码 | 预览 |",
        "|---|---|---|",
    ]
    for block in components:
        lines.append(f"| {block.label} | P{block.start_page}-P{block.end_page} | {block.text_preview} |")
    lines.extend(["", "## 单题切片", "", "| 题块 | 页码 | 预览 |", "|---|---|---|"])
    for block in questions:
        lines.append(f"| {block.label} | P{block.start_page}-P{block.end_page} | {block.text_preview} |")
    (out_dir / "dual_extract_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    source_pdf = Path(os.environ.get("SOURCE_PDF_ASCII", r"C:\codex_tmp\english_narrative_teacher.pdf"))
    out_name = os.environ.get("OUT_NAME", "english_narrative_teacher_dual_v01")
    out_dir = Path.cwd() / "outputs" / "ingress_splitter_v0.1" / out_name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    pages_dir = out_dir / "pages"
    component_crop_dir = out_dir / "component_crops"
    component_text_dir = out_dir / "component_transcripts"
    question_crop_dir = out_dir / "question_crops"
    question_text_dir = out_dir / "question_transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    page_paths = render_pdf(source_pdf, pages_dir)
    ocr_by_page = ocr_pages(page_paths)
    example_starts = detect_example_starts(ocr_by_page)
    components = build_components(page_paths, ocr_by_page, example_starts)
    example_components = [block for block in components if block.kind == "example_group"]
    questions = build_question_blocks(ocr_by_page, example_components, page_paths)

    persist_block_set(components, page_paths, ocr_by_page, component_crop_dir, component_text_dir)
    persist_block_set(questions, page_paths, ocr_by_page, question_crop_dir, question_text_dir)

    contact_sheet(components, "常规组件与例题组预览", out_dir / "components_contact_sheet.jpg")
    contact_sheet(questions, "单题切片预览", out_dir / "questions_contact_sheet.jpg")
    write_manifest(source_pdf, components, questions, out_dir)
    html_gallery(components, questions, out_dir / "preview_gallery.html")

    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "page_count": len(page_paths),
                "example_count": len(example_components),
                "component_count": len(components),
                "question_count": len(questions),
                "gallery": str(out_dir / "preview_gallery.html"),
                "components_contact_sheet": str(out_dir / "components_contact_sheet.jpg"),
                "questions_contact_sheet": str(out_dir / "questions_contact_sheet.jpg"),
                "manifest": str(out_dir / "dual_extract_manifest.json"),
                "report": str(out_dir / "dual_extract_report.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
