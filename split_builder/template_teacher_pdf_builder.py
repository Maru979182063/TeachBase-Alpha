# Purpose:
# - Composes teacher-facing template PDFs with banners, icons, grouped split data, and layout rules.
# - Visual consistency changes should usually start here instead of scattered downstream scripts.

import html
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, ImageOps
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


TEACHER_PDF = Path(
    r"C:\Users\EDY\Documents\WXWork\1688857912801359\WeDrive\领世培优\领世一对一数学学科资料\高中数学\01标准化讲义\01 暑假\01 高一\第6讲 基本不等式\第6讲 基本不等式 - 教师版.pdf"
)
SPLIT_JSON = Path(
    r"C:\Users\EDY\Documents\教研基建\outputs\split_builder\math_basic_inequality\lesson_split.json"
)
OUT_DIR = Path(r"C:\Users\EDY\Documents\教研基建\outputs\tiered_handouts\basic_inequality_teacher_icon_package")
ICON_ROOT = Path(r"C:\Users\EDY\Documents\教研基建\assets\component_icons\math")
ICON_MANIFEST = ICON_ROOT / "component_icon_manifest.json"


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
        "s5_q8",
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

SECTION_TITLES = {
    "1": "不等式的直接应用",
    "2": "配凑法求最值",
    "3": "常数代换法求最值",
    "4": "消元法求最值",
    "5": "整体化求最值",
}

TIER_NOTES = {
    "低档版": "概念和公式入口版：保留成立条件、等号条件、低门槛最值和标准原型题。",
    "中档版": "标准课堂版：覆盖五个考点的常规方法链，去掉证明和强综合题。",
    "高档版": "提升迁移版：压缩直接套公式题，突出陷阱判断、消元、整体化和证明迁移。",
}


PUA_MAP = {
    "\uf02b": "+",
    "\uf02d": "-",
    "\uf03d": "=",
    "\uf03e": ">",
    "\uf03c": "<",
    "\uf085": "≥",
    "\uf0b3": "≥",
    "\uf084": "≤",
    "\uf0a3": "≤",
    "\uf0b9": "≠",
    "\uf0ce": "∈",
    "\uf0b1": "±",
    "\uf0d7": "·",
    "\uf028": "(",
    "\uf029": ")",
    "\uf0e7": "(",
    "\uf0f7": ")",
    "\uf0e6": "[",
    "\uf0f6": "]",
    "\uf0e8": "(",
    "\uf0f8": ")",
    "\uf0e9": "(",
    "\uf0f9": ")",
    "\uf0ea": "[",
    "\uf0fa": "]",
    "\uf0eb": "{",
    "\uf0fb": "}",
    "\uf051": "∵",
    "\uf05c": "∴",
    "\uf0a5": "∞",
}


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("SimHei", r"C:\Windows\Fonts\simhei.ttf"))
    pdfmetrics.registerFont(TTFont("SimSun", r"C:\Windows\Fonts\simsun.ttc"))


def norm_text(text: str) -> str:
    if not text:
        return ""
    for src, dst in PUA_MAP.items():
        text = text.replace(src, dst)
    text = re.sub(r"[\uf000-\uf8ff]", "", text)
    text = text.replace("＋", "+").replace("－", "-").replace("＝", "=")
    text = text.replace("", "≥").replace("", "≤").replace("", "∵").replace("", "∴")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def para(text: str, style: ParagraphStyle) -> Paragraph:
    text = html.escape(norm_text(text)).replace("\n", "<br/>")
    return Paragraph(text, style)


class SectionBadge(Flowable):
    def __init__(self, text: str, width: float):
        super().__init__()
        self.text = text
        self.width = width
        self.height = 22

    def draw(self):
        self.canv.setFillColor(colors.HexColor("#0B63CE"))
        self.canv.roundRect(0, 0, 92, 20, 4, fill=1, stroke=0)
        self.canv.setFillColor(colors.white)
        self.canv.setFont("SimHei", 10)
        self.canv.drawString(10, 5.5, self.text)


class RuleLine(Flowable):
    def __init__(self, width: float):
        super().__init__()
        self.width = width
        self.height = 9

    def draw(self):
        self.canv.setStrokeColor(colors.HexColor("#D6DCE5"))
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 5, self.width, 5)


def load_icon_manifest() -> Dict:
    if ICON_MANIFEST.exists():
        return json.loads(ICON_MANIFEST.read_text(encoding="utf-8"))
    return {"components": {}}


