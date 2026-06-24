# 用途：
# - 通过裁剪源标记并重新组装，生成分层可打印 PDF 页面。
# - 裁剪和分页假设集中在这里，方便后续调参。

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


STUDENT_PDF = Path(
    r"C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一数学学科资料\高中数学\01标准化讲义\01 暑假\01 高一\第6讲 基本不等式\第6讲 基本不等式 - 学生版.pdf"
)

TEACHER_PDF = Path(
    r"C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一数学学科资料\高中数学\01标准化讲义\01 暑假\01 高一\第6讲 基本不等式\第6讲 基本不等式 - 教师版.pdf"
)

SPLIT_JSON = Path(
    r"C:\Users\EDY\Documents\教研基建\outputs\split_builder\math_basic_inequality\lesson_split.json"
)

OUT_DIR = Path(r"C:\Users\EDY\Documents\教研基建\outputs\tiered_handouts\basic_inequality")

SECTION_RE = re.compile(r"^考点\s*(\d+)\s*[:：]\s*(.+)$")
QUESTION_RE = re.compile(r"^(\d{1,2})[．.、]\s*")

SECTION_TITLES = {
    "1": "不等式的直接应用",
    "2": "配凑法求最值",
    "3": "常数代换法求最值",
    "4": "消元法求最值",
    "5": "整体化求最值",
}

# 阅读者分层：保持同一课堂节奏，只改任务题块。
TIER_TASKS = {
    "低档版": [
        "s1_q1",
        "s1_q2",
        "s1_q4",
        "s1_q5",
        "s1_q6",
        "s1_q7",
        "s2_q4",
        "s2_q5",
        "s2_q7",
        "s3_q2",
        "s3_q6",
        "s4_q1",
        "s5_q2",
        "s5_q3",
        "s5_q7",
        "s5_q8",
    ],
    "中档版": [
        "s1_q1",
        "s1_q2",
        "s1_q3",
        "s1_q4",
        "s1_q5",
        "s1_q6",
        "s1_q7",
        "s1_q8",
        "s2_q1",
        "s2_q3",
        "s2_q4",
        "s2_q5",
        "s2_q6",
        "s2_q7",
        "s2_q8",
        "s3_q1",
        "s3_q2",
        "s3_q5",
        "s3_q6",
        "s4_q1",
        "s5_q2",
        "s5_q3",
        "s5_q5",
        "s5_q7",
        "s5_q8"
    ],
    "高档版": [
        "s1_q3",
        "s1_q8",
        "s1_q9",
        "s2_q2",
        "s2_q3",
        "s2_q6",
        "s2_q8",
        "s2_q9",
        "s3_q1",
        "s3_q3",
        "s3_q4",
        "s4_q2",
        "s4_q3",
        "s4_q4",
        "s4_q5",
        "s4_q6",
        "s5_q1",
        "s5_q4",
        "s5_q6",
        "s5_q9",
        "s5_q10",
    ],
}

TIER_NOTES = {
    "低档版": "保留概念辨析、等号条件、直接最值和低门槛方法题，删去证明和综合迁移。",
    "中档版": "保留完整标准方法链，覆盖五个考点下的常规题型，删去少量证明和强综合题。",
    "高档版": "压缩原型题，保留判断陷阱、函数/分式最值、消元、整体化和证明迁移。",
}


@dataclass
class Marker:
    kind: str
    key: str
    section: str
    page: int
    top: float
    bottom: float
    global_top: float
    text: str


def render_pdf_pages(pdf_path: Path, scale: float = 2.5) -> Tuple[List[Image.Image], float, float]:
    doc = pdfium.PdfDocument(str(pdf_path))
    rendered: List[Image.Image] = []
    page_width = page_height = 0.0
    for i in range(len(doc)):
        page = doc[i]
        page_width, page_height = page.get_size()
        bitmap = page.render(scale=scale)
        rendered.append(bitmap.to_pil().convert("RGB"))
        page.close()
    doc.close()
    return rendered, page_width, page_height


def extract_markers(pdf_path: Path) -> Tuple[List[Marker], Dict[str, Tuple[int, float, float]], float, float]:
    markers: List[Marker] = []
    section_headers: Dict[str, Tuple[int, float, float]] = {}
    active_section = ""
    header_start: Dict[str, Tuple[int, float]] = {}

    with pdfplumber.open(str(pdf_path)) as pdf:
        page_width = float(pdf.pages[0].width)
        page_height = float(pdf.pages[0].height)
        for page_number, page in enumerate(pdf.pages, start=1):
            lines = page.extract_text_lines() or []
            for line in lines:
                text = re.sub(r"\s+", " ", line.get("text", "")).strip()
                if not text:
                    continue
                top = float(line["top"])
                bottom = float(line["bottom"])
                global_top = (page_number - 1) * page_height + top
                section_match = SECTION_RE.match(text)
                if section_match:
                    active_section = section_match.group(1)
                    header_start[active_section] = (page_number, top)
                    markers.append(
                        Marker("section", f"section_{active_section}", active_section, page_number, top, bottom, global_top, text)
                    )
                    continue

                question_match = QUESTION_RE.match(text)
                if question_match and active_section:
                    q_no = question_match.group(1)
                    key = f"s{active_section}_q{q_no}"
                    if active_section in header_start and active_section not in section_headers:
                        header_page, header_top = header_start[active_section]
                        if header_page == page_number:
                            section_headers[active_section] = (page_number, header_top, max(header_top + 18, top - 4))
                    markers.append(Marker("question", key, active_section, page_number, top, bottom, global_top, text))

    markers.sort(key=lambda item: item.global_top)
    return markers, section_headers, page_width, page_height


