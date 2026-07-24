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

from docx_native_formula_providers import LegacyMtefManifestProvider, OmmlLatexProvider


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "outputs" / "docx_native_formula_token_stream_v0_1"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def qn(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def lname(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def slug_for(path: Path) -> str:
    chars: list[str] = []
    for ch in path.stem:
        if ch.isalnum():
            chars.append(ch)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return ("".join(chars).strip("_") or "docx")[:56]


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
    name = "word/_rels/document.xml.rels"
    if name not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(name))
    rels: dict[str, str] = {}
    for rel in root:
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if not rid or not target:
            continue
        if target.startswith("/"):
            rels[rid] = target.lstrip("/")
        elif target.startswith("word/"):
            rels[rid] = target
        else:
            rels[rid] = "word/" + target
    return rels


def extract_media(docx_path: Path, out_dir: Path) -> dict[str, dict[str, Any]]:
    media_dir = out_dir / "word_media_native"
    media_dir.mkdir(parents=True, exist_ok=True)
    media: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(docx_path) as zf:
        for zip_name in zf.namelist():
            if not zip_name.startswith("word/media/") or zip_name.endswith("/"):
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


def run_vert_align(run: ET.Element) -> str:
    align = run.find("w:rPr/w:vertAlign", NS)
    return align.attrib.get(qn("w", "val"), "") if align is not None else ""


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
    direct = direct_run_text(run)
    if direct:
        return direct
    return nested_run_text(run)


def serialize_run(run: ET.Element) -> tuple[str, list[dict[str, Any]]]:
    direct = direct_run_text(run)
    text = direct or nested_run_text(run)
    if not text:
        return "", []
    findings: list[dict[str, Any]] = []
    if not direct:
        findings.append({"type": "nested_run_text", "text": text})
    align = run_vert_align(run)
    if align == "superscript":
        return f"^{{{text}}}", [*findings, {"type": "run_superscript", "text": text}]
    if align == "subscript":
        return f"_{{{text}}}", [*findings, {"type": "run_subscript", "text": text}]
    return text, findings


MATH_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "αβγδεζηθικλμνξοπρστυφχψω"
    "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    "+-−﹣=<>≤≥≈≠×÷*/⋅·:.()（）[]{}|^_′″°"
    "∠△⊙⊥∥∼≌π√"
)


def is_math_char(ch: str) -> bool:
    return ch in MATH_CHARS


def split_trailing_math(text: str) -> tuple[str, str]:
    core_end = len(text.rstrip())
    suffix_space = text[core_end:]
    pos = core_end
    while pos > 0 and is_math_char(text[pos - 1]):
        pos -= 1
    return text[:pos] + suffix_space, text[pos:core_end]


def split_leading_math(text: str) -> tuple[str, str]:
    prefix_space_len = len(text) - len(text.lstrip())
    pos = prefix_space_len
    while pos < len(text) and is_math_char(text[pos]):
        pos += 1
    return text[prefix_space_len:pos], text[:prefix_space_len] + text[pos:]


