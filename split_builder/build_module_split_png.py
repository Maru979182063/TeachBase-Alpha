import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path("outputs") / "module_splitter"
OUT = ROOT / "module_split_overview.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


F_TITLE = font(34, True)
F_H2 = font(24, True)
F_BODY = font(18)
F_SMALL = font(15)
F_BADGE = font(14, True)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, fnt: ImageFont.ImageFont) -> list[str]:
    lines = []
    current = ""
    for char in text:
        trial = current + char
        if draw.textlength(trial, font=fnt) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def badge(draw, xy, text, fill, outline, text_fill):
    x, y = xy
    w = int(draw.textlength(text, font=F_BADGE)) + 22
    h = 28
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=fill, outline=outline)
    draw.text((x + 11, y + 4), text, font=F_BADGE, fill=text_fill)
    return w + 8


def main() -> None:
    docs = []
    for p in sorted(ROOT.rglob("module_split.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        docs.append(data)

    width = 1500
    y = 36
    card_heights = []
    tmp = Image.new("RGB", (width, 2000), "#eef2f7")
    draw = ImageDraw.Draw(tmp)
    for data in docs:
        h = 230 + min(len(data["nodes"]), 9) * 42 + min(len(data["tasks"]), 8) * 32
        card_heights.append(h)
    height = y + 80 + sum(card_heights) + len(docs) * 26 + 40
    img = Image.new("RGB", (width, height), "#eef2f7")
    draw = ImageDraw.Draw(img)

    draw.text((42, y), "讲义模块拆分结果总览", font=F_TITLE, fill="#172033")
    y += 48
    draw.text((42, y), "只展示结构拆分与题块边界，不代表已经完成分层组装或全量视觉验收。", font=F_BODY, fill="#53627a")
    y += 38

    for data, card_h in zip(docs, card_heights):
        q = data["quality"]
        x = 42
        draw.rounded_rectangle([x, y, width - 42, y + card_h], radius=18, fill="white", outline="#d7dfeb")
        cy = y + 24
        draw.text((x + 24, cy), f"{data['source']['subject']} | {data['lesson']['title']}", font=F_H2, fill="#172033")

        risks = q.get("risk_flags", [])
        if "ocr_required" in risks:
            judgment = "需要 OCR/视觉通道，当前不是可拆文本零件"
            tone = ("#fff1f2", "#fecdd3", "#be123c")
        elif data["source"]["subject"] == "生物" and q["task_count"] == 0:
            judgment = "知识模块可用，题块零件未完成"
            tone = ("#fff7ed", "#fed7aa", "#b45309")
        else:
            judgment = "模块/题块零件基本可用，需抽样视觉复核"
            tone = ("#ecfdf5", "#b7ebd1", "#067647")
        badge(draw, (width - 42 - 430, cy + 2), judgment, *tone)
        cy += 48

        stats = [
            ("页数", q["page_count"]),
            ("模块", q["node_count"]),
            ("题块", q["task_count"]),
            ("答案解析绑定", q["answer_bound_task_count"]),
        ]
        sx = x + 24
        for label, value in stats:
            draw.rounded_rectangle([sx, cy, sx + 178, cy + 64], radius=12, fill="#f7f9fc", outline="#e2e8f2")
            draw.text((sx + 16, cy + 9), str(value), font=F_H2, fill="#172033")
            draw.text((sx + 16, cy + 38), label, font=F_SMALL, fill="#60708a")
            sx += 194
        cy += 82

        draw.text((x + 24, cy), "结构树", font=F_BODY, fill="#172033")
        cy += 30
        for node in data["nodes"][:9]:
            indent = 0 if node["parent_id"] is None else 24
            draw.text((x + 28 + indent, cy), f"{node['phase']}  p{node['page_start']}-{node['page_end']}", font=F_SMALL, fill="#60708a")
            title = node["title"]
            for line in wrap_text(draw, title, 650 - indent, F_BODY)[:1]:
                draw.text((x + 300 + indent, cy - 2), line, font=F_BODY, fill="#172033")
            cy += 42
        if not data["nodes"]:
            draw.text((x + 28, cy), "没有可抽取文本结构，需先 OCR。", font=F_BODY, fill="#8a98ad")
            cy += 38

        draw.text((x + 830, y + 154), "题块样例", font=F_BODY, fill="#172033")
        ty = y + 184
        for task in data["tasks"][:8]:
            state = "已绑定" if task["answer"] or task["explanation"] else "待复核"
            color = "#067647" if state == "已绑定" else "#b45309"
            draw.text((x + 830, ty), f"{task['task_id']} | p{task['page_start']}-{task['page_end']} | {state}", font=F_SMALL, fill=color)
            title = task["title"].replace("\n", " ")
            lines = wrap_text(draw, title, 560, F_SMALL)
            if lines:
                draw.text((x + 830, ty + 20), lines[0], font=F_SMALL, fill="#334155")
            ty += 56
        if not data["tasks"]:
            draw.text((x + 830, ty), "暂无题块。", font=F_BODY, fill="#8a98ad")

        y += card_h + 26

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
