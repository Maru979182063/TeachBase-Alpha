from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import time
import zipfile
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


DEFAULT_SCALE = 1.35
HEADER_FILTERS = ("领世1对1英语",)
QUESTION_RE = re.compile(r"^\d{1,2}\.\s*")
EXAMPLE_RE = re.compile(r"例\s*\d+")
COMPONENT_MARKERS = [
    ("course_goals", "课程目标"),
    ("knowledge", "知识梳理"),
    ("reading_method", "阅读解题思路"),
    ("example_component", "例题讲解"),
    ("mini_test", "要点小测"),
    ("after_class", "课后落实"),
]


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
class Block:
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
    return re.sub(r"\s+", " ", text).strip()


def font(size: int):
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


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def stage_state(state_path: Path, **updates) -> dict:
    state = load_json(state_path, default={}) or {}
    state.update(updates)
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(state_path, state)
    return state


def render_pdf(pdf_path: Path, pages_dir: Path, scale: float) -> list[Path]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    if list(pages_dir.glob("page_*.png")):
        return sorted(pages_dir.glob("page_*.png"))
    doc = fitz.open(str(pdf_path))
    rendered: list[Path] = []
    for page_no, page in enumerate(doc, start=1):
        out = pages_dir / f"page_{page_no:03d}.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        pix.save(str(out))
        rendered.append(out)
        print(f"[render] page {page_no}/{len(doc)}")
    return rendered


def content_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    arr = np.asarray(image.convert("RGB"))
    nonwhite = np.any(arr < 244, axis=2)
    ys, xs = np.where(nonwhite)
    if len(xs) == 0 or len(ys) == 0:
        return 60, 90, image.width - 60, image.height - 70
    return (
        max(24, int(xs.min()) - 18),
        max(82, int(ys.min()) - 18),
        min(image.width - 24, int(xs.max()) + 18),
        min(image.height - 24, int(ys.max()) + 18),
    )


def line_from_ocr(page: int, item) -> OcrLine | None:
    if len(item) < 3:
        return None
    box, text, score = item
    clean = norm(text)
    if not clean or float(score) < 0.45:
        return None
    xs = [pt[0] for pt in box]
    ys = [pt[1] for pt in box]
    return OcrLine(
        page=page,
        x0=int(min(xs)),
        y0=int(min(ys)),
        x1=int(max(xs)),
        y1=int(max(ys)),
        text=clean,
        score=float(score),
    )


def ocr_pages(page_paths: list[Path], ocr_dir: Path, state_path: Path) -> dict[int, list[OcrLine]]:
    ocr_dir.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR()
    pages: dict[int, list[OcrLine]] = {}
    total = len(page_paths)
    for idx, page_path in enumerate(page_paths, start=1):
        cache_path = ocr_dir / f"page_{idx:03d}.json"
        if cache_path.exists():
            raw = load_json(cache_path, default=[]) or []
            pages[idx] = [OcrLine(**item) for item in raw]
            print(f"[ocr] page {idx}/{total} cache")
            continue
        t0 = time.time()
        result, _ = engine(str(page_path))
        lines = [line for item in (result or []) if (line := line_from_ocr(idx, item))]
        lines.sort(key=lambda item: (item.y0, item.x0))
        write_json(cache_path, [asdict(line) for line in lines])
        pages[idx] = lines
        dt = round(time.time() - t0, 2)
        stage_state(state_path, current_stage="ocr", current_page=idx, page_count=total)
        print(f"[ocr] page {idx}/{total} lines={len(lines)} time={dt}s")
    return pages


def first_line(lines: list[OcrLine], predicate) -> OcrLine | None:
    for line in lines:
        if predicate(line):
            return line
    return None


def detect_example_starts(ocr_pages_map: dict[int, list[OcrLine]]) -> list[OcrLine]:
    hits: list[OcrLine] = []
    for page, lines in ocr_pages_map.items():
        for line in lines:
            if "例" not in line.text:
                continue
            if EXAMPLE_RE.search(line.text):
                hits.append(line)
    hits.sort(key=lambda item: (item.page, item.y0))
    deduped: list[OcrLine] = []
    for line in hits:
        if deduped and line.page == deduped[-1].page and abs(line.y0 - deduped[-1].y0) < 26:
            continue
        deduped.append(line)
    return deduped


