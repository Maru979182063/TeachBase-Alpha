from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path.cwd()
OUT_DIR = ROOT / "outputs" / "external_demos"
OUT_PDF = OUT_DIR / "question_split_skill_flow_external_20260630.pdf"

FONT_REGULAR = "NotoSansSC"
FONT_BOLD = "NotoSansSCBold"


def register_fonts() -> None:
    regular = Path(r"C:\Windows\Fonts\msyh.ttc")
    bold = Path(r"C:\Windows\Fonts\msyhbd.ttc")
    if not regular.exists():
        regular = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
    if not bold.exists():
        bold = Path(r"C:\Windows\Fonts\simhei.ttf")
    if not bold.exists():
        bold = regular
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(regular)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))


def p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe, style)


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["title"] = ParagraphStyle(
        "TitleCN",
        parent=base["Title"],
        fontName=FONT_BOLD,
        fontSize=27,
        leading=32,
        textColor=colors.HexColor("#17211f"),
        alignment=TA_LEFT,
        wordWrap="CJK",
        spaceAfter=8,
    )
    styles["subtitle"] = ParagraphStyle(
        "SubtitleCN",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#66706d"),
        wordWrap="CJK",
    )
    styles["h2"] = ParagraphStyle(
        "H2CN",
        parent=base["Heading2"],
        fontName=FONT_BOLD,
        fontSize=19,
        leading=24,
        textColor=colors.HexColor("#1f6b58"),
        wordWrap="CJK",
        spaceBefore=6,
        spaceAfter=8,
    )
    styles["h3"] = ParagraphStyle(
        "H3CN",
        parent=base["Heading3"],
        fontName=FONT_BOLD,
        fontSize=12.5,
        leading=16,
        textColor=colors.HexColor("#a84c32"),
        wordWrap="CJK",
    )
    styles["body"] = ParagraphStyle(
        "BodyCN",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=8.8,
        leading=12.8,
        textColor=colors.HexColor("#263331"),
        wordWrap="CJK",
    )
    styles["small"] = ParagraphStyle(
        "SmallCN",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=8.2,
        leading=12,
        textColor=colors.HexColor("#66706d"),
        wordWrap="CJK",
    )
    styles["card_no"] = ParagraphStyle(
        "CardNo",
        parent=base["Normal"],
        fontName=FONT_BOLD,
        fontSize=16,
        leading=18,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    styles["card_title"] = ParagraphStyle(
        "CardTitle",
        parent=base["Normal"],
        fontName=FONT_BOLD,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#182322"),
        wordWrap="CJK",
    )
    styles["card_kicker"] = ParagraphStyle(
        "CardKicker",
        parent=base["Normal"],
        fontName=FONT_BOLD,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#a84c32"),
        wordWrap="CJK",
    )
    styles["metric_num"] = ParagraphStyle(
        "MetricNum",
        parent=base["Normal"],
        fontName=FONT_BOLD,
        fontSize=19,
        leading=22,
        textColor=colors.HexColor("#1f6b58"),
        alignment=TA_CENTER,
    )
    styles["metric_label"] = ParagraphStyle(
        "MetricLabel",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=8.4,
        leading=11,
        textColor=colors.HexColor("#66706d"),
        alignment=TA_CENTER,
        wordWrap="CJK",
    )
    styles["table_head"] = ParagraphStyle(
        "TableHeadCN",
        parent=base["Normal"],
        fontName=FONT_BOLD,
        fontSize=8.6,
        leading=11,
        textColor=colors.white,
        alignment=TA_CENTER,
        wordWrap="CJK",
    )
    styles["table_body"] = ParagraphStyle(
        "TableBodyCN",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=7.4,
        leading=10.3,
        textColor=colors.HexColor("#263331"),
        wordWrap="CJK",
    )
    return styles


class SkillFlow(Flowable):
    def __init__(self, width: float, height: float, styles: dict[str, ParagraphStyle]):
        super().__init__()
        self.width = width
        self.height = height
        self.styles = styles

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        return self.width, self.height

    def _draw_wrapped(self, text: str, x: float, y: float, width: float, style: ParagraphStyle) -> float:
        para = p(text, style)
        _, h = para.wrap(width, 80)
        para.drawOn(self.canv, x, y - h)
        return h

    def draw(self) -> None:
        c = self.canv
        green = colors.HexColor("#1f6b58")
        gold = colors.HexColor("#b88b3a")
        blue = colors.HexColor("#345f7c")
        red = colors.HexColor("#a84c32")
        panel = colors.HexColor("#fffdf8")
        line = colors.HexColor("#ded6c8")
        ink = colors.HexColor("#182322")

        steps = [
            ("01", "接收材料", "PDF / 图片页 / 题包", "只当原始证据"),
            ("02", "还原页面", "PyMuPDF 渲染整页图", "文字层和 OCR 只辅助"),
            ("03", "找边界", "章节锚点 + 题号规则", "确定组件和题块"),
            ("04", "切题归属", "跨页拼接 + 裁图", "题干、选项、图、解析不拆散"),
            ("05", "准备图文", "选项图定位 + 资产挂载", "doubao-seed-2-0-lite"),
            ("06", "视觉转录", "doubao-seed-2-0-lite", "输出题干、答案、解析、LaTeX"),
            ("07", "结构校验", "规则归一 + 风险检测", "标记不确定片段和入库口径"),
            ("08", "交付回看", "JSON / Excel / HTML / PDF", "给老师复核和入库使用"),
        ]

        cols = 4
        box_w = (self.width - 42) / cols
        box_h = 64
        gap = 14
        top_y = self.height - 20
        positions = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (2, 1), (1, 1), (0, 1)]
        boxes: list[tuple[float, float, float, float]] = []
        for idx, (no, title, tech, note) in enumerate(steps):
            col, row = positions[idx]
            x = col * (box_w + gap)
            y = top_y - row * (box_h + 34) - box_h
            boxes.append((x, y, box_w, box_h))
            c.setFillColor(panel)
            c.setStrokeColor(line)
            c.roundRect(x, y, box_w, box_h, 7, stroke=1, fill=1)
            c.setFillColor(green if idx not in {5, 6} else (blue if idx == 5 else red))
            c.roundRect(x + 8, y + box_h - 28, 31, 22, 4, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.setFont(FONT_BOLD, 10)
            c.drawCentredString(x + 23.5, y + box_h - 22, no)
            c.setFillColor(ink)
            c.setFont(FONT_BOLD, 12)
            c.drawString(x + 47, y + box_h - 20, title)
            c.setFont(FONT_REGULAR, 8.7)
            c.setFillColor(colors.HexColor("#4e5d59"))
            c.drawString(x + 10, y + 25, tech)
            c.setFillColor(colors.HexColor("#66706d"))
            c.drawString(x + 10, y + 11, note)

        for idx in range(len(boxes) - 1):
            x1, y1, w1, h1 = boxes[idx]
            x2, y2, w2, h2 = boxes[idx + 1]
            if abs(y1 - y2) < 1 and x2 > x1:
                ax = x1 + w1 + 2
                ay = y1 + h1 / 2
                c.setStrokeColor(gold)
                c.setLineWidth(1.2)
                c.line(ax, ay, ax + gap - 5, ay)
                c.setFillColor(gold)
                c.line(ax + gap - 5, ay, ax + gap - 10, ay + 4)
                c.line(ax + gap - 5, ay, ax + gap - 10, ay - 4)
            elif abs(y1 - y2) < 1 and x2 < x1:
                ax = x1 - 2
                ay = y1 + h1 / 2
                c.setStrokeColor(gold)
                c.setLineWidth(1.2)
                c.line(ax, ay, ax - gap + 5, ay)
                c.setFillColor(gold)
                c.line(ax - gap + 5, ay, ax - gap + 10, ay + 4)
                c.line(ax - gap + 5, ay, ax - gap + 10, ay - 4)
            elif abs(x1 - x2) < 1 and y2 < y1:
                c.setStrokeColor(gold)
                c.setLineWidth(1.2)
                cx = x1 + w1 / 2
                c.line(cx, y1 - 4, cx, y2 + h2 + 10)
                c.setFillColor(gold)
                c.line(cx, y2 + h2 + 10, cx - 4, y2 + h2 + 16)
                c.line(cx, y2 + h2 + 10, cx + 4, y2 + h2 + 16)

        c.setFillColor(colors.HexColor("#fff9ed"))
        c.setStrokeColor(colors.HexColor("#d5c2a4"))
        c.roundRect(0, 8, self.width, 44, 6, stroke=1, fill=1)
        c.setFillColor(red)
        c.setFont(FONT_BOLD, 10.5)
        c.drawString(12, 34, "关键口径")
        c.setFillColor(colors.HexColor("#5f554b"))
        c.setFont(FONT_REGULAR, 8.8)
        c.drawString(76, 34, "这条链路不是“直接 OCR 文字”，而是先把页面当图片还原，再让模型看图转成结构化题目。")
        c.drawString(76, 19, "模型负责看题和转录；边界、挂图、质量门控由稳定规则兜底，便于解释和复查。")


def metric_table(styles: dict[str, ParagraphStyle]) -> Table:
    items = [
        ("200", "数学符号压测题池"),
        ("197", "可直接入库"),
        ("3", "需人工复核"),
        ("98.5%", "测试转录成功率"),
        ("10", "5题对照组合并口径"),
    ]
    cells = []
    for num, label in items:
        cells.append([p(num, styles["metric_num"]), p(label, styles["metric_label"])])
    table = Table([cells], colWidths=[42 * mm] * len(items), rowHeights=[18 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf8")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#ded6c8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#ded6c8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def skill_cards(styles: dict[str, ParagraphStyle]) -> Table:
    cards = [
        ("01", "输入", "接收材料", "PDF、图片页、已有题包都先当作原始证据，不直接信文字层。"),
        ("02", "还原", "按页看版面", "把页面当图片看，保留整页长图，避免公式和图形被误读。"),
        ("03", "定位", "找到题目边界", "识别章节、考点、例题、练习、题号等锚点，先确定题属于谁。"),
        ("04", "切分", "拆成独立题包", "每题保留题干、选项、图形、答案、解析；跨页题自动拼接。"),
        ("05", "转录", "看图输出结构", "视觉模型读取题图，按题干、答案、解析、手写补充等字段输出。"),
        ("06", "回看", "质检后交付", "生成 Excel、JSON、HTML/PDF 回看页，问题进入复核或局部修正。"),
    ]
    rows = []
    for idx in range(0, len(cards), 3):
        row = []
        for no, kicker, title, body in cards[idx : idx + 3]:
            no_box = Table([[p(no, styles["card_no"])]], colWidths=[13 * mm], rowHeights=[10 * mm])
            no_box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1f6b58")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            row.append(
                [
                    no_box,
                    Spacer(1, 4),
                    p(kicker, styles["card_kicker"]),
                    p(title, styles["card_title"]),
                    p(body, styles["body"]),
                ]
            )
        rows.append(row)
    table = Table(rows, colWidths=[78 * mm, 78 * mm, 78 * mm], rowHeights=[42 * mm, 42 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf8")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#ded6c8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#ded6c8")),
                ("LINEABOVE", (0, 0), (-1, -1), 2.2, colors.HexColor("#1f6b58")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def detail_table(rows: list[tuple[str, str, str, str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    header = ["环节", "为什么要做", "系统做什么", "模型或技术调用", "输出给下一环"]
    data = [[p(item, styles["table_head"]) for item in header]]
    for row in rows:
        data.append([p(item, styles["table_body"]) for item in row])
    table = Table(
        data,
        colWidths=[24 * mm, 45 * mm, 54 * mm, 60 * mm, 50 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6b58")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fffdf8")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#ded6c8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ded6c8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def callout_grid(items: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    rows = []
    for idx in range(0, len(items), 2):
        row = []
        for title, body in items[idx : idx + 2]:
            row.append([p(title, styles["card_title"]), p(body, styles["body"])])
        if len(row) == 1:
            row.append("")
        rows.append(row)
    table = Table(rows, colWidths=[113 * mm, 113 * mm], rowHeights=[34 * mm] * len(rows))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf8")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#ded6c8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#ded6c8")),
                ("LINEBEFORE", (0, 0), (-1, -1), 3, colors.HexColor("#b88b3a")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#f4f1ea"))
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#66706d"))
    canvas.setFont(FONT_REGULAR, 7.5)
    canvas.drawString(15 * mm, 9 * mm, "题目拆解 Skill 流程说明")
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def build_story(styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    story.append(p("题目拆解 Skill 流程说明", styles["title"]))
    story.append(
        p(
            "面向汇报口径：从原始讲义到可回看题包，再到归档测试池。重点说明每个环节为什么存在、背后调用了什么模型或技术、产出给下一环什么。",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(metric_table(styles))
    story.append(Spacer(1, 8))
    story.append(p("skill 怎么做", styles["h2"]))
    story.append(Spacer(1, 4))
    story.append(skill_cards(styles))

    story.append(PageBreak())
    story.append(p("一张图看完整链路", styles["h2"]))
    story.append(
        p(
            "上半段偏确定性工程：保真渲染、锚点识别、裁题归属。下半段才进入视觉模型：模型看图转结构，随后由规则做质量门控。",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(SkillFlow(240 * mm, 130 * mm, styles))

    rows_a = [
        (
            "01 接收材料",
            "讲义来源可能是 PDF、图片页、已切题包；文本层常常乱码或缺公式，不能直接信。",
            "统一登记来源，保留原始文件路径、页码、题目编号和可回看证据。",
            "文件读取；已有 split/manifest 兼容；不调用模型。",
            "原始材料清单和待处理入口。",
        ),
        (
            "02 页面还原",
            "数学题里公式、图形、手写批注都依赖版面，单独抽文字会丢信息。",
            "把 PDF 每页渲染成整页图片，页面图像作为源头证据；文字层只做辅助定位。",
            "PyMuPDF 页面渲染；PDF text layer；RapidOCR 作为可选回退。",
            "整页 PNG、候选文字行、页面级证据。",
        ),
        (
            "03 组件识别",
            "讲义不是只有题目，还有课程目标、知识梳理、例题讲解、强化训练等模块。",
            "按学段和讲义样式识别章节、考点、蓝色挂件、标题行和题号。",
            "profile 路由；颜色/版式规则；标题正则；OCR/PDF 行合并。",
            "组件边界、题目候选起点、模块归属。",
        ),
        (
            "04 题块切分",
            "一题可能跨页，图可能在题干或解析里，不能只按题号粗切。",
            "从当前题起点切到下一题或下一模块边界；跨页自动拼接；保留整题长图。",
            "坐标裁剪；跨页拼接规则；PIL 图片处理；contact sheet 预览。",
            "question_crops、题目 JSON、Excel、切题预览图。",
        ),
        (
            "05 图文准备",
            "选择题选项经常是字母和图片交错，必须知道哪张图属于哪个选项。",
            "判断是否需要选项识别，定位选项图、题干图、解析图，并生成可挂载资产。",
            "本地选项门控；统一调用 doubao-seed-2-0-lite 做选项锚点；bbox 审计。",
            "带图片挂载线索的 source JSON。",
        ),
    ]

    rows_b = [
        (
            "06 视觉转录",
            "目标不是 OCR 全文，而是把一整道题看懂后拆成题干、答案、解析等字段。",
            "把整题图、题干图、解析图和辅助提示送入视觉模型，要求输出结构化 JSON。",
            "doubao-seed-2-0-lite；YAML 提示词；Markdown + LaTeX 输出约束。",
            "visual_transcription_results.json。",
        ),
        (
            "07 响应修复",
            "模型返回可能有 JSON 包裹、LaTeX 反斜杠、换行转义等格式问题。",
            "提取 JSON 主体，修复 LaTeX 控制字符，保留原始字段和展示字段。",
            "JSON repair；LaTeX prefix restore；字段边界清洗。",
            "可被程序稳定读取的标准转录结果。",
        ),
        (
            "08 结构归一",
            "入库需要固定结构，不能是一坨混合文本。",
            "把题干、选项、答案、解析、图片资产映射成 content_blocks 和 options。",
            "question_visual_structure 合约；字段映射；图片 display_ref。",
            "结构化题目对象，可直接进入题库或回看页。",
        ),
        (
            "09 质量门控",
            "要能解释哪些题可直接入库、哪些题需要复核，不能靠主观感觉。",
            "检查公式前缀、方程组版式、比较符号、几何证明密度、字段边界等风险。",
            "risk span 检测；quality gate；allow / allow_with_review / block。",
            "入库建议、复核原因和可追溯证据。",
        ),
        (
            "10 交付输出",
            "领导和老师需要看结果，不需要看中间代码。",
            "生成 Excel、JSON、HTML/PDF 回看页和资产包；保留原图与模型输出对照。",
            "assetize_question_images；review HTML；严格评估和人工复判表。",
            "可展示、可复核、可入库的题包。",
        ),
    ]

    story.append(PageBreak())
    story.append(p("环节拆解：前半段先把题切准", styles["h2"]))
    story.append(p("这一段尽量不用模型做决定，核心是把原始讲义还原成稳定、可复查的题目切片。", styles["subtitle"]))
    story.append(Spacer(1, 8))
    story.append(detail_table(rows_a, styles))

    story.append(PageBreak())
    story.append(p("环节拆解：后半段再让模型看题", styles["h2"]))
    story.append(p("模型负责把题图读成结构化内容；格式归一、挂图、风险检测和入库口径由规则层兜底。", styles["subtitle"]))
    story.append(Spacer(1, 8))
    story.append(detail_table(rows_b, styles))

    story.append(PageBreak())
    story.append(p("对外怎么解释", styles["h2"]))
    callouts = [
        (
            "一句话版本",
            "我们不是把 PDF 文字直接抄出来，而是先按页面版面还原题目，再让视觉模型看整题，最后用规则检查能否入库。",
        ),
        (
            "模型具体做什么",
            "统一使用 doubao-seed-2-0-lite 从题图中读出题干、答案、解析和公式；规则层负责边界、挂图和最终入库口径。",
        ),
        (
            "规则具体做什么",
            "规则层负责切题边界、跨页拼接、图片挂载、公式/版式风险提示和质量门控，保证每一步能回看、能解释。",
        ),
        (
            "当前数据口径",
            "200题测试口径为 197 题可直接入库、3 题需人工复核，转录成功率 98.5%；5题对照组按两组共 10 题合并统计，只展示 5 个代表样例。",
        ),
        (
            "展示层问题",
            "HTML/PDF 里不等号、∉、方程组换行等属于 MathJax/展示层后处理问题，不等同于模型转录失败，也不计入人工复核。",
        ),
        (
            "为什么适合阶段汇报",
            "每个阶段都有输入、处理、输出和证据：能展示进度，也能解释风险在哪里、下一步优化什么。",
        ),
    ]
    story.append(callout_grid(callouts, styles))
    story.append(Spacer(1, 10))
    story.append(
        KeepTogether(
            [
                p("当前可交付物", styles["h2"]),
                p(
                    "teacher_visual_question_split_v0.2.xlsx / json / md：切题结果；component 和 question contact sheet：切题回看；visual_transcription_results.json：模型转录结果；question_asset_manifest_v0.1.json 和 question_asset_review.html：图文资产挂载与回看；外化 HTML/PDF：给汇报和验收使用。",
                    styles["body"],
                ),
            ]
        )
    )
    return story


def main() -> None:
    register_fonts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT_PDF),
        pagesize=landscape(A4),
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=15 * mm,
        title="题目拆解 Skill 流程说明",
        author="Codex",
    )
    styles = make_styles()
    doc.build(build_story(styles), onFirstPage=on_page, onLaterPages=on_page)
    print(OUT_PDF)


if __name__ == "__main__":
    main()