# Visual identity helper: resolves component icons into reusable PDF banner images.
def component_banner(component_id: str, width_pt: float = None) -> RLImage:
    manifest = load_icon_manifest()
    meta = manifest.get("components", {}).get(component_id)
    if not meta:
        return None
    path = ICON_ROOT / meta["asset"]
    if not path.exists():
        return None
    target_width = width_pt or float(meta.get("recommended_width_pt", 150))
    from PIL import Image as PILImage

    with PILImage.open(path) as image:
        w, h = image.size
    target_height = target_width * h / w
    return RLImage(str(path), width=target_width, height=target_height, kind="proportional")


def add_banner(story: List, component_id: str, fallback_label: str = "") -> None:
    banner = component_banner(component_id)
    if banner:
        story.append(banner)
        story.append(Spacer(1, 5))
    elif fallback_label:
        story.append(SectionBadge(fallback_label, 0))
        story.append(Spacer(1, 4))


def make_styles() -> Dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title",
            fontName="SimHei",
            fontSize=18,
            leading=24,
            alignment=TA_CENTER,
            spaceAfter=8,
            wordWrap="CJK",
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="SimSun",
            fontSize=9,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#667085"),
            spaceAfter=12,
            wordWrap="CJK",
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName="SimHei",
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#101828"),
            spaceBefore=6,
            spaceAfter=5,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "body",
            fontName="SimSun",
            fontSize=9.4,
            leading=15,
            textColor=colors.HexColor("#101828"),
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "small",
            fontName="SimSun",
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#475467"),
            wordWrap="CJK",
        ),
        "answer": ParagraphStyle(
            "answer",
            fontName="SimHei",
            fontSize=9.4,
            leading=15,
            textColor=colors.HexColor("#B42318"),
            wordWrap="CJK",
        ),
        "analysis": ParagraphStyle(
            "analysis",
            fontName="SimSun",
            fontSize=8.9,
            leading=14,
            textColor=colors.HexColor("#B42318"),
            wordWrap="CJK",
        ),
    }


def page_header(canvas_obj, doc):
    width, height = A4
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(colors.HexColor("#5C6675"))
    canvas_obj.setLineWidth(0.7)
    canvas_obj.line(28 * mm, height - 18 * mm, width - 42 * mm, height - 18 * mm)

    x = width - 39 * mm
    y = height - 23 * mm
    canvas_obj.setFillColor(colors.HexColor("#2364AA"))
    canvas_obj.roundRect(x, y + 2, 10, 10, 2, fill=1, stroke=0)
    canvas_obj.setFillColor(colors.HexColor("#F17B2D"))
    canvas_obj.roundRect(x + 7, y + 5, 7, 7, 2, fill=1, stroke=0)
    canvas_obj.setFillColor(colors.HexColor("#101828"))
    canvas_obj.setFont("SimHei", 9)
    canvas_obj.drawString(x + 17, y + 4, "领世1对1 | 数学")

    canvas_obj.setFillColor(colors.HexColor("#667085"))
    canvas_obj.setFont("SimSun", 8)
    canvas_obj.drawCentredString(width / 2, 11 * mm, str(doc.page))
    canvas_obj.restoreState()


def load_split() -> Dict:
    with SPLIT_JSON.open(encoding="utf-8") as f:
        return json.load(f)