def detect_component_anchors(ocr_pages_map: dict[int, list[OcrLine]]) -> list[tuple[str, str, OcrLine]]:
    anchors: list[tuple[str, str, OcrLine]] = []
    for page, lines in ocr_pages_map.items():
        for line in lines:
            for kind, label in COMPONENT_MARKERS:
                if label in line.text:
                    anchors.append((kind, label, line))
                    break
    anchors.sort(key=lambda item: (item[2].page, item[2].y0))
    deduped: list[tuple[str, str, OcrLine]] = []
    for item in anchors:
        if deduped:
            pk, pl, prev = deduped[-1]
            if item[0] == pk and item[2].page == prev.page and abs(item[2].y0 - prev.y0) < 28:
                continue
        deduped.append(item)
    return deduped


def build_component_blocks(page_paths: list[Path], ocr_pages_map: dict[int, list[OcrLine]]) -> list[Block]:
    anchors = detect_component_anchors(ocr_pages_map)
    blocks: list[Block] = []
    total_pages = len(page_paths)
    for idx, (kind, label, line) in enumerate(anchors, start=1):
        if idx < len(anchors):
            next_line = anchors[idx][2]
            end_page = next_line.page
            end_y = next_line.y0 - 18
        else:
            last_img = Image.open(page_paths[-1]).convert("RGB")
            _, _, _, y1 = content_bounds(last_img)
            end_page = total_pages
            end_y = y1
        blocks.append(
            Block(
                block_id=f"comp_{idx:03d}",
                kind=kind,
                label=label,
                start_page=line.page,
                start_y=max(80, line.y0 - 12),
                end_page=end_page,
                end_y=end_y,
            )
        )
    return blocks


def build_example_blocks(page_paths: list[Path], ocr_pages_map: dict[int, list[OcrLine]], component_blocks: list[Block]) -> list[Block]:
    example_component = next((block for block in component_blocks if block.kind == "example_component"), None)
    if example_component is None:
        return []
    starts = []
    for line in detect_example_starts(ocr_pages_map):
        if line.page < example_component.start_page or line.page > example_component.end_page:
            continue
        if line.page == example_component.start_page and line.y0 < example_component.start_y:
            continue
        if line.page == example_component.end_page and line.y0 > example_component.end_y:
            continue
        starts.append(line)
    blocks: list[Block] = []
    for idx, start in enumerate(starts, start=1):
        if idx < len(starts):
            next_start = starts[idx]
            end_page = next_start.page
            end_y = next_start.y0 - 18
        else:
            end_page = example_component.end_page
            end_y = example_component.end_y
        blocks.append(
            Block(
                block_id=f"example_{idx:03d}",
                kind="example_group",
                label=f"例题 {idx}",
                start_page=start.page,
                start_y=max(80, start.y0 - 18),
                end_page=end_page,
                end_y=end_y,
            )
        )
    return blocks


def has_option_signature(lines: list[OcrLine], anchor: OcrLine) -> bool:
    near = [
        line.text
        for line in lines
        if line.page == anchor.page and line.y0 >= anchor.y0 and line.y0 <= anchor.y0 + 240
    ]
    has_a = any(re.match(r"^A\.", text) for text in near)
    has_b = any(re.match(r"^B\.", text) for text in near)
    return has_a and has_b


def detect_question_starts(ocr_pages_map: dict[int, list[OcrLine]], question_regions: list[Block]) -> list[tuple[Block, OcrLine]]:
    starts: list[tuple[Block, OcrLine]] = []
    for block in question_regions:
        for page in range(block.start_page, block.end_page + 1):
            lines = ocr_pages_map.get(page, [])
            for line in ocr_pages_map.get(page, []):
                if page == block.start_page and line.y0 < block.start_y:
                    continue
                if page == block.end_page and line.y0 > block.end_y:
                    continue
                if line.x0 > 220:
                    continue
                if QUESTION_RE.match(line.text) and ("?" in line.text or has_option_signature(lines, line)):
                    starts.append((block, line))
    starts.sort(key=lambda item: (item[1].page, item[1].y0))
    deduped: list[tuple[Block, OcrLine]] = []
    for block, line in starts:
        if deduped:
            prev_block, prev_line = deduped[-1]
            if block.block_id == prev_block.block_id and line.page == prev_line.page and abs(line.y0 - prev_line.y0) < 24:
                continue
        deduped.append((block, line))
    return deduped