def build_task_segments(markers: List[Marker], page_height: float, page_count: int) -> Dict[str, Tuple[float, float]]:
    question_markers = [marker for marker in markers if marker.kind == "question"]
    next_markers = markers[1:] + []
    task_ranges: Dict[str, Tuple[float, float]] = {}
    for i, marker in enumerate(question_markers):
        later = [m for m in markers if m.global_top > marker.global_top and m.kind in {"question", "section"}]
        end = later[0].global_top - 3 if later else page_count * page_height - 50
        task_ranges[marker.key] = (max(marker.global_top - 2, 0), max(end, marker.global_top + 18))
    return task_ranges


def pdf_to_pixel(value: float, scale: float) -> int:
    return int(round(value * scale))


def crop_global(
    images: List[Image.Image],
    start_global: float,
    end_global: float,
    page_width: float,
    page_height: float,
    scale: float,
    left_pt: float = 38,
    right_pt: float = 555,
) -> List[Image.Image]:
    crops: List[Image.Image] = []
    first_page = int(start_global // page_height) + 1
    last_page = int(max(end_global - 0.01, 0) // page_height) + 1
    for page in range(first_page, last_page + 1):
        page_start = (page - 1) * page_height
        top = max(start_global - page_start, 58)
        bottom = min(end_global - page_start, page_height - 44)
        if bottom <= top + 4:
            continue
        image = images[page - 1]
        left_px = pdf_to_pixel(left_pt, scale)
        right_px = min(pdf_to_pixel(right_pt, scale), image.width)
        top_px = max(pdf_to_pixel(top, scale), 0)
        bottom_px = min(pdf_to_pixel(bottom, scale), image.height)
        if bottom_px <= top_px + 8:
            continue
        crop = image.crop((left_px, top_px, right_px, bottom_px))
        crops.append(crop)
    return crops


def crop_local(
    images: List[Image.Image],
    page: int,
    top: float,
    bottom: float,
    scale: float,
    left_pt: float = 38,
    right_pt: float = 555,
) -> Image.Image:
    image = images[page - 1]
    return image.crop(
        (
            pdf_to_pixel(left_pt, scale),
            max(pdf_to_pixel(top, scale), 0),
            min(pdf_to_pixel(right_pt, scale), image.width),
            min(pdf_to_pixel(bottom, scale), image.height),
        )
    )


def paste_block(page: Image.Image, block: Image.Image, y: int, x: int) -> None:
    page.paste(block, (x, y))


def make_pages_for_tier(
    tier_name: str,
    selected_keys: List[str],
    images: List[Image.Image],
    section_headers: Dict[str, Tuple[int, float, float]],
    task_ranges: Dict[str, Tuple[float, float]],
    page_width: float,
    page_height: float,
    scale: float,
) -> List[Image.Image]:
    source_page = images[0]
    page_size = source_page.size
    full_pages: List[Image.Image] = [source_page.copy()]

    header = source_page.crop((0, 0, source_page.width, pdf_to_pixel(56, scale)))
    page_no_font = ImageFont.load_default()
    content_top = pdf_to_pixel(66, scale)
    bottom_limit = pdf_to_pixel(page_height - 48, scale)
    x = pdf_to_pixel(38, scale)
    gap = pdf_to_pixel(8, scale)

    current = Image.new("RGB", page_size, "white")
    paste_block(current, header, 0, 0)
    y = content_top

    # 学生版第 2 页顶部是知识主干的续写，需保留。
    first_section_global = page_height + section_headers.get("1", (2, 130, 160))[1]
    knowledge_continuation = crop_global(
        images,
        page_height + 58,
        first_section_global - 18,
        page_width,
        page_height,
        scale,
    )
    for block in knowledge_continuation:
        if block.height > 10:
            paste_block(current, block, y, x)
            y += block.height + gap

    def new_page() -> Image.Image:
        page = Image.new("RGB", page_size, "white")
        paste_block(page, header, 0, 0)
        return page

    last_section = None
    for key in selected_keys:
        section = key.split("_")[0].replace("s", "")
        if section != last_section:
            if section in section_headers:
                header_page, header_top, header_bottom = section_headers[section]
                section_block = crop_local(images, header_page, header_top - 2, header_bottom + 3, scale)
                if y + section_block.height > bottom_limit:
                    full_pages.append(current)
                    current = new_page()
                    y = content_top
                paste_block(current, section_block, y, x)
                y += section_block.height + gap
            last_section = section

        if key not in task_ranges:
            continue
        start, end = task_ranges[key]
        blocks = crop_global(images, start, end, page_width, page_height, scale)
        for block in blocks:
            if block.height <= 10:
                continue
            if y + block.height > bottom_limit:
                full_pages.append(current)
                current = new_page()
                y = content_top
            paste_block(current, block, y, x)
            y += block.height + gap

    full_pages.append(current)
    numbered: List[Image.Image] = []
    total = len(full_pages)
    for idx, page in enumerate(full_pages, start=1):
        draw = ImageDraw.Draw(page)
        draw.text((page.width // 2, page.height - pdf_to_pixel(26, scale)), str(idx), fill=(40, 40, 40), font=page_no_font)
        numbered.append(page)
    return numbered


def save_pages_as_pdf(pages: List[Image.Image], output_pdf: Path, page_width: float, page_height: float) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_pdf), pagesize=(page_width, page_height))
    for idx, page in enumerate(pages):
        temp_png = output_pdf.with_suffix(f".page{idx + 1}.png")
        page.save(temp_png, "PNG")
        c.drawImage(ImageReader(str(temp_png)), 0, 0, width=page_width, height=page_height)
        c.showPage()
        temp_png.unlink(missing_ok=True)
    c.save()


def load_task_lookup() -> Dict[str, Dict]:
    with SPLIT_JSON.open(encoding="utf-8") as f:
        data = json.load(f)
    return {task["task_id"]: task for task in data["tasks"]}


def write_split_record(task_lookup: Dict[str, Dict], output_paths: Dict[str, Path]) -> None:
    lines: List[str] = []
    lines.append("# 基本不等式分层拆分记录")
    lines.append("")
    lines.append("样本：高一数学暑假《第6讲 基本不等式》学生版。")
    lines.append("处理口径：保留原课程目标、知识主干、五个考点顺序，只对任务题块做分层筛选。")
    lines.append("说明：三档 PDF 为学生讲义，不包含教师版答案解析；教师版仅用于分层阅读和答案状态复核。")
    lines.append("")
    lines.append("## 输出 PDF")
    lines.append("")
    for label, path in output_paths.items():
        lines.append(f"- {label}: `{path}`")
    lines.append("")
    lines.append("## 三档拆分依据")
    lines.append("")
    for tier, note in TIER_NOTES.items():
        lines.append(f"### {tier}")
        lines.append("")
        lines.append(note)
        lines.append("")
        grouped: Dict[str, List[str]] = {}
        for key in TIER_TASKS[tier]:
            section = key.split("_")[0].replace("s", "")
            grouped.setdefault(section, []).append(key)
        for section, keys in grouped.items():
            labels = []
            for key in keys:
                task = task_lookup.get(key, {})
                labels.append(f"{key}({task.get('question_no', '?')})")
            lines.append(f"- 考点 {section}：{', '.join(labels)}")
        lines.append("")

    lines.append("## 阅读者观察")
    lines.append("")
    lines.append("- 低档版仍覆盖五个考点，但每个考点只保留原型题或低门槛方法题，适合概念未稳的学生。")
    lines.append("- 中档版基本保持原讲义的标准课堂路径，删除证明和强综合后仍能覆盖完整方法链。")
    lines.append("- 高档版不再保留大量直接套公式题，重点放在判断陷阱、分式/函数最值、消元、整体化和证明。")
    lines.append("- 本次为了保持原格式，题块以原 PDF 视觉裁切重排，公式和版式保真度高，但生成 PDF 是图片型，后续产品化需记录题块坐标和文本结构双层数据。")
    (OUT_DIR / "分层拆分记录.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    scale = 2.5
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    original_copy = OUT_DIR / "00_原版_基本不等式_学生版.pdf"
    shutil.copy2(STUDENT_PDF, original_copy)

    images, page_width, page_height = render_pdf_pages(STUDENT_PDF, scale=scale)
    markers, section_headers, _, _ = extract_markers(STUDENT_PDF)
    task_ranges = build_task_segments(markers, page_height, len(images))
    task_lookup = load_task_lookup()

    output_paths: Dict[str, Path] = {"原版": original_copy}
    for tier_name, keys in TIER_TASKS.items():
        pages = make_pages_for_tier(
            tier_name,
            keys,
            images,
            section_headers,
            task_ranges,
            page_width,
            page_height,
            scale,
        )
        pdf_path = OUT_DIR / f"{tier_name}_基本不等式_学生版.pdf"
        save_pages_as_pdf(pages, pdf_path, page_width, page_height)
        output_paths[tier_name] = pdf_path

    write_split_record(task_lookup, output_paths)
    print("created")
    for label, path in output_paths.items():
        print(label, path)
    print("record", OUT_DIR / "分层拆分记录.md")


if __name__ == "__main__":
    main()