def group_keys(keys: List[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for key in keys:
        section = key.split("_")[0].replace("s", "")
        grouped.setdefault(section, []).append(key)
    return grouped


# Layout stage: turns one task record into the flowables used by ReportLab pages.
def build_question_block(task: Dict, display_no: int, styles: Dict[str, ParagraphStyle]) -> List:
    story: List = []
    stem = task.get("teacher_stem") or task.get("student_stem") or ""
    answer = task.get("answer") or ""
    answer_raw = task.get("answer_raw") or ""
    explanation = task.get("explanation") or ""
    status = task.get("answer_status") or ""

    story.append(para(f"{display_no}. {strip_original_number(stem)}", styles["body"]))
    if answer:
        story.append(para(f"【答案】{answer}", styles["answer"]))
    elif status == "solution_only":
        story.append(para("【答案】见解析/解答过程", styles["answer"]))
    if explanation:
        story.append(para(f"【解析】{explanation}", styles["analysis"]))
    elif answer_raw and answer_raw != answer:
        story.append(para(f"【原始答案】{answer_raw}", styles["analysis"]))
    story.append(Spacer(1, 5))
    return story


def strip_original_number(text: str) -> str:
    text = norm_text(text)
    text = re.sub(r"^\d{1,2}[．.、]\s*", "", text)
    return text


# PDF assembly stage: groups tasks by tier and writes the final teacher-facing document.
def build_pdf(tier_name: str, keys: List[str], output_pdf: Path, split: Dict) -> None:
    styles = make_styles()
    task_map = {task["task_id"]: task for task in split["tasks"]}
    node_map = {node["node_id"]: node for node in split["nodes"]}
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=A4,
        rightMargin=24 * mm,
        leftMargin=24 * mm,
        topMargin=28 * mm,
        bottomMargin=20 * mm,
    )
    story: List = []
    title = f"基本不等式 - {tier_name} - 教师版"
    story.append(Paragraph(title, styles["title"]))
    story.append(Paragraph(TIER_NOTES[tier_name], styles["subtitle"]))

    goals = split["lesson"].get("learning_goals") or []
    add_banner(story, "course_goal", "课程目标")
    if goals:
        for idx, goal in enumerate(goals, start=1):
            story.append(para(f"{idx}. {goal}", styles["body"]))
    story.append(Spacer(1, 8))

    knowledge = node_map.get("knowledge_outline", {}).get("text", "")
    if knowledge:
        add_banner(story, "knowledge_outline", "知识梳理")
        story.append(para(knowledge, styles["body"]))
        add_banner(story, "key_review", "要点回顾")
        story.append(Spacer(1, 8))

    grouped = group_keys(keys)
    for section, section_keys in grouped.items():
        story.append(RuleLine(doc.width))
        story.append(Paragraph(f"考点 {section}：{SECTION_TITLES.get(section, '')}", styles["h1"]))
        add_banner(story, "key_quiz", "要点小测")
        current_bucket = None
        for idx, key in enumerate(section_keys, start=1):
            task = task_map.get(key)
            if not task:
                continue
            tier = task.get("difficulty_tier")
            if tier == "advanced":
                bucket = "ability_advance"
            elif idx <= 1:
                bucket = "example_explain"
            else:
                bucket = "intensive_training"
            if bucket != current_bucket:
                add_banner(
                    story,
                    bucket,
                    {
                        "example_explain": "例题讲解",
                        "intensive_training": "强化训练",
                        "ability_advance": "能力进阶",
                    }[bucket],
                )
                current_bucket = bucket
            block = build_question_block(task, idx, styles)
            story.append(KeepTogether(block))
        story.append(Spacer(1, 4))

    doc.build(story, onFirstPage=page_header, onLaterPages=page_header)


def write_record(outputs: Dict[str, Path]) -> None:
    lines = [
        "# 教师版模板重排试验记录",
        "",
        "本轮按用户要求改用教师版：原版教师 PDF + 低/中/高三档教师版重排 PDF。",
        "",
        "## 输出",
        "",
    ]
    for name, path in outputs.items():
        lines.append(f"- {name}: `{path}`")
    lines.extend(
        [
            "",
            "## 处理口径",
            "",
            "- 原 PDF 不再作为裁切拼贴材料，只作为内容来源和视觉风格参考。",
            "- 页眉、考点标题、题号、页码均由模板重新生成。",
            "- 栏目标题使用 `assets/component_icons/math` 下的数学组件 icon 包。",
            "- 题干、答案、解析来自教师版结构化结果。",
            "- 数学符号做了一轮私有字符规范化，但复杂分式仍是线性文本，后续需要公式插件。",
            "",
            "## 与上一版裁切方案相比",
            "",
            "- 消除了图标重复、考点标题残片、题号裁切破损。",
            "- 牺牲了原公式的精细排版，换来结构稳定和批量可控。",
            "- 后续产品化应采用：结构定位 -> 语义对象 -> 公式/图表资产 -> 模板排版。",
        ]
    )
    (OUT_DIR / "教师版模板重排记录.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    register_fonts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    split = load_split()
    outputs: Dict[str, Path] = {}
    original = OUT_DIR / "00_原版_基本不等式_教师版.pdf"
    shutil.copy2(TEACHER_PDF, original)
    outputs["原版教师版"] = original
    for tier_name, keys in TIER_TASKS.items():
        output_pdf = OUT_DIR / f"{tier_name}_基本不等式_教师版_模板重排.pdf"
        build_pdf(tier_name, keys, output_pdf, split)
        outputs[tier_name] = output_pdf
    write_record(outputs)
    print("created")
    for name, path in outputs.items():
        print(name, path)
    print("record", OUT_DIR / "教师版模板重排记录.md")


if __name__ == "__main__":
    main()