def build_question_blocks(ocr_pages_map: dict[int, list[OcrLine]], question_regions: list[Block]) -> list[Block]:
    starts = detect_question_starts(ocr_pages_map, question_regions)
    questions: list[Block] = []
    for idx, (block, line) in enumerate(starts, start=1):
        if idx < len(starts) and starts[idx][0].block_id == block.block_id:
            next_line = starts[idx][1]
            end_page = next_line.page
            end_y = next_line.y0 - 18
        else:
            end_page = block.end_page
            end_y = block.end_y
        number = QUESTION_RE.match(line.text).group(0).rstrip(". ").strip()
        questions.append(
            Block(
                block_id=f"question_{idx:03d}",
                kind="question_slice",
                label=f"{block.label} - 题{number}",
                start_page=line.page,
                start_y=max(80, line.y0 - 18),
                end_page=end_page,
                end_y=end_y,
            )
        )
    return questions


def meaningful_lines_for_page(block: Block, page_no: int, ocr_pages_map: dict[int, list[OcrLine]]) -> list[OcrLine]:
    lines = []
    for line in ocr_pages_map.get(page_no, []):
        if page_no == block.start_page and line.y1 < block.start_y:
            continue
        if page_no == block.end_page and line.y0 > block.end_y:
            continue
        if any(token in line.text for token in HEADER_FILTERS):
            continue
        if re.fullmatch(r"\d{1,2}", line.text):
            continue
        lines.append(line)
    return lines


def crop_block(block: Block, page_paths: list[Path], ocr_pages_map: dict[int, list[OcrLine]], out_path: Path) -> None:
    pieces: list[Image.Image] = []
    for page_no in range(block.start_page, block.end_page + 1):
        page_lines = meaningful_lines_for_page(block, page_no, ocr_pages_map)
        if not page_lines:
            continue
        img = Image.open(page_paths[page_no - 1]).convert("RGB")
        x0, base_y0, x1, base_y1 = content_bounds(img)
        min_line_y0 = min(line.y0 for line in page_lines)
        max_line_y1 = max(line.y1 for line in page_lines)
        y0 = block.start_y if page_no == block.start_page else min_line_y0
        y1 = block.end_y if page_no == block.end_page else max_line_y1
        y0 = max(base_y0, min(y0, min_line_y0) - 10)
        y1 = min(base_y1, max(y1, max_line_y1) + 12)
        if y1 <= y0 + 24:
            continue
        pieces.append(img.crop((x0, y0, x1, y1)))
    if not pieces:
        return
    width = max(piece.width for piece in pieces)
    height = sum(piece.height for piece in pieces) + max(0, len(pieces) - 1) * 16
    canvas = Image.new("RGB", (width, height), "white")
    cursor = 0
    draw = ImageDraw.Draw(canvas)
    for idx, piece in enumerate(pieces):
        canvas.paste(piece, (0, cursor))
        cursor += piece.height
        if idx < len(pieces) - 1:
            draw.line((0, cursor + 8, width, cursor + 8), fill=(210, 214, 222), width=2)
            cursor += 16
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def extract_block_text(block: Block, ocr_pages_map: dict[int, list[OcrLine]]) -> str:
    rows: list[str] = []
    for page in range(block.start_page, block.end_page + 1):
        for line in ocr_pages_map.get(page, []):
            if page == block.start_page and line.y1 < block.start_y:
                continue
            if page == block.end_page and line.y0 > block.end_y:
                continue
            if any(token in line.text for token in HEADER_FILTERS):
                continue
            if re.fullmatch(r"\d{1,2}", line.text):
                continue
            rows.append(line.text)
    return "\n".join(rows).strip()


