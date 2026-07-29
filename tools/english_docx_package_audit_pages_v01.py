#!/usr/bin/env python3
"""Package English DOCX audit HTML pages with local image assets."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse


IMG_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=")(file:///[^"]+)(")', re.IGNORECASE)


def file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"not a file URI: {uri}")
    value = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", value):
        value = value[1:]
    return Path(value)


def unique_asset_name(source: Path, used: set[str]) -> str:
    stem = source.stem or "asset"
    suffix = source.suffix or ".bin"
    candidate = source.name
    index = 2
    while candidate.lower() in used:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used.add(candidate.lower())
    return candidate


def package_pages(input_dir: Path, output_dir: Path, package_name: str) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    copied_assets: dict[str, str] = {}
    html_files: list[str] = []

    for source_html in sorted(input_dir.glob("*.html")):
        html = source_html.read_text(encoding="utf-8")

        def replace_img(match: re.Match[str]) -> str:
            uri = match.group(2)
            if uri not in copied_assets:
                source_asset = file_uri_to_path(uri)
                asset_name = unique_asset_name(source_asset, used_names)
                shutil.copy2(source_asset, assets_dir / asset_name)
                copied_assets[uri] = f"assets/{asset_name}"
            return f"{match.group(1)}{copied_assets[uri]}{match.group(3)}"

        html = IMG_SRC_RE.sub(replace_img, html)
        target_html = output_dir / source_html.name
        target_html.write_text(html, encoding="utf-8")
        html_files.append(source_html.name)

    readme = "\n".join(
        [
            "# English DOCX Audit Pages",
            "",
            "Open the HTML files directly in a browser.",
            "",
            "Included pages:",
            *[f"- {name}" for name in html_files],
            "",
            f"Bundled image assets: {len(copied_assets)}",
            "",
        ]
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    manifest = {
        "schema_version": "english_docx_audit_page_package.v0.1",
        "source_dir": str(input_dir),
        "html_files": html_files,
        "asset_count": len(copied_assets),
        "assets": sorted(set(copied_assets.values())),
    }
    (output_dir / "package_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    zip_path = output_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(output_dir.parent))

    return {
        "output_dir": str(output_dir),
        "zip_path": str(zip_path),
        "html_count": len(html_files),
        "asset_count": len(copied_assets),
        "zip_bytes": zip_path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--package-name", default="")
    args = parser.parse_args()
    result = package_pages(args.input_dir, args.output_dir, args.package_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
