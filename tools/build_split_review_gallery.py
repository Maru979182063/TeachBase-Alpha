# Purpose:
# - Creates contact sheets and HTML galleries for split-review image outputs.
# - Keep presentation tweaks here instead of scattering gallery rules across extraction scripts.

from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


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


def trim_image(src: Path, dst: Path, pad: int = 18) -> None:
    img = Image.open(src).convert("RGB")
    arr = np.asarray(img)
    # Keep the blue slice label; trim only the excessive white canvas.
    nonwhite = np.any(arr < 246, axis=2)
    ys, xs = np.where(nonwhite)
    if len(xs) < 20:
        img.save(dst)
        return
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(img.width, int(xs.max()) + pad)
    y1 = min(img.height, int(ys.max()) + pad)
    img.crop((x0, y0, x1, y1)).save(dst)


def make_contact_sheet(items: list[dict], out_path: Path) -> None:
    font = load_font(18)
    thumbs = []
    for item in items:
        im = Image.open(item["trimmed_path"]).convert("RGB")
        im.thumbnail((520, 390))
        canvas = Image.new("RGB", (560, 470), "white")
        draw = ImageDraw.Draw(canvas)
        title = f"{item['question_id']} {item['checkpoint']} / {item['component_label']} {item['local_number']}"
        draw.text((12, 10), title[:38], fill=(20, 40, 80), font=font)
        canvas.paste(im, ((560 - im.width) // 2, 62))
        thumbs.append(canvas)
    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 560, rows * 470), (242, 244, 248))
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * 560, (idx // cols) * 470))
    sheet.save(out_path, quality=92)


def build_html(items: list[dict], out_path: Path, title: str) -> None:
    groups: dict[str, list[dict]] = {}
    for item in items:
        key = f"{item['checkpoint']} / {item['component_label']}"
        groups.setdefault(key, []).append(item)

    rows = []
    for group, group_items in groups.items():
        rows.append(f"<h2>{html.escape(group)}</h2>")
        rows.append('<div class="grid">')
        for item in group_items:
            rel = Path(item["trimmed_path"]).relative_to(out_path.parent).as_posix()
            rows.append(
                '<a class="card" href="{src}" target="_blank">'
                '<div class="meta"><b>{qid}</b><span>{num}</span></div>'
                '<img src="{src}" loading="lazy" />'
                "</a>".format(
                    src=html.escape(rel),
                    qid=html.escape(item["question_id"]),
                    num=html.escape(str(item["local_number"])),
                )
            )
        rows.append("</div>")

    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{html.escape(title)}</title>
<style>
body {{ margin: 0; font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f7fb; color: #172033; }}
header {{ position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid #d9dfeb; padding: 16px 24px; }}
h1 {{ margin: 0 0 4px; font-size: 22px; }}
.summary {{ color: #5c667a; font-size: 14px; }}
main {{ padding: 18px 24px 40px; }}
h2 {{ font-size: 18px; margin: 24px 0 12px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; }}
.card {{ display: block; background: #fff; border: 1px solid #dce3ef; border-radius: 8px; overflow: hidden; text-decoration: none; color: inherit; }}
.meta {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 12px; background: #eef4ff; color: #173f7a; font-size: 14px; }}
.card img {{ width: 100%; display: block; background: #fff; }}
</style>
</head>
<body>
<header><h1>{html.escape(title)}</h1><div class="summary">共 {len(items)} 道题。点击卡片可查看原尺寸裁剪图。</div></header>
<main>
{''.join(rows)}
</main>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")


def main() -> None:
    source_dir = Path(r"outputs\ingress_splitter_v0.1\skill_trial_junior_math_quad_equation_ineq_v05")
    data = json.loads((source_dir / "teacher_visual_question_split_v0.2.json").read_text(encoding="utf-8"))
    out_dir = source_dir / "review_friendly"
    crops_dir = out_dir / "trimmed_question_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for q in data["questions"]:
        src = Path(q["crop_path"])
        dst = crops_dir / src.name
        trim_image(src, dst)
        item = dict(q)
        item["trimmed_path"] = str(dst)
        items.append(item)

    make_contact_sheet(items, out_dir / "question_crops_contact_sheet_large.jpg")
    build_html(items, out_dir / "review_gallery.html", "初中数学教师讲义视觉切题审核")
    (out_dir / "review_summary.json").write_text(
        json.dumps(
            {
                "source": str(source_dir),
                "question_count": len(items),
                "gallery": str(out_dir / "review_gallery.html"),
                "large_contact_sheet": str(out_dir / "question_crops_contact_sheet_large.jpg"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(out_dir)


if __name__ == "__main__":
    main()
