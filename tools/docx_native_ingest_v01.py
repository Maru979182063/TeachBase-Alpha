from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.docx_native_config_v01 import load_config, nested_get, workspace_path


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

Q_START_RE = re.compile(r"^\s*【(?P<label>例\d+|变式\d+(?:-\d+)?)】")
ANSWER_MARKERS = ("【答案】",)
ANALYSIS_MARKERS = ("【分析】",)
SOLUTION_MARKERS = ("【详解】", "【解答】", "【证明】")
KNOWLEDGE_MARKERS = ("【点睛】", "【点评】", "【知识点】")
INLINE_MATH_TAG = f"{{{NS['m']}}}oMath"
MATH_PARA_TAG = f"{{{NS['m']}}}oMathPara"
P_TAG = f"{{{NS['w']}}}p"
TBL_TAG = f"{{{NS['w']}}}tbl"
TC_TAG = f"{{{NS['w']}}}tc"


def qn(name: str) -> str:
    prefix, local = name.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(zf.read(name))


def text_content(node: ET.Element) -> str:
    parts: list[str] = []
    for child in node.iter():
        if child.tag in {qn("w:t"), qn("m:t")}:
            parts.append(child.text or "")
    return "".join(parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> dict[str, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return {"width_px": img.width, "height_px": img.height}
    except Exception:
        return {"width_px": None, "height_px": None}


def rels_for_document(zf: zipfile.ZipFile) -> dict[str, str]:
    rel_root = read_xml(zf, "word/_rels/document.xml.rels")
    rels: dict[str, str] = {}
    for rel in rel_root:
        rid = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if rid and target:
            rels[rid] = target
    return rels


def normalize_media_target(target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("../"):
        return target[3:]
    if target.startswith("word/"):
        return target
    return "word/" + target


def extract_media(zf: zipfile.ZipFile, out_dir: Path) -> list[dict[str, Any]]:
    media_dir = out_dir / "word_media_native"
    media_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, zip_name in enumerate(sorted(n for n in zf.namelist() if n.startswith("word/media/")), start=1):
        name = Path(zip_name).name
        out_path = media_dir / name
        out_path.write_bytes(zf.read(zip_name))
        suffix = out_path.suffix.lower().lstrip(".")
        stat = out_path.stat()
        dims = image_size(out_path)
        records.append(
            {
                "asset_id": f"docx_media_{index:04d}",
                "zip_path": zip_name,
                "file_name": name,
                "format": suffix,
                "bytes": stat.st_size,
                "sha256": sha256_file(out_path),
                "native_path": str(out_path),
                **dims,
            }
        )
    return records


def xml_has(node: ET.Element, local: str) -> bool:
    return any(local_name(child.tag) == local for child in node.iter())


def omml_text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.findall(".//m:t", NS))


def convert_omml_node(node: ET.Element) -> str:
    name = local_name(node.tag)
    if name == "t":
        return node.text or ""
    if name == "r":
        return "".join(convert_omml_node(child) for child in node)
    if name == "f":
        num = node.find("m:num", NS)
        den = node.find("m:den", NS)
        return "\\frac{" + convert_omml_children(num) + "}{" + convert_omml_children(den) + "}"
    if name == "sSup":
        base = node.find("m:e", NS)
        sup = node.find("m:sup", NS)
        return convert_omml_children(base) + "^{" + convert_omml_children(sup) + "}"
    if name == "sSub":
        base = node.find("m:e", NS)
        sub = node.find("m:sub", NS)
        return convert_omml_children(base) + "_{" + convert_omml_children(sub) + "}"
    if name == "bar":
        base = node.find("m:e", NS)
        return "\\overline{" + convert_omml_children(base) + "}"
    if name == "d":
        base = node.find("m:e", NS)
        has_eq_arr = node.find(".//m:eqArr", NS) is not None
        left = "{" if has_eq_arr else "("
        right = "" if has_eq_arr else ")"
        beg = node.find("m:dPr/m:begChr", NS)
        end = node.find("m:dPr/m:endChr", NS)
        if beg is not None:
            left = beg.attrib.get(qn("m:val"), left)
        if end is not None:
            right = end.attrib.get(qn("m:val"), right)
        return "\\left" + escape_delim(left) + convert_omml_children(base) + "\\right" + escape_delim(right)
    if name == "eqArr":
        rows = []
        for child in node:
            if local_name(child.tag) == "e":
                row = convert_omml_children(child).strip()
                if row:
                    rows.append(row)
        if rows:
            return "\\begin{array}{l}" + " \\\\ ".join(rows) + "\\end{array}"
    return "".join(convert_omml_node(child) for child in node)


def escape_delim(value: str) -> str:
    value = (value or "").strip()
    if value == "{":
        return "\\{"
    if value == "}":
        return "\\}"
    if value == "":
        return "."
    return value


def convert_omml_children(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(convert_omml_node(child) for child in node)


def cleanup_latex(text: str) -> str:
    replacements = {
        "∠": "\\angle ",
        "△": "\\triangle ",
        "≅": "\\cong ",
        "∴": "\\therefore ",
        "∵": "\\because ",
        "⊥": "\\perp ",
        "∥": "\\parallel ",
        "°": "^\\circ",
        "（": "(",
        "）": ")",
        "，": ",",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def omml_to_latex(node: ET.Element) -> str:
    return cleanup_latex(convert_omml_node(node))


def condition_group_items(node: ET.Element) -> list[str]:
    eq_arr = node.find(".//m:eqArr", NS)
    if eq_arr is None:
        return []
    items: list[str] = []
    for child in eq_arr:
        if local_name(child.tag) != "e":
            continue
        item = cleanup_latex(convert_omml_children(child)).strip()
        if item:
            items.append(item)
    return items


@dataclass
class FormulaRecord:
    formula_id: str
    paragraph_index: int
    raw_omml_path: str
    flat_text: str
    latex_heuristic: str
    formula_kind: str
    structural_tags: list[str]
    condition_items: list[str] = field(default_factory=list)
    quality_status: str = "ok"
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class ParagraphRecord:
    paragraph_index: int
    block_kind: str
    text: str
    md: str
    table_index: int | None
    formula_ids: list[str] = field(default_factory=list)
    image_ref_ids: list[str] = field(default_factory=list)


def paragraph_markdown(
    paragraph: ET.Element,
    paragraph_index: int,
    formula_records: list[FormulaRecord],
    raw_omml_dir: Path,
) -> tuple[str, list[str]]:
    parts: list[str] = []
    formula_ids: list[str] = []
    for child in paragraph.iter():
        name = local_name(child.tag)
        if name == "t" and child.tag == qn("w:t"):
            parts.append(child.text or "")
        elif child.tag == INLINE_MATH_TAG:
            formula_id = f"omml_p{paragraph_index:04d}_{len(formula_records) + 1:04d}"
            raw_path = raw_omml_dir / f"{formula_id}.xml"
            raw_path.write_text(ET.tostring(child, encoding="unicode"), encoding="utf-8")
            tags = sorted({local_name(n.tag) for n in child.iter() if n.tag.startswith(f"{{{NS['m']}}}")})
            flat = omml_text(child)
            latex = omml_to_latex(child)
            items = condition_group_items(child)
            kind = "condition_group" if items else "ordinary_formula"
            reasons = ["omml_eqArr_condition_group"] if items else []
            formula_records.append(
                FormulaRecord(
                    formula_id=formula_id,
                    paragraph_index=paragraph_index,
                    raw_omml_path=str(raw_path),
                    flat_text=flat,
                    latex_heuristic=latex,
                    formula_kind=kind,
                    structural_tags=tags,
                    condition_items=items,
                    quality_status="needs_structured_review" if items else "ok",
                    review_reasons=reasons,
                )
            )
            formula_ids.append(formula_id)
            if items:
                rendered = "\n".join(f"- ${item}$" for item in items)
                parts.append(f"\n:::condition-group source={formula_id}\n{rendered}\n:::\n")
            else:
                parts.append(f"${latex}$" if latex else f"<!-- FORMULA_EMPTY {formula_id} -->")
    md = "".join(parts).strip()
    if not md:
        md = text_content(paragraph).strip()
    return md, formula_ids


def paragraph_images(
    paragraph: ET.Element,
    paragraph_index: int,
    rels: dict[str, str],
    media_by_zip: dict[str, dict[str, Any]],
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    for mode, path_expr in (("inline", ".//wp:inline"), ("anchor", ".//wp:anchor")):
        for drawing in paragraph.findall(path_expr, NS):
            for blip in drawing.findall(".//a:blip", NS):
                rid = blip.attrib.get(qn("r:embed")) or blip.attrib.get(qn("r:link")) or ""
                target = rels.get(rid, "")
                zip_path = normalize_media_target(target) if target else ""
                asset = media_by_zip.get(zip_path, {})
                ref_id = f"imgref_{next_index:04d}"
                next_index += 1
                records.append(
                    {
                        "image_ref_id": ref_id,
                        "paragraph_index": paragraph_index,
                        "mode": mode,
                        "rId": rid,
                        "zip_path": zip_path,
                        "asset_id": asset.get("asset_id", ""),
                        "native_path": asset.get("native_path", ""),
                        "width_px": asset.get("width_px"),
                        "height_px": asset.get("height_px"),
                    }
                )
    return records, next_index


def iter_body_paragraphs(body: ET.Element) -> list[tuple[ET.Element, str, int | None]]:
    parent_map = {child: parent for parent in body.iter() for child in parent}
    table_ids = {table: index for index, table in enumerate(body.findall(".//w:tbl", NS), start=1)}
    result: list[tuple[ET.Element, str, int | None]] = []
    for paragraph in body.iter():
        if paragraph.tag != P_TAG:
            continue
        cursor = parent_map.get(paragraph)
        table_index = None
        block_kind = "paragraph"
        while cursor is not None and cursor is not body:
            if cursor.tag == TBL_TAG:
                table_index = table_ids.get(cursor)
                block_kind = "table_paragraph"
                break
            cursor = parent_map.get(cursor)
        if block_kind == "paragraph" and parent_map.get(paragraph) is not body:
            block_kind = "nested_paragraph"
        result.append((paragraph, block_kind, table_index))
    return result


def parse_document(docx_path: Path, out_dir: Path) -> dict[str, Any]:
    raw_omml_dir = out_dir / "raw_omml"
    raw_omml_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx_path) as zf:
        rels = rels_for_document(zf)
        media_records = extract_media(zf, out_dir)
        media_by_zip = {item["zip_path"]: item for item in media_records}
        root = read_xml(zf, "word/document.xml")
        body = root.find("w:body", NS)
        if body is None:
            raise ValueError("word/document.xml has no w:body")
        table_count = len(body.findall("w:tbl", NS))
        paragraph_nodes = iter_body_paragraphs(body)
        formula_records: list[FormulaRecord] = []
        paragraph_records: list[ParagraphRecord] = []
        image_records: list[dict[str, Any]] = []
        next_image_index = 1
        inline_count = len(root.findall(".//wp:inline", NS))
        anchor_count = len(root.findall(".//wp:anchor", NS))
        anchor_with_blip_count = sum(1 for anchor in root.findall(".//wp:anchor", NS) if anchor.findall(".//a:blip", NS))
        omath_para_count = len(root.findall(".//m:oMathPara", NS))
        for paragraph_index, (paragraph, block_kind, table_index) in enumerate(paragraph_nodes):
            md, formula_ids = paragraph_markdown(paragraph, paragraph_index, formula_records, raw_omml_dir)
            images, next_image_index = paragraph_images(
                paragraph, paragraph_index, rels, media_by_zip, next_image_index
            )
            image_records.extend(images)
            text = text_content(paragraph).strip()
            paragraph_records.append(
                ParagraphRecord(
                    paragraph_index=paragraph_index,
                    block_kind=block_kind,
                    text=text,
                    md=md,
                    table_index=table_index,
                    formula_ids=formula_ids,
                    image_ref_ids=[item["image_ref_id"] for item in images],
                )
            )
    return {
        "paragraphs": paragraph_records,
        "formulas": formula_records,
        "images": image_records,
        "media": media_records,
        "counts": {
            "paragraphs": len(paragraph_records),
            "document_xml_all_paragraphs": len(root.findall(".//w:p", NS)),
            "document_xml_body_direct_paragraphs": len(body.findall("w:p", NS)),
            "document_xml_table_paragraphs": len(body.findall(".//w:tbl//w:p", NS)),
            "tables": table_count,
            "native_media": len(media_records),
            "image_insertions": len(image_records),
            "inline_shapes": inline_count,
            "floating_anchor_shapes": anchor_count,
            "floating_anchor_shapes_with_image_ref": anchor_with_blip_count,
            "floating_shapes_without_image_ref": max(anchor_count - anchor_with_blip_count, 0),
            "omml_formulas": len(formula_records),
            "omml_math_paragraphs": omath_para_count,
            "omml_total_elements": len(formula_records) + omath_para_count,
            "condition_group_formulas": sum(1 for f in formula_records if f.formula_kind == "condition_group"),
        },
    }


def field_for_text(text: str, current: str) -> str:
    if any(marker in text for marker in ANSWER_MARKERS):
        return "answer"
    if any(marker in text for marker in ANALYSIS_MARKERS):
        return "analysis"
    if any(marker in text for marker in SOLUTION_MARKERS):
        return "solution"
    if any(marker in text for marker in KNOWLEDGE_MARKERS):
        return "knowledge"
    return current


def paragraph_to_blocks(
    paragraph: ParagraphRecord,
    image_by_ref: dict[str, dict[str, Any]],
    formula_by_id: dict[str, FormulaRecord],
    field: str,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if paragraph.md:
        block_type = "text"
        if paragraph.formula_ids and not paragraph.text:
            block_type = "formula"
        if any(formula_by_id[fid].formula_kind == "condition_group" for fid in paragraph.formula_ids):
            block_type = "condition_group"
        block: dict[str, Any] = {
            "type": block_type,
            "field": field,
            "paragraph_index": paragraph.paragraph_index,
            "markdown": paragraph.md,
            "text": paragraph.text,
            "formula_ids": paragraph.formula_ids,
        }
        if block_type == "condition_group":
            items: list[str] = []
            for fid in paragraph.formula_ids:
                items.extend(formula_by_id[fid].condition_items)
            block["items"] = items
            block["needs_review"] = True
        blocks.append(block)
    for ref_id in paragraph.image_ref_ids:
        image = image_by_ref.get(ref_id, {})
        blocks.append(
            {
                "type": "image",
                "field": field,
                "paragraph_index": paragraph.paragraph_index,
                "image_ref_id": ref_id,
                "asset_id": image.get("asset_id", ""),
                "native_path": image.get("native_path", ""),
                "markdown": f"![{ref_id}]({image.get('native_path', '')})",
            }
        )
    return blocks


def split_questions(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    paragraphs: list[ParagraphRecord] = parsed["paragraphs"]
    image_by_ref = {item["image_ref_id"]: item for item in parsed["images"]}
    formula_by_id = {item.formula_id: item for item in parsed["formulas"]}
    questions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    field = "stem"

    for paragraph in paragraphs:
        text = paragraph.text or paragraph.md
        if Q_START_RE.search(text):
            if current:
                questions.append(current)
            q_index = len(questions) + 1
            title = text[:120]
            current = {
                "question_id": f"docx_q_{q_index:03d}",
                "order_index": q_index,
                "title": title,
                "start_paragraph_index": paragraph.paragraph_index,
                "end_paragraph_index": paragraph.paragraph_index,
                "fields": {"stem": [], "answer": [], "analysis": [], "solution": [], "knowledge": []},
                "blocks": [],
                "formula_ids": [],
                "image_ref_ids": [],
                "review_flags": [],
            }
            field = "stem"
        if not current:
            continue
        field = field_for_text(text, field)
        blocks = paragraph_to_blocks(paragraph, image_by_ref, formula_by_id, field)
        current["blocks"].extend(blocks)
        current["fields"].setdefault(field, []).extend(blocks)
        current["formula_ids"].extend(paragraph.formula_ids)
        current["image_ref_ids"].extend(paragraph.image_ref_ids)
        current["end_paragraph_index"] = paragraph.paragraph_index
    if current:
        questions.append(current)

    for question in questions:
        question["formula_ids"] = sorted(set(question["formula_ids"]))
        question["image_ref_ids"] = sorted(set(question["image_ref_ids"]))
        question["display_markdown"] = "\n\n".join(block.get("markdown", "") for block in question["blocks"]).strip()
        question["stem_text_md"] = "\n\n".join(block.get("markdown", "") for block in question["fields"].get("stem", [])).strip()
        question["answer_text_md"] = "\n\n".join(block.get("markdown", "") for block in question["fields"].get("answer", [])).strip()
        question["analysis_text_md"] = "\n\n".join(block.get("markdown", "") for block in question["fields"].get("analysis", [])).strip()
        if any(formula_by_id[fid].formula_kind == "condition_group" for fid in question["formula_ids"]):
            question["review_flags"].append("condition_group_formula_requires_model_or_human_review")
        if any(image_by_ref[rid].get("mode") == "anchor" for rid in question["image_ref_ids"]):
            question["review_flags"].append("floating_anchor_image_present")
        if not question["answer_text_md"]:
            question["review_flags"].append("answer_field_missing")
        if not question["analysis_text_md"]:
            question["review_flags"].append("analysis_field_missing")
    return questions


def build_asset_manifest(parsed: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    question_by_image: dict[str, str] = {}
    field_by_image: dict[str, str] = {}
    for question in questions:
        for block in question["blocks"]:
            if block.get("type") == "image":
                question_by_image[block["image_ref_id"]] = question["question_id"]
                field_by_image[block["image_ref_id"]] = block.get("field", "")
    insertions = []
    for item in parsed["images"]:
        insertions.append(
            {
                **item,
                "question_id": question_by_image.get(item["image_ref_id"], ""),
                "field": field_by_image.get(item["image_ref_id"], ""),
            }
        )
    referenced_asset_ids = {item["asset_id"] for item in parsed["images"] if item.get("asset_id")}
    assets = []
    for media in parsed["media"]:
        assets.append(
            {
                **media,
                "referenced_by_document_xml": media["asset_id"] in referenced_asset_ids,
                "storage_policy": "preserve_docx_native_original",
            }
        )
    return {
        "schema_version": "docx_native_asset_manifest.v0.1",
        "assets": assets,
        "image_insertions": insertions,
    }


def formula_to_dict(record: FormulaRecord, questions_by_formula: dict[str, str]) -> dict[str, Any]:
    return {
        "formula_id": record.formula_id,
        "question_id": questions_by_formula.get(record.formula_id, ""),
        "paragraph_index": record.paragraph_index,
        "formula_kind": record.formula_kind,
        "flat_text": record.flat_text,
        "latex_heuristic": record.latex_heuristic,
        "condition_items": record.condition_items,
        "structural_tags": record.structural_tags,
        "raw_omml_path": record.raw_omml_path,
        "quality_status": record.quality_status,
        "review_reasons": record.review_reasons,
    }


def build_release_decision(questions: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = []
    counter = Counter()
    for question in questions:
        reasons = list(question.get("review_flags", []))
        if reasons:
            status = "review"
        else:
            status = "allow_preview"
        counter[status] += 1
        decisions.append(
            {
                "question_id": question["question_id"],
                "status": status,
                "reasons": reasons,
                "not_runtime_imported": True,
            }
        )
    return {
        "schema_version": "docx_native_release_decision_preview.v0.1",
        "decision_counts": dict(counter),
        "decisions": decisions,
        "import_policy": "do_not_import_review_or_block_items; this run did not write runtime/db",
    }


def build_runtime_manifest_preview(
    docx_path: Path,
    questions: list[dict[str, Any]],
    asset_manifest: dict[str, Any],
) -> dict[str, Any]:
    runtime_questions = []
    for question in questions:
        visual_assets = []
        for ref_id in question["image_ref_ids"]:
            insertion = next((item for item in asset_manifest["image_insertions"] if item["image_ref_id"] == ref_id), None)
            if not insertion:
                continue
            visual_assets.append(
                {
                    "asset_id": insertion.get("asset_id", ""),
                    "display_ref": f"asset://{insertion.get('asset_id', '')}",
                    "storage_key": insertion.get("native_path", ""),
                    "attach_status": "attached",
                    "file_status": "exists",
                    "placement_scope": insertion.get("field", ""),
                    "source_image_role": "docx_native_media",
                    "paragraph_index": insertion.get("paragraph_index"),
                    "image_ref_id": ref_id,
                }
            )
        qvs = {
            "schema_version": "question_visual_structure.v1.1",
            "generated_by": "docx_native_ingest_v01",
            "question_uid": question["question_id"],
            "stem_md": question["stem_text_md"],
            "answer_md": question["answer_text_md"],
            "analysis_md": question["analysis_text_md"],
            "legacy_stem_md": question["stem_text_md"],
            "content_blocks": question["blocks"],
            "visual_assets": visual_assets,
            "review_flags": question["review_flags"],
            "source_refs": {
                "docx_path": str(docx_path),
                "start_paragraph_index": question["start_paragraph_index"],
                "end_paragraph_index": question["end_paragraph_index"],
            },
        }
        runtime_questions.append(
            {
                "question_uid": question["question_id"],
                "question_id": question["question_id"],
                "local_task_id": question["question_id"],
                "question_type": "math_docx_native_question",
                "display_markdown": question["display_markdown"],
                "stem_text_md": question["stem_text_md"],
                "answer_text_md": question["answer_text_md"],
                "analysis_text_md": question["analysis_text_md"],
                "question_visual_structure": qvs,
                "source_refs_json": {"question_visual_structure": qvs, "docx_native": qvs["source_refs"]},
                "review_flags": question["review_flags"],
            }
        )
    return {
        "schema_version": "docx_native_question_asset_manifest_preview.v0.1",
        "payload_type": "question_asset_manifest",
        "source_docx": str(docx_path),
        "questions": runtime_questions,
    }


def safe_file_stem(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", value).strip(" ._")
    if not text:
        text = fallback
    return text[:120]


def write_question_markdown_files(out_dir: Path, questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    md_dir = out_dir / "questions_md"
    md_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    for question in questions:
        stem = safe_file_stem(question.get("title", ""), question["question_id"])
        path = md_dir / f"{question['question_id']}_{stem}.md"
        lines = [
            f"<!-- question_id={question['question_id']} start_paragraph_index={question['start_paragraph_index']} end_paragraph_index={question['end_paragraph_index']} -->",
            "",
            question["display_markdown"],
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        records.append({"question_id": question["question_id"], "path": str(path)})
    return records


def build_model_refine_prompt_pack(
    questions: list[dict[str, Any]],
    formulas: list[dict[str, Any]],
) -> dict[str, Any]:
    formulas_by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for formula in formulas:
        if formula.get("formula_kind") == "condition_group":
            formulas_by_question[formula.get("question_id", "")].append(formula)
    tasks = []
    for question in questions:
        condition_groups = formulas_by_question.get(question["question_id"], [])
        if not condition_groups:
            continue
        tasks.append(
            {
                "question_id": question["question_id"],
                "instruction": (
                    "Review DOCX-native Markdown. Keep native image markers/paths. "
                    "Normalize each condition_group into the canonical :::condition-group block; "
                    "do not flatten multi-line OMML into one inline formula."
                ),
                "input_markdown": question["display_markdown"],
                "condition_group_candidates": [
                    {
                        "formula_id": item["formula_id"],
                        "paragraph_index": item["paragraph_index"],
                        "flat_text": item["flat_text"],
                        "latex_heuristic": item["latex_heuristic"],
                        "condition_items": item["condition_items"],
                        "raw_omml_path": item["raw_omml_path"],
                    }
                    for item in condition_groups
                ],
                "expected_output_contract": {
                    "markdown": "refined question markdown",
                    "blocks": "preserve text/formula/image/condition_group block boundaries",
                    "condition_group_format": ":::condition-group\\n- $line1$\\n- $line2$\\n:::",
                },
            }
        )
    return {
        "schema_version": "docx_native_model_refine_prompt_pack.v0.1",
        "task_count": len(tasks),
        "tasks": tasks,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(docx_path: Path, out_dir: Path, parsed: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_manifest = build_asset_manifest(parsed, questions)
    questions_by_formula: dict[str, str] = {}
    for question in questions:
        for fid in question["formula_ids"]:
            questions_by_formula[fid] = question["question_id"]
    formulas = [formula_to_dict(record, questions_by_formula) for record in parsed["formulas"]]
    release_decision = build_release_decision(questions)
    runtime_preview = build_runtime_manifest_preview(docx_path, questions, asset_manifest)
    question_md_records = write_question_markdown_files(out_dir, questions)
    model_refine_prompt_pack = build_model_refine_prompt_pack(questions, formulas)
    paragraph_stream = [record.__dict__ for record in parsed["paragraphs"]]
    summary = {
        "schema_version": "docx_native_ingest_summary.v0.1",
        "source_docx": str(docx_path),
        "out_dir": str(out_dir),
        **parsed["counts"],
        "questions": len(questions),
        "release_decision_counts": release_decision["decision_counts"],
        "note": "preview artifacts only; no Runtime import and no database write",
    }

    files = {
        "summary": out_dir / "summary.json",
        "paragraph_stream": out_dir / "paragraph_stream.json",
        "question_packets": out_dir / "question_packets_backend_preview.json",
        "asset_manifest": out_dir / "asset_manifest_backend_preview.json",
        "formula_manifest": out_dir / "formula_manifest_backend_preview.json",
        "release_decision": out_dir / "release_decision_preview.json",
        "runtime_preview": out_dir / "question_asset_manifest_for_runtime_preview.json",
        "model_refine_prompt_pack": out_dir / "model_refine_prompt_pack.json",
    }
    files["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    files["paragraph_stream"].write_text(json.dumps(paragraph_stream, ensure_ascii=False, indent=2), encoding="utf-8")
    files["question_packets"].write_text(json.dumps({"questions": questions}, ensure_ascii=False, indent=2), encoding="utf-8")
    files["asset_manifest"].write_text(json.dumps(asset_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    files["formula_manifest"].write_text(json.dumps({"formulas": formulas}, ensure_ascii=False, indent=2), encoding="utf-8")
    files["release_decision"].write_text(json.dumps(release_decision, ensure_ascii=False, indent=2), encoding="utf-8")
    files["runtime_preview"].write_text(json.dumps(runtime_preview, ensure_ascii=False, indent=2), encoding="utf-8")
    files["model_refine_prompt_pack"].write_text(
        json.dumps(model_refine_prompt_pack, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "question_markdown_manifest.json").write_text(
        json.dumps({"questions": question_md_records}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_csv(
        out_dir / "image_anchor_manifest.csv",
        asset_manifest["image_insertions"],
        ["image_ref_id", "question_id", "field", "paragraph_index", "mode", "rId", "zip_path", "asset_id", "native_path", "width_px", "height_px"],
    )
    write_csv(
        out_dir / "formula_manifest.csv",
        formulas,
        ["formula_id", "question_id", "paragraph_index", "formula_kind", "flat_text", "latex_heuristic", "quality_status", "review_reasons", "raw_omml_path"],
    )

    report = [
        "# DOCX Native Ingest v0.1 Report\n\n",
        "## Real Status\n\n",
        "- This is a native DOCX preview pipeline output, not a production DB import.\n",
        "- It reads `word/document.xml`, saves `word/media` originals, preserves raw OMML, and emits backend-preview packets.\n",
        "- It does not modify the PDF visual-first pipeline.\n\n",
        "## Counts\n\n",
        f"- Paragraphs: {summary['paragraphs']}\n",
        f"- `document.xml` all paragraphs: {summary['document_xml_all_paragraphs']}\n",
        f"- Body direct paragraphs: {summary['document_xml_body_direct_paragraphs']}\n",
        f"- Table paragraphs: {summary['document_xml_table_paragraphs']}\n",
        f"- Tables: {summary['tables']}\n",
        f"- Native media assets: {summary['native_media']}\n",
        f"- Image insertions: {summary['image_insertions']} (inline={summary['inline_shapes']}, anchor={summary['floating_anchor_shapes']})\n",
        f"- Floating anchors without image ref: {summary['floating_shapes_without_image_ref']}\n",
        f"- OMML formulas: {summary['omml_formulas']} (`m:oMathPara`={summary['omml_math_paragraphs']}, total elements={summary['omml_total_elements']})\n",
        f"- Condition-group formulas: {summary['condition_group_formulas']}\n",
        f"- Questions: {summary['questions']}\n",
        f"- Release decisions: {summary['release_decision_counts']}\n\n",
        "## Artifacts\n\n",
    ]
    for key, path in files.items():
        report.append(f"- {key}: `{path}`\n")
    report.append("\n## Known Risks\n\n")
    report.append("- `condition_group` formulas are flagged for model/human structured review before DB import.\n")
    report.append("- Floating anchors are preserved and flagged; ambiguous ownership should be reviewed.\n")
    report.append("- Runtime preview is adapter-shaped but was not imported in this run.\n")
    (out_dir / "docx_native_ingest_report.md").write_text("".join(report), encoding="utf-8")
    summary["artifacts"] = {key: str(path) for key, path in files.items()}
    summary["artifacts"]["report"] = str(out_dir / "docx_native_ingest_report.md")
    return summary


def run(docx_path: Path, out_dir: Path) -> dict[str, Any]:
    if not docx_path.exists():
        raise FileNotFoundError(docx_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for folder_name in ("raw_omml", "word_media_native", "questions_md"):
        folder = out_dir / folder_name
        if folder.exists():
            shutil.rmtree(folder)
    for file_name in (
        "summary.json",
        "paragraph_stream.json",
        "question_packets_backend_preview.json",
        "asset_manifest_backend_preview.json",
        "formula_manifest_backend_preview.json",
        "formula_manifest.csv",
        "image_anchor_manifest.csv",
        "release_decision_preview.json",
        "question_asset_manifest_for_runtime_preview.json",
        "model_refine_prompt_pack.json",
        "question_markdown_manifest.json",
        "docx_native_ingest_report.md",
    ):
        target = out_dir / file_name
        if target.exists():
            target.unlink()
    shutil.copy2(docx_path, out_dir / docx_path.name)
    parsed = parse_document(docx_path, out_dir)
    questions = split_questions(parsed)
    return write_outputs(docx_path, out_dir, parsed, questions)


def main() -> None:
    parser = argparse.ArgumentParser(description="DOCX native-first ingest preview pipeline v0.1")
    parser.add_argument("--config", default="")
    parser.add_argument("--docx", default=None, type=Path)
    parser.add_argument("--out", default=None, type=Path)
    args = parser.parse_args()
    config, config_path = load_config(args.config)
    docx_path = args.docx or Path(str(nested_get(config, "input.default_docx", "")))
    if not str(docx_path):
        raise SystemExit("missing_docx")
    if not docx_path.is_absolute():
        docx_path = workspace_path(docx_path)
    out_dir = args.out
    if out_dir is None:
        output_root = str(nested_get(config, "output.root", "outputs/docx_native_ingest_v0_1"))
        run_name = str(nested_get(config, "output.default_run_name", "configured_docx_native_run"))
        out_dir = workspace_path(Path(output_root) / run_name)
    elif not out_dir.is_absolute():
        out_dir = workspace_path(out_dir)
    summary = run(docx_path, out_dir)
    summary["loaded_config_path"] = str(config_path) if config_path.exists() else ""
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
