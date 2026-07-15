from __future__ import annotations

import argparse
import html
import json
import shutil
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
            target.write_bytes(zf.read(zip_name))
            media[zip_name] = {
                "asset_id": asset_id,
                "zip_path": zip_name,
                "filename": target.name,
                "storage_key": safe_rel(target),
                "preview_src": "word_media_native/" + target.name,
                "bytes": target.stat().st_size,
            }
    return media


def run_vert_align(run: ET.Element) -> str:
    align = run.find("w:rPr/w:vertAlign", NS)
    return align.attrib.get(qn("w", "val"), "") if align is not None else ""


def run_text(run: ET.Element) -> str:
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


def serialize_run(run: ET.Element) -> tuple[str, list[dict[str, Any]]]:
    text = run_text(run)
    if not text:
        return "", []
    align = run_vert_align(run)
    if align == "superscript":
        return f"^{{{text}}}", [{"type": "run_superscript", "text": text}]
    if align == "subscript":
        return f"_{{{text}}}", [{"type": "run_subscript", "text": text}]
    return text, []


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


def collect_image_refs(el: ET.Element, rels: dict[str, str], media: dict[str, dict[str, Any]], counter: list[int]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    mode = "anchor" if el.findall(".//wp:anchor", NS) else "inline"
    for blip in el.findall(".//a:blip", NS):
        rid = blip.attrib.get(qn("r", "embed")) or blip.attrib.get(qn("r", "link"))
        asset = media.get(rels.get(rid or "", ""))
        if not asset:
            continue
        counter[0] += 1
        refs.append(
            {
                "image_ref_id": f"img_ref_{counter[0]:04d}",
                "asset_id": asset["asset_id"],
                "mode": mode,
                "storage_key": asset["storage_key"],
            }
        )
    return refs


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

    walk(p)
    plain = "".join(run_text(run) for run in p.findall(".//w:r", NS)).strip()
    markdown = tokens_to_markdown(tokens)
    return {
        "source_block_type": "docx_paragraph",
        "text": plain,
        "markdown": markdown,
        "tokens": tokens,
        "formula_count": formula_count,
        "formula_findings": findings,
        "image_refs": [token for token in tokens if token.get("type") == "image"],
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
    for tr in tbl.findall("./w:tr", NS):
        row_text: list[str] = []
        row_blocks: list[dict[str, Any]] = []
        for tc in tr.findall("./w:tc", NS):
            paras = [serialize_paragraph(p, rels, media, image_counter, omml_provider, mtef_provider) for p in tc.findall("./w:p", NS)]
            text = "\n".join(p["markdown"] for p in paras if p.get("markdown"))
            row_text.append(text)
            row_blocks.append({"paragraphs": paras})
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
        "image_refs": [ref for row in cell_blocks for cell in row for p in cell["paragraphs"] for ref in p.get("image_refs", [])],
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
    }
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
