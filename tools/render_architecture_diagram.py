from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "report_assets" / "brd_figures" / "figma_structure_architecture.png"


def draw_architecture() -> Path:
    width, height = 3200, 1600
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    font_regular = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 30)
    font_small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 20)
    font_section = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 28)
    font_title = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 46)
    font_title_small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 18)
    font_regular_narrow = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 24)

    outer = (90, 80, 3110, 1520)
    draw.rounded_rectangle(
        outer,
        radius=18,
        outline=(208, 208, 208),
        width=3,
        fill=(250, 250, 250),
    )

    draw.text((150, 120), "讲义加工与题目治理整体结构", font=font_title, fill=(34, 34, 34))
    draw.text(
        (150, 185),
        "用于说明资料进入、内容加工、教研判断与底层支撑之间的关系",
        font=font_title_small,
        fill=(76, 136, 214),
    )

    rows = [
        {
            "top": 280,
            "title": "资料入口层",
            "fill": (234, 250, 236),
            "outline": (181, 235, 191),
            "boxes": [
                ("标准讲义资料", 560, 102),
                ("老师补充题目", 560, 102),
                ("教师版 / 学生版配套资料", 720, 102),
            ],
        },
        {
            "top": 535,
            "title": "内容加工层",
            "fill": (239, 248, 255),
            "outline": (191, 224, 255),
            "boxes": [
                ("页面拆解", 480, 102),
                ("组件沉淀", 480, 102),
                ("结构编排", 480, 102),
                ("题目挂接", 480, 102),
            ],
        },
        {
            "top": 790,
            "title": "教研判断层",
            "fill": (247, 241, 255),
            "outline": (223, 207, 255),
            "boxes": [
                ("学科规则", 560, 102),
                ("考点映射", 560, 102),
                ("人工校核标准", 720, 102),
            ],
        },
        {
            "top": 1045,
            "title": "业务操作层",
            "fill": (255, 246, 238),
            "outline": (255, 222, 194),
            "boxes": [
                ("结构调整", 560, 102),
                ("人工校核", 560, 102),
                ("导出交付", 720, 102),
            ],
        },
        {
            "top": 1300,
            "title": "基础支撑层",
            "fill": (255, 250, 236),
            "outline": (247, 225, 171),
            "boxes": [
                ("Doubao 1.8V", 430, 102),
                ("任务调度", 430, 102),
                ("数据存储", 430, 102),
                ("文件存储", 430, 102),
                ("访问安全", 430, 102),
            ],
        },
    ]

    for row in rows:
        top = row["top"]
        band = (140, top, 3020, top + 170)
        draw.rounded_rectangle(
            band,
            radius=12,
            fill=row["fill"],
            outline=row["outline"],
            width=2,
        )
        draw.text((170, top + 18), row["title"], font=font_section, fill=(58, 58, 58))

        boxes = row["boxes"]
        gap = 40 if len(boxes) >= 5 else 60
        total_width = sum(box[1] for box in boxes) + gap * (len(boxes) - 1)
        start_x = 150 + (2870 - total_width) // 2
        cursor_x = start_x

        for label, box_width, box_height in boxes:
            rect = (cursor_x, top + 54, cursor_x + box_width, top + 54 + box_height)
            draw.rounded_rectangle(
                rect,
                radius=14,
                fill="white",
                outline=(191, 191, 191),
                width=3,
            )

            font = font_regular_narrow if len(label) >= 14 else font_regular
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            text_x = cursor_x + (box_width - text_width) / 2
            text_y = top + 54 + (box_height - text_height) / 2 - 4
            draw.text((text_x, text_y), label, font=font, fill=(45, 45, 45))

            cursor_x += box_width + gap

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH)
    return OUT_PATH


if __name__ == "__main__":
    print(draw_architecture())
