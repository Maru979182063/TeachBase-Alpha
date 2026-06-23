# Purpose:
# - Renders DOCX flow outputs into image cards and review galleries for visual QA.
# - It exists to make Word-based deliverables reviewable with the same visual rhythm as PDF flows.

from __future__ import annotations

import html
import json
import os
import textwrap
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def paragraph_image_map(docx_path: Path, media_dir: Path) -> dict[int, list[Path]]:
    media_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx_path) as zf:
        rel_root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        rels = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root
            if rel.attrib.get("Target", "").startswith("media/")
        }

        root = ET.fromstring(zf.read("word/document.xml"))
        body = root.find("w:body", NS)
        result: dict[int, list[Path]] = {}
        paragraph_idx = 0
        for node in body.iter():
            if node.tag != f"{{{NS['w']}}}p":
                continue
            paths: list[Path] = []
            for blip in node.findall(".//a:blip", NS):
                rid = blip.attrib.get(f"{{{NS['r']}}}embed")
                target = rels.get(rid or "")
                if not target:
                    continue
                zip_name = "word/" + target
                suffix = Path(target).suffix.lower() or ".png"
                out_path = media_dir / f"p{paragraph_idx:04d}_{len(paths)+1:02d}{suffix}"
                if not out_path.exists():
                    out_path.write_bytes(zf.read(zip_name))
                paths.append(out_path)
            if paths:
                result[paragraph_idx] = paths
            paragraph_idx += 1
        return result


def wrap_cjk_text(text: str, width: int) -> list[str]:
    text = text.replace("\n", " ")
    return textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False)


def make_card(record: dict, image_paths: list[Path], out_path: Path) -> None:
    w, h = 760, 540
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    title_font = load_font(24)
    body_font = load_font(18)
    small_font = load_font(15)
    border_color = (51, 103, 214) if image_paths else (140, 140, 140)

    draw.rectangle([0, 0, w - 1, h - 1], outline=border_color, width=4)
    draw.rectangle([0, 0, w, 48], fill=(235, 242, 255) if image_paths else (245, 245, 245))
    draw.text((16, 10), f"Q{record['question_number']}  {record['section_title'][:28]}", font=title_font, fill=(20, 45, 90))
    draw.text((16, 55), f"绑定：{record['bind_status']}  图片：{len(image_paths)}", font=small_font, fill=(80, 80, 80))

    y = 84
    qtext = record["student_question"].replace("\n", " ")
    for line in wrap_cjk_text(qtext, 42)[:9]:
        draw.text((18, y), line, font=body_font, fill=(20, 20, 20))
        y += 28

    if image_paths:
        x = 18
        y = max(y + 8, 350)
        for path in image_paths[:4]:
            try:
                pic = Image.open(path).convert("RGB")
                pic.thumbnail((170, 145))
                draw.rectangle([x - 2, y - 2, x + pic.width + 2, y + pic.height + 2], outline=(190, 190, 190))
                img.paste(pic, (x, y))
                x += 185
            except Exception:
                draw.text((x, y), f"[image error] {path.name}", font=small_font, fill=(180, 0, 0))
                x += 185
    else:
        draw.text((18, 475), "未检测到内嵌图片", font=small_font, fill=(130, 130, 130))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=92)


def contact_sheets(card_paths: list[Path], out_dir: Path) -> list[Path]:
    sheets = []
    cards_per_sheet = 12
    for sheet_idx in range(0, len(card_paths), cards_per_sheet):
        batch = card_paths[sheet_idx : sheet_idx + cards_per_sheet]
        thumbs = []
        for p in batch:
            im = Image.open(p).convert("RGB")
            im.thumbnail((380, 270))
            canvas = Image.new("RGB", (400, 300), "white")
            canvas.paste(im, ((400 - im.width) // 2, (300 - im.height) // 2))
            thumbs.append(canvas)
        cols = 3
        rows = 4
        sheet = Image.new("RGB", (cols * 400, rows * 300), (245, 245, 245))
        for idx, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((idx % cols) * 400, (idx // cols) * 300))
        out_path = out_dir / f"word_visual_review_sheet_{sheet_idx // cards_per_sheet + 1:02d}.jpg"
        sheet.save(out_path, quality=92)
        sheets.append(out_path)
    return sheets


def write_html(records: list[dict], q_images: dict[int, list[Path]], out_path: Path) -> None:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Word视觉复查</title>",
        "<style>body{font-family:'Microsoft YaHei',Arial,sans-serif;margin:24px;background:#f5f7fb;color:#172033;}"
        ".q{background:white;border:1px solid #d8e0ef;border-radius:8px;margin:0 0 18px;padding:16px;}"
        ".meta{color:#53627a;font-size:13px;margin-bottom:8px}.imgs{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}"
        "img{max-width:220px;max-height:160px;border:1px solid #cfd6e3;background:white;padding:4px}"
        "pre{white-space:pre-wrap;font-family:inherit;line-height:1.55}</style></head><body>",
        "<h1>Word题包视觉复查 v0.1</h1>",
        "<p>说明：此预览直接来自 docx 段落流和原始内嵌 PNG，用于检查题号绑定、题图归属和明显丢图；不是最终页面坐标。</p>",
    ]
    for r in records:
        qn = r["question_number"]
        parts.append("<div class='q'>")
        parts.append(f"<h2>Q{qn} {html.escape(r['section_title'])}</h2>")
        parts.append(f"<div class='meta'>绑定：{r['bind_status']} | 图片：{len(q_images.get(qn, []))}</div>")
        parts.append(f"<pre>{html.escape(r['student_question'])}</pre>")
        if q_images.get(qn):
            parts.append("<div class='imgs'>")
            for img_path in q_images[qn]:
                rel = os.path.relpath(img_path, out_path.parent).replace("\\", "/")
                parts.append(f"<img src='{html.escape(rel)}'>")
            parts.append("</div>")
        parts.append("</div>")
    parts.append("</body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    docx_path = Path(os.environ["DOC_STU"])
    bound_json = Path.cwd() / "outputs" / "ingress_splitter_v0.1" / "docx_pair_bind" / "docx_pair_bound_questions.json"
    out_dir = Path.cwd() / "outputs" / "ingress_splitter_v0.1" / "docx_visual_review"
    media_dir = out_dir / "media"
    cards_dir = out_dir / "cards"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(bound_json.read_text(encoding="utf-8"))
    records = data["questions"]
    p_images = paragraph_image_map(docx_path, media_dir)

    q_images: dict[int, list[Path]] = {}
    for r in records:
        images: list[Path] = []
        for pidx in r["student_paragraph_indexes"]:
            images.extend(p_images.get(pidx, []))
        q_images[r["question_number"]] = images

    card_paths = []
    for r in records:
        card_path = cards_dir / f"q{r['question_number']:03d}.jpg"
        make_card(r, q_images[r["question_number"]], card_path)
        card_paths.append(card_path)

    sheets = contact_sheets(card_paths, out_dir)
    html_path = out_dir / "word_visual_review.html"
    write_html(records, q_images, html_path)

    summary = {
        "question_count": len(records),
        "questions_with_images": sum(1 for v in q_images.values() if v),
        "total_bound_images": sum(len(v) for v in q_images.values()),
        "sheets": [str(p) for p in sheets],
        "html": str(html_path),
        "note": "Flow preview from DOCX paragraphs and embedded PNGs; fixed-page Word rendering still pending.",
    }
    (out_dir / "word_visual_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