def write_block_artifacts(blocks: list[Block], page_paths: list[Path], ocr_pages_map: dict[int, list[OcrLine]], crop_dir: Path, text_dir: Path) -> None:
    for idx, block in enumerate(blocks, start=1):
        crop_path = crop_dir / f"{block.block_id}.png"
        crop_block(block, page_paths, ocr_pages_map, crop_path)
        block.crop_path = str(crop_path)
        text = extract_block_text(block, ocr_pages_map)
        block.text_preview = norm(text).replace("\n", " ")[:220]
        transcript_path = text_dir / f"{block.block_id}.md"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(f"# {block.label}\n\n{text}\n", encoding="utf-8")
        block.transcript_path = str(transcript_path)
        print(f"[artifact] {idx}/{len(blocks)} {block.block_id}")


def make_contact_sheet(blocks: list[Block], title: str, out_path: Path) -> None:
    cards: list[Image.Image] = []
    header_font = font(26)
    body_font = font(18)
    for block in blocks:
        path = Path(block.crop_path)
        if not path.exists():
            continue
        img = Image.open(path).convert("RGB")
        img.thumbnail((360, 250))
        card = Image.new("RGB", (400, 332), "white")
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle((4, 4, 396, 328), radius=12, outline=(219, 227, 240), width=2)
        draw.text((14, 12), block.label[:34], fill=(20, 30, 45), font=body_font)
        draw.text((14, 38), f"{block.kind} | P{block.start_page}-{block.end_page}", fill=(102, 117, 138), font=body_font)
        card.paste(img, ((400 - img.width) // 2, 68))
        cards.append(card)
    if not cards:
        return
    cols = 3
    rows = math.ceil(len(cards) / cols)
    sheet = Image.new("RGB", (cols * 400, rows * 332 + 60), (246, 248, 252))
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 14), title, fill=(20, 30, 45), font=header_font)
    for idx, card in enumerate(cards):
        sheet.paste(card, ((idx % cols) * 400, (idx // cols) * 332 + 60))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def write_preview_html(components: list[Block], questions: list[Block], out_path: Path) -> None:
    def render_cards(blocks: list[Block]) -> str:
        parts = []
        for block in blocks:
            crop_rel = Path(block.crop_path).parent.name + "/" + Path(block.crop_path).name
            txt_rel = Path(block.transcript_path).parent.name + "/" + Path(block.transcript_path).name
            parts.append(
                f"""
                <article class="card">
                  <div class="meta">
                    <strong>{block.label}</strong>
                    <span>{block.kind} | P{block.start_page}-{block.end_page}</span>
                  </div>
                  <img src="./{crop_rel}" alt="{block.label}">
                  <p>{block.text_preview}</p>
                  <a href="./{txt_rel}" target="_blank">查看转录</a>
                </article>
                """
            )
        return "\n".join(parts)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>教师讲义 runtime 预览</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f7fb; color: #18243a; }}
    header {{ background: white; padding: 28px 32px; box-shadow: 0 8px 24px rgba(37, 61, 98, .08); position: sticky; top: 0; }}
    h1 {{ margin: 0; font-size: 30px; }}
    .sub {{ margin-top: 8px; color: #65758c; }}
    main {{ padding: 22px 28px 60px; }}
    h2 {{ margin: 28px 0 14px; font-size: 24px; }}
    .grid {{ display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .card {{ background: white; border: 1px solid #dde6f4; border-radius: 14px; padding: 14px; box-shadow: 0 10px 24px rgba(32, 52, 84, .06); }}
    .card img {{ width: 100%; border-radius: 10px; border: 1px solid #e8eef8; }}
    .meta {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }}
    .meta span {{ color: #708096; font-size: 13px; }}
    .card p {{ min-height: 66px; line-height: 1.65; color: #324157; font-size: 14px; }}
    a {{ color: #2257f3; text-decoration: none; font-weight: 700; }}
  </style>
</head>
<body>
  <header>
    <h1>教师讲义 runtime 结果</h1>
    <div class="sub">页级 OCR 缓存 -> 组件判定 -> 单题切分 -> 转录输出</div>
  </header>
  <main>
    <h2>常规组件与例题组</h2>
    <section class="grid">{render_cards(components)}</section>
    <h2>单题切片</h2>
    <section class="grid">{render_cards(questions)}</section>
  </main>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def publish_results(work_dir: Path, publish_dir: Path) -> None:
    if publish_dir.exists():
        shutil.rmtree(publish_dir)
    shutil.copytree(work_dir, publish_dir)


def package_dir(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in source_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir.parent))


def main() -> None:
    source_pdf = Path(os.environ.get("SOURCE_PDF_ASCII", r"C:\codex_tmp\english_narrative_teacher.pdf"))
    run_name = os.environ.get("RUN_NAME", "english_teacher_runtime_v01")
    workspace_root = Path.cwd()
    work_root = Path(r"C:\codex_tmp\teacher_handout_runtime") / run_name
    publish_root = workspace_root / "outputs" / "ingress_runtime_v0.1" / run_name
    state_path = work_root / "runtime_state.json"

    work_root.mkdir(parents=True, exist_ok=True)
    local_pdf = work_root / "source.pdf"
    if not local_pdf.exists():
        shutil.copyfile(source_pdf, local_pdf)

    stage_state(
        state_path,
        run_name=run_name,
        source_pdf=str(source_pdf),
        work_root=str(work_root),
        publish_root=str(publish_root),
        current_stage="init",
    )

    pages_dir = work_root / "pages"
    ocr_dir = work_root / "ocr_pages"
    component_crop_dir = work_root / "component_crops"
    component_text_dir = work_root / "component_transcripts"
    question_crop_dir = work_root / "question_crops"
    question_text_dir = work_root / "question_transcripts"

    page_paths = render_pdf(local_pdf, pages_dir, DEFAULT_SCALE)
    stage_state(state_path, current_stage="render_complete", page_count=len(page_paths))

    ocr_pages_map = ocr_pages(page_paths, ocr_dir, state_path)
    stage_state(state_path, current_stage="ocr_complete")

    components = build_component_blocks(page_paths, ocr_pages_map)
    example_blocks = build_example_blocks(page_paths, ocr_pages_map, components)
    question_regions = [*example_blocks, *[block for block in components if block.kind == "after_class"]]
    questions = build_question_blocks(ocr_pages_map, question_regions)
    stage_state(
        state_path,
        current_stage="blocks_detected",
        component_count=len(components),
        example_count=len(example_blocks),
        question_count=len(questions),
    )
    print(f"[detect] components={len(components)} examples={len(example_blocks)} questions={len(questions)}")

    write_block_artifacts(components, page_paths, ocr_pages_map, component_crop_dir, component_text_dir)
    write_block_artifacts(questions, page_paths, ocr_pages_map, question_crop_dir, question_text_dir)
    stage_state(state_path, current_stage="artifacts_written")

    make_contact_sheet(components, "常规组件与例题组", work_root / "components_contact_sheet.jpg")
    make_contact_sheet(questions, "单题切片", work_root / "questions_contact_sheet.jpg")
    write_preview_html(components, questions, work_root / "preview_gallery.html")
    write_json(
        work_root / "runtime_manifest.json",
        {
            "run_name": run_name,
            "source_pdf": str(source_pdf),
            "page_count": len(page_paths),
            "component_count": len(components),
            "question_count": len(questions),
            "components": [asdict(item) for item in components],
            "questions": [asdict(item) for item in questions],
        },
    )
    stage_state(state_path, current_stage="manifest_ready")

    publish_results(work_root, publish_root)
    package_dir(publish_root, publish_root.parent / f"{run_name}_package.zip")
    stage_state(state_path, current_stage="published", published=True)

    print(
        json.dumps(
            {
                "publish_root": str(publish_root),
                "package": str(publish_root.parent / f"{run_name}_package.zip"),
                "gallery": str(publish_root / "preview_gallery.html"),
                "components_contact_sheet": str(publish_root / "components_contact_sheet.jpg"),
                "questions_contact_sheet": str(publish_root / "questions_contact_sheet.jpg"),
                "state": str(work_root / "runtime_state.json"),
                "manifest": str(publish_root / "runtime_manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