def tokens_to_markdown(tokens: list[dict[str, Any]]) -> str:
    rendered: list[dict[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.get("type") not in {"omml_formula", "legacy_mtef_formula"}:
            text = str(token.get("markdown") or "")
            if text:
                rendered.append({"type": str(token.get("type")), "text": text})
            index += 1
            continue

        latex = str(token.get("latex") or "")
        if token.get("type") == "omml_formula" and rendered and rendered[-1]["type"] == "text":
            prefix, trailing = split_trailing_math(rendered[-1]["text"])
            if trailing:
                rendered[-1]["text"] = prefix
                latex = trailing + latex
        if token.get("type") == "omml_formula" and index + 1 < len(tokens) and tokens[index + 1].get("type") == "text":
            leading, rest = split_leading_math(str(tokens[index + 1].get("markdown") or ""))
            if leading:
                latex += leading
                tokens[index + 1] = {**tokens[index + 1], "markdown": rest}
        if rendered and rendered[-1]["type"] == "formula" and latex:
            rendered[-1]["text"] = rendered[-1]["text"].rstrip("$") + latex + "$"
        else:
            rendered.append({"type": "formula", "text": f"${latex}$" if latex else ""})
        index += 1
    return "".join(item["text"] for item in rendered).strip()


def formula_structural_risks(markdown: str) -> list[dict[str, Any]]:
    text = str(markdown or "")
    risks: list[dict[str, Any]] = []

    def add(code: str, match: re.Match[str], message: str, action: str) -> None:
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 120)
        risks.append(
            {
                "risk_code": code,
                "span": text[start:end],
                "match": match.group(0),
                "char_start": match.start(),
                "char_end": match.end(),
                "message": message,
                "suggested_action": action,
            }
        )

    for match in re.finditer(r"\\left(?![A-Za-z])\s*\{", text):
        add(
            "bad_left_brace_delimiter",
            match,
            r"Found \left{. KaTeX requires \left\{ or a cases/aligned environment.",
            "convert_to_cases_or_left_brace_aligned",
        )
    for match in re.finditer(r"\\right(?![A-Za-z])(?=\s*(?:\$|$|[，,。；;]))", text):
        add(
            "bad_right_missing_delimiter",
            match,
            r"Found \right without a visible delimiter.",
            "close_with_right_dot_or_convert_to_cases",
        )
    for match in re.finditer(r"\\left(?![A-Za-z])\s*\{[^$]{0,160}=[^$]{1,160}=", text):
        add(
            "possible_equation_group_flattened",
            match,
            "Multiple equations appear flattened into one inline formula.",
            "split_equations_into_cases_or_aligned_rows",
        )
    return risks


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


def image_ref_is_inline_glyph_candidate(ref: dict[str, Any]) -> bool:
    if str(ref.get("mode") or "") != "inline":
        return False
    width_in = ref.get("display_width_in")
    height_in = ref.get("display_height_in")
    if not isinstance(width_in, (int, float)) or not isinstance(height_in, (int, float)):
        return False
    if width_in <= 0 or height_in <= 0:
        return False
    if width_in > 0.35 or height_in > 0.45:
        return False
    if float(width_in) * float(height_in) > 0.08:
        return False
    if int(ref.get("bytes") or 0) > 20000:
        return False
    return True


def token_has_visible_text(token: dict[str, Any]) -> bool:
    if token.get("type") == "text":
        return bool(str(token.get("markdown") or "").strip())
    if token.get("type") in {"omml_formula", "legacy_mtef_formula"}:
        return bool(str(token.get("markdown") or token.get("latex") or "").strip())
    return False


def classify_inline_glyph_tokens(tokens: list[dict[str, Any]]) -> None:
    for index, token in enumerate(tokens):
        if token.get("type") != "image" or not image_ref_is_inline_glyph_candidate(token):
            continue
        has_left_text = any(token_has_visible_text(item) for item in tokens[:index])
        has_right_text = any(token_has_visible_text(item) for item in tokens[index + 1 :])
        if not (has_left_text and has_right_text):
            continue
        token["asset_role"] = "inline_glyph_asset"
        token["content_role"] = "text_glyph"
        token["markdown"] = str(token.get("glyph_text") or "")
        token["suppressed_from_visual_refs"] = True


def formula_refs_from_tokens(tokens: list[dict[str, Any]], block_id: str, start_index: int = 0) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    formula_index = start_index
    for token in tokens:
        if token.get("type") not in {"omml_formula", "legacy_mtef_formula"}:
            continue
        formula_index += 1
        source = "omml" if token.get("type") == "omml_formula" else "legacy_equation_mtef"
        formula_id = str(token.get("formula_id") or f"{block_id}_f_{formula_index:03d}")
        refs.append(
            {
                "formula_ref_id": formula_id,
                "source": source,
                "latex": str(token.get("latex") or ""),
                "markdown": str(token.get("markdown") or ""),
                "status": str(token.get("status") or ("omml_latex_ok" if source == "omml" else "")),
            }
        )
    return refs


def formula_refs_for_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    refs = formula_refs_from_tokens(list(block.get("tokens", []) or []), str(block.get("block_id") or ""))
    block_id = str(block.get("block_id") or "")
    formula_index = len(refs)
    for token in block.get("table_formula_tokens", []) or []:
        formula_index += 1
        source = "omml" if token.get("type") == "omml_formula" else "legacy_equation_mtef"
        formula_id = str(token.get("formula_id") or f"{block_id}_table_f_{formula_index:03d}")
        refs.append(
            {
                "formula_ref_id": formula_id,
                "source": source,
                "latex": str(token.get("latex") or ""),
                "markdown": str(token.get("markdown") or ""),
                "status": str(token.get("status") or ("omml_latex_ok" if source == "omml" else "")),
                "table_row": token.get("table_row"),
                "table_col": token.get("table_col"),
                "cell_paragraph_index": token.get("cell_paragraph_index"),
            }
        )
    for finding in block.get("formula_findings", []) or []:
        if finding.get("type") not in {"run_superscript", "run_subscript"}:
            continue
        formula_index += 1
        refs.append(
            {
                "formula_ref_id": f"{block_id}_run_{formula_index:03d}",
                "source": "word_run_vert_align",
                "latex": "",
                "markdown": "",
                "status": str(finding.get("type")),
                "text": str(finding.get("text") or ""),
            }
        )
    return refs


def loss_flags_for_block(block: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    markdown = str(block.get("markdown") or "")
    plain = str(block.get("text") or "")
    if markdown and plain and markdown != plain and "$" in markdown:
        flags.append("plain_text_loses_formula_markup")
    if block.get("source_block_type") == "docx_table":
        flags.append("table_markdown_is_linearized")
        table = block.get("table_structured") or {}
        if not table.get("rows"):
            flags.append("table_structure_missing")
    if block.get("formula_count") and "$" not in markdown:
        flags.append("formula_count_without_display_formula")
    if block.get("formula_structural_risks"):
        flags.append("formula_structural_risk")
    for finding in block.get("formula_findings", []) or []:
        if finding.get("type") == "legacy_mtef_formula" and not finding.get("has_latex"):
            flags.append("legacy_mtef_missing_latex")
            break
    if block.get("image_refs") and not plain and not markdown.replace(" ", ""):
        flags.append("image_only_block_needs_role_classification")
    if block.get("inline_glyph_refs"):
        flags.append("inline_glyph_asset_suppressed_from_visual_refs")
    return flags


def annotate_block_contract(block: dict[str, Any], order: int) -> dict[str, Any]:
    block_id = f"b_{order:06d}"
    block["schema_version"] = "docx_native_block.v0.2"
    block["block_id"] = block_id
    block["block_order"] = order
    block["display_markdown"] = str(block.get("markdown") or "")
    block["plain_text_lossy"] = str(block.get("text") or "")
    block["asset_refs"] = list(block.get("image_refs") or [])
    block["formula_refs"] = formula_refs_for_block(block)
    block["formula_structural_risks"] = formula_structural_risks(block["display_markdown"])
    block["content_loss_flags"] = loss_flags_for_block(block)
    serious = {
        "formula_count_without_display_formula",
        "legacy_mtef_missing_latex",
        "table_structure_missing",
        "formula_structural_risk",
    }
    block["qa_status"] = "needs_review" if serious.intersection(block["content_loss_flags"]) else "ok"
    block["content_contract"] = {
        "canonical_markdown_field": "display_markdown",
        "plain_text_field": "plain_text_lossy",
        "plain_text_is_lossy": True,
        "asset_refs_field": "asset_refs",
        "formula_refs_field": "formula_refs",
        "loss_flags_field": "content_loss_flags",
    }
    return block


def serialize_paragraph(
    p: ET.Element,
    rels: dict[str, str],
    media: dict[str, dict[str, Any]],
    image_counter: list[int],
    omml_provider: OmmlLatexProvider,
    mtef_provider: LegacyMtefManifestProvider,
) -> dict[str, Any]:
    tokens: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    formula_count = 0

    def walk(node: ET.Element) -> None:
        nonlocal formula_count
        name = lname(node)
        if name == "r":
            mtef_token = mtef_provider.token_for_run(node)
            if mtef_token is not None:
                formula_count += 1
                if mtef_token.markdown:
                    tokens.append(
                        {
                            "type": "legacy_mtef_formula",
                            "formula_id": mtef_token.formula_id,
                            "latex": mtef_token.latex,
                            "markdown": mtef_token.markdown,
                            "status": mtef_token.status,
                        }
                    )
                findings.append(
                    {
                        "type": "legacy_mtef_formula",
                        "formula_id": mtef_token.formula_id,
                        "status": mtef_token.status,
                        "has_latex": bool(mtef_token.latex),
                    }
                )
            text, run_findings = serialize_run(node)
            if text:
                tokens.append({"type": "text", "markdown": text})
            findings.extend(run_findings)
            refs = collect_image_refs(node, rels, media, image_counter)
            for ref in refs:
                md = f"![{ref['asset_id']}](asset://{ref['asset_id']})"
                tokens.append({"type": "image", "markdown": md, **ref})
            return
        if name in {"oMath", "oMathPara"}:
            formula_count += 1
            formula_token = omml_provider.token(node)
            latex = formula_token.latex
            md = f"${latex}$" if latex else ""
            if md:
                tokens.append({"type": "omml_formula", "latex": latex, "markdown": md})
            findings.append({"type": "omml_formula", "latex": latex, "has_sqrt": "\\sqrt" in latex, "has_power": "^{" in latex, "has_frac": "\\frac" in latex})
            return
        for child in list(node):
            walk(child)

    def collect_plain_text(node: ET.Element) -> str:
        name = lname(node)
        if name == "r":
            return run_text(node)
        if name in {"oMath", "oMathPara"}:
            return ""
        return "".join(collect_plain_text(child) for child in list(node))

    walk(p)
    classify_inline_glyph_tokens(tokens)
    plain = collect_plain_text(p).strip()
    markdown = tokens_to_markdown(tokens)
    return {
        "source_block_type": "docx_paragraph",
        "text": plain,
        "markdown": markdown,
        "tokens": tokens,
        "formula_count": formula_count,
        "formula_findings": findings,
        "image_refs": [
            token
            for token in tokens
            if token.get("type") == "image" and token.get("asset_role") != "inline_glyph_asset"
        ],
        "inline_glyph_refs": [
            token
            for token in tokens
            if token.get("type") == "image" and token.get("asset_role") == "inline_glyph_asset"
        ],
    }


def serialize_table(
    tbl: ET.Element,
    rels: dict[str, str],
    media: dict[str, dict[str, Any]],
    image_counter: list[int],
    omml_provider: OmmlLatexProvider,
    mtef_provider: LegacyMtefManifestProvider,
) -> dict[str, Any]:
    rows: list[list[str]] = []
    cell_blocks: list[list[dict[str, Any]]] = []
    table_formula_tokens: list[dict[str, Any]] = []
    for tr in tbl.findall("./w:tr", NS):
        row_index = len(rows)
        row_text: list[str] = []
        row_blocks: list[dict[str, Any]] = []
        for tc in tr.findall("./w:tc", NS):
            col_index = len(row_text)
            paras = [serialize_paragraph(p, rels, media, image_counter, omml_provider, mtef_provider) for p in tc.findall("./w:p", NS)]
            text = "\n".join(p["markdown"] for p in paras if p.get("markdown"))
            row_text.append(text)
            row_blocks.append({"paragraphs": paras})
            for para_index, para in enumerate(paras):
                for token in para.get("tokens", []) or []:
                    if token.get("type") in {"omml_formula", "legacy_mtef_formula"}:
                        table_formula_tokens.append(
                            {
                                **token,
                                "table_row": row_index,
                                "table_col": col_index,
                                "cell_paragraph_index": para_index,
                            }
                        )
        rows.append(row_text)
        cell_blocks.append(row_blocks)
    markdown = "\n".join(" | ".join(cell for cell in row) for row in rows)
    return {
        "source_block_type": "docx_table",
        "text": markdown,
        "markdown": markdown,
        "tokens": [{"type": "table", "markdown": markdown}],
        "formula_count": sum(p.get("formula_count", 0) for row in cell_blocks for cell in row for p in cell["paragraphs"]),
        "formula_findings": [f for row in cell_blocks for cell in row for p in cell["paragraphs"] for f in p.get("formula_findings", [])],
        "table_formula_tokens": table_formula_tokens,
        "image_refs": [ref for row in cell_blocks for cell in row for p in cell["paragraphs"] for ref in p.get("image_refs", [])],
        "inline_glyph_refs": [ref for row in cell_blocks for cell in row for p in cell["paragraphs"] for ref in p.get("inline_glyph_refs", [])],
        "table_structured": {"rows": rows},
    }


def count_ole_embeddings(docx_path: Path) -> int:
    with zipfile.ZipFile(docx_path) as zf:
        return sum(1 for name in zf.namelist() if name.startswith("word/embeddings/") and not name.endswith("/"))


def extract_stream(docx_path: Path, out_dir: Path, formula_manifest: Path | None = None) -> dict[str, Any]:
    media = extract_media(docx_path, out_dir)
    image_counter = [0]
    paragraphs: list[dict[str, Any]] = []
    omml_provider = OmmlLatexProvider()
    mtef_provider = LegacyMtefManifestProvider(formula_manifest)
    with zipfile.ZipFile(docx_path) as zf:
        rels = parse_relationships(zf)
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find("w:body", NS)
    if body is not None:
        for child in body:
            if lname(child) == "p":
                block = serialize_paragraph(child, rels, media, image_counter, omml_provider, mtef_provider)
            elif lname(child) == "tbl":
                block = serialize_table(child, rels, media, image_counter, omml_provider, mtef_provider)
            else:
                continue
            block["paragraph_index"] = len(paragraphs)
            annotate_block_contract(block, len(paragraphs))
            paragraphs.append(block)
    counts = {
        "paragraphs": len(paragraphs),
        "tables": sum(1 for p in paragraphs if p["source_block_type"] == "docx_table"),
        "native_media": len(media),
        "image_insertions": image_counter[0],
        "formula_elements": sum(int(p.get("formula_count") or 0) for p in paragraphs),
        "legacy_ole_embeddings": count_ole_embeddings(docx_path),
        "legacy_mtef_manifest_formulas": mtef_provider.converted_count,
        "legacy_mtef_tokens": sum(1 for p in paragraphs for f in p.get("formula_findings", []) if f.get("type") == "legacy_mtef_formula" and f.get("has_latex")),
        "omml_formulas_with_sqrt": sum(1 for p in paragraphs for f in p.get("formula_findings", []) if f.get("has_sqrt")),
        "run_superscripts": sum(1 for p in paragraphs for f in p.get("formula_findings", []) if f.get("type") == "run_superscript"),
        "run_subscripts": sum(1 for p in paragraphs for f in p.get("formula_findings", []) if f.get("type") == "run_subscript"),
        "nested_run_texts": sum(1 for p in paragraphs for f in p.get("formula_findings", []) if f.get("type") == "nested_run_text"),
        "formula_structural_risk_blocks": sum(1 for p in paragraphs if p.get("formula_structural_risks")),
        "inline_glyph_assets": sum(len(p.get("inline_glyph_refs", []) or []) for p in paragraphs),
        "inline_glyph_blocks": sum(1 for p in paragraphs if p.get("inline_glyph_refs")),
    }
    loss_flag_counts: dict[str, int] = {}
    for block in paragraphs:
        for flag in block.get("content_loss_flags", []) or []:
            loss_flag_counts[flag] = loss_flag_counts.get(flag, 0) + 1
    counts["needs_review_blocks"] = sum(1 for p in paragraphs if p.get("qa_status") == "needs_review")
    counts["blocks_with_loss_flags"] = sum(1 for p in paragraphs if p.get("content_loss_flags"))
    counts["loss_flag_counts"] = loss_flag_counts
    write_json(out_dir / "paragraph_stream_formula_tokens.json", {"source_docx": str(docx_path), "counts": counts, "paragraphs": paragraphs})
    write_json(out_dir / "asset_manifest_native.json", {"assets": list(media.values())})
    write_json(out_dir / "formula_token_audit.json", build_audit(paragraphs, counts))
    return {"paragraphs": paragraphs, "assets": list(media.values()), "counts": counts}


def build_audit(paragraphs: list[dict[str, Any]], counts: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    missing_legacy = int(counts.get("legacy_ole_embeddings") or 0) - int(counts.get("legacy_mtef_tokens") or 0)
    if missing_legacy > 0:
        issues.append(
            {
                "code": "legacy_ole_equations_not_converted",
                "count": missing_legacy,
                "legacy_ole_embeddings": counts.get("legacy_ole_embeddings"),
                "legacy_mtef_tokens": counts.get("legacy_mtef_tokens"),
                "message": "This token stream handles OMML and Word run superscript/subscript only. Legacy Equation Editor OLE/MTEF must be converted by the MTEF bridge before this document can pass content QA.",
            }
        )
    for p in paragraphs:
        markdown = str(p.get("markdown") or "")
        if p.get("formula_count") and "$" not in markdown:
            issues.append({"code": "formula_count_without_formula_markdown", "paragraph_index": p.get("paragraph_index"), "sample": markdown[:200]})
        if any(f.get("has_sqrt") for f in p.get("formula_findings", [])) and "\\sqrt" not in markdown:
            issues.append({"code": "sqrt_formula_missing_in_markdown", "paragraph_index": p.get("paragraph_index"), "sample": markdown[:200]})
        for risk in p.get("formula_structural_risks", []) or []:
            issues.append(
                {
                    "code": "formula_structural_risk",
                    "risk_code": risk.get("risk_code"),
                    "paragraph_index": p.get("paragraph_index"),
                    "block_id": p.get("block_id"),
                    "sample": risk.get("span"),
                    "suggested_action": risk.get("suggested_action"),
                }
            )
    return {
        "schema_version": "docx_formula_token_audit.v0.1",
        "status": "ok" if not issues else "needs_review",
        "counts": counts,
        "issue_count": len(issues),
        "issues": issues,
    }


def build_packets_from_boundaries(paragraphs: list[dict[str, Any]], assets: list[dict[str, Any]], boundaries_path: Path, out_dir: Path) -> dict[str, Any]:
    boundaries = load_json(boundaries_path)
    packets: list[dict[str, Any]] = []
    for q in boundaries.get("questions") or []:
        start = int(q["start_paragraph_index"])
        end = int(q["end_paragraph_index"])
        paras = paragraphs[start : end + 1]
        display = "\n\n".join(p["markdown"] for p in paras if p.get("markdown"))
        refs = [ref for p in paras for ref in p.get("image_refs", [])]
        packets.append(
            {
                "question_id": q.get("question_id") or f"docx_q_{len(packets)+1:03d}",
                "order_index": q.get("order_index") or len(packets) + 1,
                "start_paragraph_index": start,
                "end_paragraph_index": end,
                "display_markdown": display,
                "asset_ids": list(dict.fromkeys(ref.get("asset_id") for ref in refs if ref.get("asset_id"))),
                "model_segmentation": q,
                "no_runtime_import": True,
                "no_database_write": True,
            }
        )
    manifest = {
        "schema_version": "docx_formula_token_question_packets.v0.1",
        "question_count": len(packets),
        "questions": packets,
        "assets": assets,
        "boundary_source": str(boundaries_path),
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "question_packets_formula_tokens.json", manifest)
    return manifest


def render_preview(out_dir: Path, paragraphs: list[dict[str, Any]], assets: list[dict[str, Any]], packets: dict[str, Any] | None) -> None:
    asset_by_id = {asset["asset_id"]: asset for asset in assets}

    def render_md(markdown: str) -> str:
        escaped = html.escape(markdown)
        for asset_id, asset in asset_by_id.items():
            token = html.escape(f"![{asset_id}](asset://{asset_id})")
            replacement = f"<figure><img src='{html.escape(asset.get('preview_src') or '')}' alt='{html.escape(asset_id)}'><figcaption>{html.escape(asset_id)}</figcaption></figure>"
            escaped = escaped.replace(token, replacement)
        return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    if packets:
        cards = []
        for q in packets.get("questions", []):
            meta = f"p{q['start_paragraph_index']}..p{q['end_paragraph_index']} assets={len(q.get('asset_ids') or [])}"
            cards.append(f"<article><h2>{html.escape(q['question_id'])}</h2><div class='meta'>{html.escape(meta)}</div>{render_md(q.get('display_markdown') or '')}</article>")
    else:
        cards = [f"<article><h2>p{p['paragraph_index']}</h2>{render_md(p.get('markdown') or '')}</article>" for p in paragraphs if p.get("markdown")]
    mathjax = """
<script>
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$']],
    processEscapes: true
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
  },
  chtml: { scale: 1 }
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
"""
    style = "body{margin:0;background:#f5f7fb;color:#172033;font-family:Arial,'Microsoft YaHei',sans-serif}main{max-width:1180px;margin:0 auto;padding:24px}article{background:#fff;border:1px solid #d8e0ec;border-radius:8px;margin:0 0 18px;padding:20px}.meta{color:#667899;margin-bottom:14px}p{font-size:17px;line-height:1.75}img{max-width:820px;max-height:560px;border:1px solid #cfd8e6}figcaption{color:#60708f}.MathJax{font-size:1.02em!important}"
    page = "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>DOCX Formula Token Preview</title><style>" + style + "</style>" + mathjax + "</head><body><main><h1>DOCX Formula Token Preview</h1>" + "".join(cards) + "</main></body></html>"
    (out_dir / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DOCX native paragraph stream with OMML and run-level formula tokens.")
    parser.add_argument("--docx", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--boundaries", type=Path, default=None, help="Optional model question_boundary_candidates.json to rebuild question packets.")
    parser.add_argument("--formula-manifest", type=Path, default=None, help="Optional existing formula_manifest_backend_preview.json with legacy MTEF conversions.")
    args = parser.parse_args()

    out_dir = OUT_ROOT / args.run_id / slug_for(args.docx)
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = extract_stream(args.docx.resolve(), out_dir, args.formula_manifest)
    packets = build_packets_from_boundaries(extracted["paragraphs"], extracted["assets"], args.boundaries, out_dir) if args.boundaries else None
    render_preview(out_dir, extracted["paragraphs"], extracted["assets"], packets)
    summary = {
        "schema_version": "docx_formula_token_stream_summary.v0.1",
        "source_docx": str(args.docx.resolve()),
        "out_dir": str(out_dir),
        **extracted["counts"],
        "question_count": packets.get("question_count") if packets else None,
        "artifacts": {
            "paragraph_stream": safe_rel(out_dir / "paragraph_stream_formula_tokens.json"),
            "asset_manifest": safe_rel(out_dir / "asset_manifest_native.json"),
            "formula_token_audit": safe_rel(out_dir / "formula_token_audit.json"),
            "question_packets": safe_rel(out_dir / "question_packets_formula_tokens.json") if packets else "",
            "preview_html": safe_rel(out_dir / "index.html"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
