# Purpose:
# - Builds preview sheets for icon assets so downstream PDF builders can verify visual labels quickly.
# - Use this file when icon manifests or badge visuals need a fast human review step.

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(r"C:\Users\EDY\Documents\教研基建\assets\component_icons\math")
OUT = Path(r"C:\Users\EDY\Documents\教研基建\outputs\component_icon_preview")


def load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "component_icon_manifest.json").read_text(encoding="utf-8"))
    font_title = load_font(r"C:\Windows\Fonts\simhei.ttf", 24)
    font_small = load_font(r"C:\Windows\Fonts\msyh.ttc", 15)
    tiles = []

    for key, meta in manifest["components"].items():
        img = Image.open(ROOT / meta["asset"]).convert("RGBA")
        preview = ImageOps.contain(img, (420, 120), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (480, 230), "white")
        tile.paste(preview, ((480 - preview.width) // 2, 18), preview)
        draw = ImageDraw.Draw(tile)
        draw.text((18, 150), f"{meta['label']}  ({key})", fill=(16, 24, 40), font=font_title)
        draw.text(
            (18, 184),
            f"{meta['asset']} · {meta['type']} · {img.width}x{img.height}",
            fill=(102, 112, 133),
            font=font_small,
        )
        draw.rounded_rectangle((0, 0, 479, 229), radius=10, outline=(215, 222, 232), width=2)
        tiles.append(tile)

    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 480 + (cols + 1) * 18, rows * 230 + (rows + 1) * 18), (244, 247, 251))
    for index, tile in enumerate(tiles):
        x = 18 + (index % cols) * (480 + 18)
        y = 18 + (index // cols) * (230 + 18)
        sheet.paste(tile, (x, y))
    sheet.save(OUT / "math_icon_package_exploded_preview.png")
    print(OUT / "math_icon_package_exploded_preview.png")


if __name__ == "__main__":
    main()
