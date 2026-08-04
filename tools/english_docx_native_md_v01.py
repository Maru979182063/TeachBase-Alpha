from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import struct
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "outputs" / "english_docx_native_md_v0_1"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "o": "urn:schemas-microsoft-com:office:office",
}


def qn(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def lname(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def safe_slug(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return (cleaned or "docx")[:limit]


def image_metadata(data: bytes, filename: str) -> dict[str, Any]:
    ext = Path(filename).suffix.lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "wmf": "image/wmf",
        "emf": "image/emf",
    }.get(ext, "application/octet-stream")
    width: int | None = None
    height: int | None = None
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            width, height = struct.unpack(">II", data[16:24])
        elif data.startswith(b"GIF") and len(data) >= 10:
            width, height = struct.unpack("<HH", data[6:10])
        elif data.startswith(b"BM") and len(data) >= 26:
            width, height = struct.unpack("<ii", data[18:26])
        elif data.startswith(b"\xff\xd8"):
            pos = 2
            while pos + 9 < len(data):
                if data[pos] != 0xFF:
                    pos += 1
                    continue
                marker = data[pos + 1]
                pos += 2
                if marker in {0xD8, 0xD9}:
                    continue
                if pos + 2 > len(data):
                    break
                size = struct.unpack(">H", data[pos : pos + 2])[0]
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and pos + 7 <= len(data):
                    height, width = struct.unpack(">HH", data[pos + 3 : pos + 7])
                    break
                pos += size
    except Exception:
        width = None
        height = None
    return {
        "format": ext or "unknown",
        "mime_type": mime,
        "sha256": hashlib.sha256(data).hexdigest(),
        "width_px": width,
        "height_px": height,
        "has_dimensions": width is not None and height is not None,
    }


EMU_PER_INCH = 914400


def emu_to_inches(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / EMU_PER_INCH, 4)


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_relationships(zf: zipfile.ZipFile) -> dict[str, str]:
    path = "word/_rels/document.xml.rels"
    if path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(path))
    rels: dict[str, str] = {}
    for rel in root.findall("rel:Relationship", NS):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if not rid or not target:
            continue
        normalized = target.replace("\\", "/")
        if normalized.startswith("/"):
            rels[rid] = normalized.lstrip("/")
        elif normalized.startswith("word/"):
            rels[rid] = normalized
        else:
            rels[rid] = "word/" + normalized
    return rels


def body_media_targets(root: ET.Element, rels: dict[str, str]) -> set[str]:
    body = root.find("w:body", NS)
    if body is None:
        return set()
    targets: set[str] = set()
    for blip in body.findall(".//a:blip", NS):
        rid = blip.attrib.get(qn("r", "embed")) or blip.attrib.get(qn("r", "link"))
        target = rels.get(rid or "")
        if target:
            targets.add(target)
    return targets


def extract_media(docx_path: Path, out_dir: Path, allowed_zip_paths: set[str]) -> dict[str, dict[str, Any]]:
    media_dir = out_dir / "word_media_native"
    media_dir.mkdir(parents=True, exist_ok=True)
    media: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(docx_path) as zf:
        for zip_name in zf.namelist():
            if not zip_name.startswith("word/media/") or zip_name.endswith("/"):
                continue
            if zip_name not in allowed_zip_paths:
                continue
            asset_id = f"docx_media_{len(media) + 1:04d}"
            target = media_dir / Path(zip_name).name
            data = zf.read(zip_name)
            target.write_bytes(data)
            media[zip_name] = {
                "asset_id": asset_id,
                "zip_path": zip_name,
                "filename": target.name,
                "storage_key": safe_rel(target),
                "preview_src": "word_media_native/" + target.name,
                "bytes": target.stat().st_size,
                **image_metadata(data, target.name),
            }
    return media


def run_is_underlined(run: ET.Element) -> bool:
    underline = run.find("w:rPr/w:u", NS)
    if underline is None:
        return False
    return underline.attrib.get(qn("w", "val"), "") != "none"


def direct_run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for child in list(run):
        name = lname(child)
        if name == "t" and child.text:
            parts.append(child.text)
        elif name == "tab":
            parts.append("\t")
        elif name == "br":
            parts.append("\n")
    return "".join(parts)


def nested_run_text(run: ET.Element) -> str:
    return "".join(node.text or "" for node in run.findall(".//w:t", NS))


def run_text(run: ET.Element) -> str:
    return direct_run_text(run) or nested_run_text(run)


def underline_token(text: str, blank_counter: list[int]) -> dict[str, Any]:
    stripped = text.strip()
    if re.fullmatch(r"\d{1,3}", stripped):
        blank_counter[0] += 1
        label = stripped
        return {
            "type": "blank",
            "markdown": f"[[BLANK_{label}]]",
            "source_text": text,
            "blank_label": label,
            "blank_index": blank_counter[0],
            "source_format": {"underline": True},
        }
    if not stripped:
        blank_counter[0] += 1
        return {
            "type": "blank",
            "markdown": f"[[BLANK_UNLABELED_{blank_counter[0]:03d}]]",
            "source_text": text,
            "blank_label": "",
            "blank_index": blank_counter[0],
            "source_format": {"underline": True},
        }
    return {
        "type": "underline_text",
        "markdown": f"<u>{html.escape(text)}</u>",
        "source_text": text,
        "source_format": {"underline": True},
    }


def response_area_tokens(text: str, counter: list[int]) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    pos = 0
    for match in re.finditer(r"_{20,}", text):
        if match.start() > pos:
            tokens.append({"type": "text", "markdown": text[pos : match.start()]})
        counter[0] += 1
        tokens.append(
            {
                "type": "response_area",
                "markdown": f"[[RESPONSE_AREA_{counter[0]:03d} chars={match.end() - match.start()}]]",
                "source_text": match.group(0),
                "char_count": match.end() - match.start(),
                "response_area_index": counter[0],
            }
        )
        pos = match.end()
    if pos < len(text):
        tokens.append({"type": "text", "markdown": text[pos:]})
    return tokens


def serialize_run(run: ET.Element, blank_counter: list[int], response_counter: list[int]) -> list[dict[str, Any]]:
    text = run_text(run)
    tokens: list[dict[str, Any]] = []
    if text:
        if run_is_underlined(run):
            tokens.append(underline_token(text, blank_counter))
        else:
            tokens.extend(response_area_tokens(text, response_counter))
    return tokens


def collect_image_refs(el: ET.Element, rels: dict[str, str], media: dict[str, dict[str, Any]], counter: list[int]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    mode = "anchor" if el.findall(".//wp:anchor", NS) else "inline"
    for blip in el.findall(".//a:blip", NS):
        rid = blip.attrib.get(qn("r", "embed")) or blip.attrib.get(qn("r", "link"))
        asset = media.get(rels.get(rid or "", ""))
        if not asset:
            continue
        extent = None
        for candidate in el.findall(".//wp:inline/wp:extent", NS) + el.findall(".//wp:anchor/wp:extent", NS):
            extent = candidate
            break
        cx_emu = parse_int(extent.attrib.get("cx")) if extent is not None else None
        cy_emu = parse_int(extent.attrib.get("cy")) if extent is not None else None
        counter[0] += 1
        refs.append(
            {
                "image_ref_id": f"img_ref_{counter[0]:04d}",
                "asset_id": asset["asset_id"],
                "mode": mode,
                "placement": mode,
                "wp_extent_emu": {"cx": cx_emu, "cy": cy_emu} if cx_emu is not None or cy_emu is not None else {},
                "display_width_in": emu_to_inches(cx_emu),
                "display_height_in": emu_to_inches(cy_emu),
                "storage_key": asset["storage_key"],
                "filename": asset.get("filename", ""),
                "format": asset.get("format", ""),
                "mime_type": asset.get("mime_type", ""),
                "bytes": asset.get("bytes", 0),
                "sha256": asset.get("sha256", ""),
                "width_px": asset.get("width_px"),
                "height_px": asset.get("height_px"),
            }
        )
    return refs


def tokens_to_markdown(tokens: list[dict[str, Any]]) -> str:
    return "".join(str(token.get("markdown") or "") for token in tokens).strip()


def plain_text_from_tokens(tokens: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for token in tokens:
        if token.get("type") == "image":
            continue
        parts.append(str(token.get("source_text") if "source_text" in token else token.get("markdown") or ""))
    return "".join(parts).strip()


def serialize_paragraph(
    paragraph: ET.Element,
    rels: dict[str, str],
    media: dict[str, dict[str, Any]],
    image_counter: list[int],
    blank_counter: list[int],
    response_counter: list[int],
) -> dict[str, Any]:
    tokens: list[dict[str, Any]] = []

    def walk(node: ET.Element) -> None:
        name = lname(node)
        if name == "r":
            tokens.extend(serialize_run(node, blank_counter, response_counter))
            for ref in collect_image_refs(node, rels, media, image_counter):
                md = f"![{ref['asset_id']}](asset://{ref['asset_id']})"
                tokens.append({"type": "image", "markdown": md, **ref})
            return
        if name in {"oMath", "oMathPara"}:
            tokens.append({"type": "unsupported_formula", "markdown": "[[UNSUPPORTED_FORMULA]]", "source_format": {"omml": True}})
            return
        for child in list(node):
            walk(child)

    walk(paragraph)
    markdown = tokens_to_markdown(tokens)
    return {
        "source_block_type": "docx_paragraph",
        "text": plain_text_from_tokens(tokens),
        "markdown": markdown,
        "tokens": tokens,
        "image_refs": [token for token in tokens if token.get("type") == "image"],
        "blank_refs": [token for token in tokens if token.get("type") == "blank"],
        "response_area_refs": [token for token in tokens if token.get("type") == "response_area"],
        "underline_text_refs": [token for token in tokens if token.get("type") == "underline_text"],
        "unsupported_formula_refs": [token for token in tokens if token.get("type") == "unsupported_formula"],
    }


def serialize_table(
    table: ET.Element,
    rels: dict[str, str],
    media: dict[str, dict[str, Any]],
    image_counter: list[int],
    blank_counter: list[int],
    response_counter: list[int],
) -> dict[str, Any]:
    rows: list[list[str]] = []
    cell_blocks: list[list[dict[str, Any]]] = []
    for row in table.findall("./w:tr", NS):
        row_text: list[str] = []
        row_blocks: list[dict[str, Any]] = []
        for cell in row.findall("./w:tc", NS):
            paras = [serialize_paragraph(p, rels, media, image_counter, blank_counter, response_counter) for p in cell.findall("./w:p", NS)]
            text = "<br>".join(p["markdown"] for p in paras if p.get("markdown"))
            row_text.append(text)
            row_blocks.append({"paragraphs": paras})
        rows.append(row_text)
        cell_blocks.append(row_blocks)
    markdown = table_to_markdown(rows)
    nested = [p for row in cell_blocks for cell in row for p in cell["paragraphs"]]
    return {
        "source_block_type": "docx_table",
        "text": markdown,
        "markdown": markdown,
        "tokens": [{"type": "table", "markdown": markdown}],
        "image_refs": [ref for p in nested for ref in p.get("image_refs", [])],
        "blank_refs": [ref for p in nested for ref in p.get("blank_refs", [])],
        "response_area_refs": [ref for p in nested for ref in p.get("response_area_refs", [])],
        "underline_text_refs": [ref for p in nested for ref in p.get("underline_text_refs", [])],
        "unsupported_formula_refs": [ref for p in nested for ref in p.get("unsupported_formula_refs", [])],
        "table_structured": {"rows": rows},
    }


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    sep = ["---"] * width
    body = normalized[1:]

    def line(cells: list[str]) -> str:
        escaped = [cell.replace("\n", "<br>").replace("|", "\\|") for cell in cells]
        return "| " + " | ".join(escaped) + " |"

    return "\n".join([line(header), line(sep), *[line(row) for row in body]])


def annotate_block_contract(block: dict[str, Any], order: int) -> dict[str, Any]:
    block_id = f"b_{order:06d}"
    block["schema_version"] = "english_docx_native_block.v0.1"
    block["block_id"] = block_id
    block["block_order"] = order
    block["paragraph_index"] = order
    block["display_markdown"] = str(block.get("markdown") or "")
    block["plain_text_lossy"] = str(block.get("text") or "")
    block["asset_refs"] = list(block.get("image_refs") or [])
    flags: list[str] = []
    if block.get("source_block_type") == "docx_table":
        flags.append("table_markdown_is_linearized")
    if block.get("blank_refs"):
        flags.append("word_underline_blanks_tokenized")
    if block.get("response_area_refs"):
        flags.append("underscore_response_areas_tokenized")
    if block.get("underline_text_refs"):
        flags.append("word_underline_text_preserved_as_html")
    if block.get("unsupported_formula_refs"):
        flags.append("unsupported_formula_marker_inserted")
    block["content_loss_flags"] = flags
    block["qa_status"] = "needs_review" if block.get("unsupported_formula_refs") else "ok"
    block["content_contract"] = {
        "canonical_markdown_field": "display_markdown",
        "plain_text_field": "plain_text_lossy",
        "plain_text_is_lossy": True,
        "asset_refs_field": "asset_refs",
        "blank_refs_field": "blank_refs",
        "response_area_refs_field": "response_area_refs",
        "loss_flags_field": "content_loss_flags",
    }
    return block


def docx_probe(docx_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(docx_path) as zf:
        names = zf.namelist()
        root = ET.fromstring(zf.read("word/document.xml"))
        return {
            "omml_elements": len(root.findall(".//m:oMath", NS)) + len(root.findall(".//m:oMathPara", NS)),
            "ole_objects": len(root.findall(".//o:OLEObject", NS)),
            "embedding_files": sum(1 for name in names if name.startswith("word/embeddings/") and not name.endswith("/")),
            "native_media": sum(1 for name in names if name.startswith("word/media/") and not name.endswith("/")),
        }


def build_document_markdown(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        markdown = str(block.get("display_markdown") or "")
        if not markdown:
            continue
        parts.append(markdown)
    return "\n\n".join(parts).rstrip() + "\n"


def render_preview(out_dir: Path, blocks: list[dict[str, Any]], assets: list[dict[str, Any]]) -> None:
    asset_by_id = {asset["asset_id"]: asset for asset in assets}

    def render_md(markdown: str) -> str:
        escaped = html.escape(markdown)
        for asset_id, asset in asset_by_id.items():
            token = html.escape(f"![{asset_id}](asset://{asset_id})")
            replacement = (
                f"<figure><img src='{html.escape(asset.get('preview_src') or '')}' alt='{html.escape(asset_id)}'>"
                f"<figcaption>{html.escape(asset_id)}</figcaption></figure>"
            )
            escaped = escaped.replace(token, replacement)
        escaped = re.sub(r"\[\[BLANK_([^\]]+)\]\]", r"<span class='blank'>BLANK_\1</span>", escaped)
        escaped = re.sub(r"\[\[RESPONSE_AREA_([^\]]+)\]\]", r"<span class='response'>RESPONSE_AREA_\1</span>", escaped)
        return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    cards = []
    for block in blocks:
        markdown = str(block.get("display_markdown") or "")
        if not markdown:
            continue
        meta = f"{block.get('block_id')} {block.get('source_block_type')} flags={','.join(block.get('content_loss_flags') or [])}"
        cards.append(f"<article><h2>{html.escape(str(block.get('block_order')))}</h2><div class='meta'>{html.escape(meta)}</div>{render_md(markdown)}</article>")
    style = (
        "body{margin:0;background:#f6f8fb;color:#172033;font-family:Arial,'Microsoft YaHei',sans-serif}"
        "main{max-width:1180px;margin:0 auto;padding:24px}"
        "article{background:#fff;border:1px solid #d8e0ec;border-radius:8px;margin:0 0 16px;padding:18px}"
        ".meta{color:#667899;margin-bottom:10px;font-size:13px}p{font-size:16px;line-height:1.7}"
        "img{max-width:820px;max-height:560px;border:1px solid #cfd8e6}"
        ".blank{display:inline-block;border-bottom:2px solid #283b58;padding:0 10px;color:#0f766e;font-weight:700}"
        ".response{display:inline-block;border:1px dashed #99a8bc;background:#f8fafc;color:#475569;padding:2px 8px;border-radius:4px}"
    )
    page = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>English DOCX Native Markdown Preview</title><style>"
        + style
        + "</style></head><body><main><h1>English DOCX Native Markdown Preview</h1>"
        + "".join(cards)
        + "</main></body></html>"
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")


def extract_stream(docx_path: Path, out_dir: Path) -> dict[str, Any]:
    image_counter = [0]
    blank_counter = [0]
    response_counter = [0]
    blocks: list[dict[str, Any]] = []
    with zipfile.ZipFile(docx_path) as zf:
        rels = parse_relationships(zf)
        root = ET.fromstring(zf.read("word/document.xml"))
    media = extract_media(docx_path, out_dir, body_media_targets(root, rels))
    body = root.find("w:body", NS)
    if body is not None:
        for child in body:
            if lname(child) == "p":
                block = serialize_paragraph(child, rels, media, image_counter, blank_counter, response_counter)
            elif lname(child) == "tbl":
                block = serialize_table(child, rels, media, image_counter, blank_counter, response_counter)
            else:
                continue
            annotate_block_contract(block, len(blocks))
            blocks.append(block)
    counts = {
        "blocks": len(blocks),
        "paragraph_blocks": sum(1 for block in blocks if block.get("source_block_type") == "docx_paragraph"),
        "table_blocks": sum(1 for block in blocks if block.get("source_block_type") == "docx_table"),
        "nonempty_blocks": sum(1 for block in blocks if str(block.get("display_markdown") or "").strip()),
        "native_media": len(media),
        "image_insertions": image_counter[0],
        "word_underline_blank_tokens": sum(len(block.get("blank_refs") or []) for block in blocks),
        "word_underline_text_tokens": sum(len(block.get("underline_text_refs") or []) for block in blocks),
        "underscore_response_area_tokens": sum(len(block.get("response_area_refs") or []) for block in blocks),
        "unsupported_formula_tokens": sum(len(block.get("unsupported_formula_refs") or []) for block in blocks),
        "needs_review_blocks": sum(1 for block in blocks if block.get("qa_status") == "needs_review"),
    }
    loss_flag_counts: dict[str, int] = {}
    for block in blocks:
        for flag in block.get("content_loss_flags", []) or []:
            loss_flag_counts[flag] = loss_flag_counts.get(flag, 0) + 1
    counts["loss_flag_counts"] = loss_flag_counts
    return {"blocks": blocks, "assets": list(media.values()), "counts": counts}


def run(args: argparse.Namespace) -> dict[str, Any]:
    docx_path = args.docx.resolve()
    out_dir = Path(args.out_root) / args.run_id / safe_slug(docx_path.stem)
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = extract_stream(docx_path, out_dir)
    blocks = extracted["blocks"]
    assets = extracted["assets"]
    block_stream = {
        "schema_version": "english_docx_native_md_block_stream.v0.1",
        "source_docx": str(docx_path),
        "counts": extracted["counts"],
        "blocks": blocks,
    }
    asset_manifest = {"schema_version": "english_docx_native_md_asset_manifest.v0.1", "assets": assets}
    write_json(out_dir / "block_stream.json", block_stream)
    write_json(out_dir / "asset_manifest.json", asset_manifest)
    (out_dir / "document.md").write_text(build_document_markdown(blocks), encoding="utf-8")
    render_preview(out_dir, blocks, assets)
    summary = {
        "schema_version": "english_docx_native_md_summary.v0.1",
        "pipeline_id": "english_docx_native_md_v01",
        "run_id": args.run_id,
        "source_docx": str(docx_path),
        "status": "needs_review" if extracted["counts"]["needs_review_blocks"] else "ok",
        "source_probe": docx_probe(docx_path),
        **extracted["counts"],
        "artifacts": {
            "out_dir": safe_rel(out_dir),
            "block_stream": safe_rel(out_dir / "block_stream.json"),
            "document_markdown": safe_rel(out_dir / "document.md"),
            "asset_manifest": safe_rel(out_dir / "asset_manifest.json"),
            "summary": safe_rel(out_dir / "summary.json"),
            "preview_html": safe_rel(out_dir / "index.html"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert English DOCX native content into source-preserving Markdown block stream.")
    parser.add_argument("--docx", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
