from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from PIL import Image


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
QVS_SCHEMA = "question_visual_structure.v1.1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except Exception:
        return str(path_value).replace("\\", "/")


def load_simple_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, data)]
    last_key_at_indent: dict[int, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            value = parse_scalar(line[2:].strip())
            if isinstance(parent, list):
                parent.append(value)
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            child: dict[str, Any] = {}
            if isinstance(parent, dict):
                parent[key] = child
                last_key_at_indent[indent] = key
            stack.append((indent, child))
            continue
        parsed = parse_scalar(value)
        if isinstance(parent, dict):
            parent[key] = parsed
            last_key_at_indent[indent] = key
            if isinstance(parsed, list):
                stack.append((indent, parsed))
        if value == "[]":
            stack.append((indent, parsed))
    # Fix list-valued sections in this config without requiring PyYAML.
    for section, keys in {
        "isolation": ["owned_output_roots", "owned_tool_prefixes", "forbidden_write_roots"],
    }.items():
        sec = data.get(section)
        if isinstance(sec, dict):
            for key in keys:
                if isinstance(sec.get(key), dict):
                    sec[key] = []
    return data


def parse_scalar(value: str) -> Any:
    text = value.strip().strip('"').strip("'")
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def clean_output_dir(out_dir: Path) -> None:
    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)


def qname(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def latex_escape_math_text(text: str) -> str:
    value = str(text or "")
    replacements = {
        "△": r"\triangle ",
        "∠": r"\angle ",
        "≌": r"\cong ",
        "∥": r"\parallel ",
        "⊥": r"\perp ",
        "°": r"^\circ",
        "≠": r"\ne ",
        "≥": r"\ge ",
        "≤": r"\le ",
        "×": r"\times ",
        "÷": r"\div ",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return re.sub(r"\s+", " ", value).strip()


def omml_plain_text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.findall(".//m:t", NS)).strip()


def omml_to_latex(node: ET.Element) -> str:
    tag = qname(node)
    if tag == "t":
        return latex_escape_math_text(node.text or "")
    if tag == "f":
        num = node.find("./m:num", NS)
        den = node.find("./m:den", NS)
        return r"\frac{" + omml_to_latex(num) + "}{" + omml_to_latex(den) + "}"
    if tag == "sSup":
        base = node.find("./m:e", NS)
        sup = node.find("./m:sup", NS)
        return omml_to_latex(base) + "^{" + omml_to_latex(sup) + "}"
    if tag == "sSub":
        base = node.find("./m:e", NS)
        sub = node.find("./m:sub", NS)
        return omml_to_latex(base) + "_{" + omml_to_latex(sub) + "}"
    if tag == "rad":
        deg = node.find("./m:deg", NS)
        base = node.find("./m:e", NS)
        if deg is not None and omml_plain_text(deg):
            return r"\sqrt[" + omml_to_latex(deg) + "]{" + omml_to_latex(base) + "}"
        return r"\sqrt{" + omml_to_latex(base) + "}"
    if tag == "d":
        beg = node.find("./m:dPr/m:begChr", NS)
        end = node.find("./m:dPr/m:endChr", NS)
        beg_chr = beg.get(f"{{{NS['m']}}}val", "") if beg is not None else ""
        end_chr = end.get(f"{{{NS['m']}}}val", "") if end is not None else ""
        body = "".join(omml_to_latex(child) for child in node if qname(child) != "dPr")
        return f"{beg_chr}{body}{end_chr}".strip()
    if node is None:
        return ""
    return "".join(omml_to_latex(child) for child in list(node)) or latex_escape_math_text(omml_plain_text(node))


def condition_group_items(node: ET.Element) -> list[str]:
    items: list[str] = []
    for eqarr in node.findall(".//m:eqArr", NS):
        for entry in eqarr.findall("./m:e", NS):
            text = omml_to_latex(entry).strip()
            if text:
                items.append(text)
    return items


def parse_relationships(zf: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
    rels = {}
    for rel in root.findall("rel:Relationship", NS):
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        if rid and target:
            rels[rid] = "word/" + target.lstrip("/") if not target.startswith("word/") else target
    return rels


def extract_media(docx_path: Path, out_dir: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    media_dir = out_dir / "word_media_native"
    media_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    zip_to_asset: dict[str, str] = {}
    with zipfile.ZipFile(docx_path) as zf:
        media_names = sorted([name for name in zf.namelist() if name.startswith("word/media/")])
        for index, name in enumerate(media_names, start=1):
            file_name = Path(name).name
            target = media_dir / file_name
            target.write_bytes(zf.read(name))
            width, height = image_size(target)
            asset_id = f"docx_media_{index:04d}"
            zip_to_asset[name] = asset_id
            assets.append(
                {
                    "asset_id": asset_id,
                    "zip_path": name,
                    "file_name": file_name,
                    "format": target.suffix.lower().lstrip("."),
                    "bytes": target.stat().st_size,
                    "sha256": sha256_file(target),
                    "native_path": str(target),
                    "storage_key": safe_rel(target),
                    "width_px": width,
                    "height_px": height,
                    "storage_policy": "preserve_docx_native_original",
                }
            )
    return assets, zip_to_asset


class DocxParser:
    def __init__(self, docx_path: Path, out_dir: Path):
        self.docx_path = docx_path
        self.out_dir = out_dir
        self.assets, self.zip_to_asset = extract_media(docx_path, out_dir)
        self.asset_by_id = {a["asset_id"]: a for a in self.assets}
        self.image_insertions: list[dict[str, Any]] = []
        self.formulas: list[dict[str, Any]] = []
        self.raw_omml_dir = out_dir / "raw_omml"
        self.raw_omml_dir.mkdir(parents=True, exist_ok=True)
        self.paragraph_index = 0
        self.inline_shapes = 0
        self.anchor_shapes = 0
        self.anchor_shapes_with_image = 0
        self.anchor_shapes_without_image = 0

    def parse(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with zipfile.ZipFile(self.docx_path) as zf:
            rels = parse_relationships(zf)
            root = ET.fromstring(zf.read("word/document.xml"))
        body = root.find("w:body", NS)
        paragraphs: list[dict[str, Any]] = []
        table_count = 0
        body_direct_paragraphs = 0
        table_paragraphs = 0
        if body is not None:
            for child in body:
                if qname(child) == "p":
                    paragraphs.append(self.parse_paragraph(child, rels, None))
                    body_direct_paragraphs += 1
                elif qname(child) == "tbl":
                    table_count += 1
                    for p in child.findall(".//w:p", NS):
                        paragraphs.append(self.parse_paragraph(p, rels, table_count))
                        table_paragraphs += 1
        summary = {
            "paragraphs": len(paragraphs),
            "document_xml_all_paragraphs": len(paragraphs),
            "document_xml_body_direct_paragraphs": body_direct_paragraphs,
            "document_xml_table_paragraphs": table_paragraphs,
            "tables": table_count,
            "native_media": len(self.assets),
            "image_insertions": len(self.image_insertions),
            "inline_shapes": self.inline_shapes,
            "floating_anchor_shapes": self.anchor_shapes,
            "floating_anchor_shapes_with_image_ref": self.anchor_shapes_with_image,
            "floating_shapes_without_image_ref": self.anchor_shapes_without_image,
            "omml_formulas": len([f for f in self.formulas if f["omml_kind"] == "oMath"]),
            "omml_math_paragraphs": len([f for f in self.formulas if f["omml_kind"] == "oMathPara"]),
            "omml_total_elements": len(self.formulas),
            "condition_group_formulas": len([f for f in self.formulas if f["formula_kind"] == "condition_group"]),
        }
        return paragraphs, summary

    def parse_paragraph(self, p: ET.Element, rels: dict[str, str], table_index: int | None) -> dict[str, Any]:
        idx = self.paragraph_index
        self.paragraph_index += 1
        state = {"markdown": [], "text": [], "formula_ids": [], "image_ref_ids": [], "blocks": []}
        self.walk_paragraph(p, rels, idx, state)
        markdown = "".join(state["markdown"]).strip()
        text = "".join(state["text"]).strip()
        return {
            "paragraph_index": idx,
            "table_index": table_index,
            "text": text,
            "markdown": markdown,
            "formula_ids": state["formula_ids"],
            "image_ref_ids": state["image_ref_ids"],
            "blocks": state["blocks"],
        }

    def walk_paragraph(self, node: ET.Element, rels: dict[str, str], pidx: int, state: dict[str, Any]) -> None:
        tag = qname(node)
        if tag == "t":
            text = node.text or ""
            state["text"].append(text)
            state["markdown"].append(text)
            return
        if tag in {"oMath", "oMathPara"}:
            self.add_formula(node, pidx, tag, state)
            return
        if tag == "drawing":
            self.add_drawing(node, rels, pidx, state)
            return
        if tag in {"tab"}:
            state["text"].append("\t")
            state["markdown"].append("\t")
            return
        if tag in {"br", "cr"}:
            state["text"].append("\n")
            state["markdown"].append("\n")
            return
        for child in node:
            self.walk_paragraph(child, rels, pidx, state)

    def add_formula(self, node: ET.Element, pidx: int, omml_kind: str, state: dict[str, Any]) -> None:
        fid = f"omml_p{pidx:04d}_{len(self.formulas)+1:04d}"
        raw_path = self.raw_omml_dir / f"{fid}.xml"
        raw_path.write_text(ET.tostring(node, encoding="unicode"), encoding="utf-8")
        items = condition_group_items(node)
        formula_kind = "condition_group" if items else "ordinary_formula"
        if items:
            markdown = f"\n:::condition-group source={fid}\n" + "\n".join(f"- ${item}$" for item in items) + "\n:::\n"
            text = "".join(items)
        else:
            latex = omml_to_latex(node).strip() or latex_escape_math_text(omml_plain_text(node))
            markdown = f"${latex}$" if latex else ""
            text = omml_plain_text(node)
        self.formulas.append(
            {
                "formula_id": fid,
                "paragraph_index": pidx,
                "omml_kind": omml_kind,
                "formula_kind": formula_kind,
                "latex": "" if items else markdown.strip("$"),
                "text": text,
                "items": items,
                "raw_omml_path": str(raw_path),
                "review_flags": ["condition_group_formula_requires_model_or_human_review"] if items else [],
            }
        )
        state["formula_ids"].append(fid)
        state["text"].append(text)
        state["markdown"].append(markdown)

    def add_drawing(self, node: ET.Element, rels: dict[str, str], pidx: int, state: dict[str, Any]) -> None:
        mode = "anchor" if node.find(".//wp:anchor", NS) is not None else "inline"
        if mode == "anchor":
            self.anchor_shapes += 1
        else:
            self.inline_shapes += 1
        blip = node.find(".//a:blip", NS)
        rid = blip.get(f"{{{NS['r']}}}embed", "") if blip is not None else ""
        zip_path = rels.get(rid, "")
        asset_id = self.zip_to_asset.get(zip_path, "")
        if mode == "anchor" and asset_id:
            self.anchor_shapes_with_image += 1
        if mode == "anchor" and not asset_id:
            self.anchor_shapes_without_image += 1
        if not asset_id:
            return
        image_ref_id = f"imgref_{len(self.image_insertions)+1:04d}"
        asset = self.asset_by_id.get(asset_id, {})
        insertion = {
            "image_ref_id": image_ref_id,
            "paragraph_index": pidx,
            "mode": mode,
            "rId": rid,
            "zip_path": zip_path,
            "asset_id": asset_id,
            "native_path": asset.get("native_path", ""),
            "storage_key": asset.get("storage_key", ""),
            "width_px": asset.get("width_px"),
            "height_px": asset.get("height_px"),
            "question_id": "",
            "field": "",
        }
        self.image_insertions.append(insertion)
        state["image_ref_ids"].append(image_ref_id)
        state["blocks"].append({"type": "image", "image_ref_id": image_ref_id, "asset_id": asset_id, "paragraph_index": pidx})
        state["markdown"].append(f"\n![{image_ref_id}]({asset.get('native_path','')})\n")


def split_questions(paragraphs: list[dict[str, Any]], formulas: list[dict[str, Any]], insertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formula_by_id = {f["formula_id"]: f for f in formulas}
    questions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    field = "stem"
    q_re = re.compile(r"^【(?:例\d+|变式\d+(?:-\d+)?)】")
    for paragraph in paragraphs:
        text = paragraph.get("text", "").strip()
        markdown = paragraph.get("markdown", "").strip()
        if q_re.match(text) or q_re.match(markdown):
            if current:
                finish_question(current, formulas, insertions)
                questions.append(current)
            qid = f"docx_q_{len(questions)+1:03d}"
            current = {
                "question_id": qid,
                "order_index": len(questions) + 1,
                "title": text[:120],
                "start_paragraph_index": paragraph["paragraph_index"],
                "end_paragraph_index": paragraph["paragraph_index"],
                "fields": {"stem": [], "answer": [], "analysis": []},
                "blocks": [],
                "formula_ids": [],
                "image_ref_ids": [],
                "review_flags": [],
            }
            field = "stem"
        if not current:
            continue
        current["end_paragraph_index"] = paragraph["paragraph_index"]
        para_field = field
        if "【答案】" in text or "【答案】" in markdown:
            para_field = "answer"
            field = "answer"
        if "【分析】" in text or "【分析】" in markdown:
            para_field = "analysis" if text.strip().startswith("【分析】") or markdown.strip().startswith("【分析】") else para_field
            field = "analysis"
        if markdown:
            current["fields"][para_field].append(markdown)
            block_type = "condition_group" if any(formula_by_id.get(fid, {}).get("formula_kind") == "condition_group" for fid in paragraph["formula_ids"]) else "text"
            block = {
                "type": block_type,
                "field": para_field,
                "paragraph_index": paragraph["paragraph_index"],
                "markdown": markdown,
                "text": text,
                "formula_ids": paragraph["formula_ids"],
            }
            if block_type == "condition_group":
                fid = next(fid for fid in paragraph["formula_ids"] if formula_by_id.get(fid, {}).get("formula_kind") == "condition_group")
                block["items"] = formula_by_id[fid].get("items", [])
                block["needs_review"] = True
            current["blocks"].append(block)
        for ref_id in paragraph["image_ref_ids"]:
            current["image_ref_ids"].append(ref_id)
            insertion = next((i for i in insertions if i["image_ref_id"] == ref_id), None)
            if insertion:
                insertion["question_id"] = current["question_id"]
                insertion["field"] = para_field
                current["blocks"].append(
                    {
                        "type": "image",
                        "field": para_field,
                        "paragraph_index": paragraph["paragraph_index"],
                        "image_ref_id": ref_id,
                        "asset_id": insertion.get("asset_id", ""),
                        "native_path": insertion.get("native_path", ""),
                        "markdown": f"![{ref_id}]({insertion.get('native_path','')})",
                    }
                )
        current["formula_ids"].extend(paragraph["formula_ids"])
    if current:
        finish_question(current, formulas, insertions)
        questions.append(current)
    return questions


def finish_question(question: dict[str, Any], formulas: list[dict[str, Any]], insertions: list[dict[str, Any]]) -> None:
    for key in ["stem", "answer", "analysis"]:
        question[f"{key}_text_md"] = "\n\n".join(x for x in question["fields"][key] if x).strip()
    display = "\n\n".join(x for x in [question["stem_text_md"], question["answer_text_md"], question["analysis_text_md"]] if x)
    question["display_markdown"] = display
    if any(f.get("formula_kind") == "condition_group" for f in formulas if f.get("formula_id") in question["formula_ids"]):
        question["review_flags"].append("condition_group_formula_requires_model_or_human_review")


def build_release_decision(questions: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = []
    counts = Counter()
    for q in questions:
        reasons = list(q.get("review_flags", []))
        status = "review" if reasons else "allow_preview"
        counts[status] += 1
        decisions.append({"question_id": q["question_id"], "status": status, "reasons": reasons, "not_runtime_imported": True})
    return {
        "schema_version": "docx_native_release_decision_preview.v0.1",
        "decision_counts": dict(counts),
        "decisions": decisions,
        "import_policy": "preview only; this run did not write runtime/db",
    }


def build_prompt_pack(questions: list[dict[str, Any]], formulas: list[dict[str, Any]]) -> dict[str, Any]:
    by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    q_by_formula = {}
    for q in questions:
        for fid in q["formula_ids"]:
            q_by_formula[fid] = q["question_id"]
    for f in formulas:
        if f.get("formula_kind") == "condition_group":
            by_q[q_by_formula.get(f["formula_id"], "")].append(f)
    tasks = []
    for q in questions:
        groups = by_q.get(q["question_id"], [])
        if not groups:
            continue
        tasks.append(
            {
                "question_id": q["question_id"],
                "instruction": (
                    "Review DOCX-native Markdown. Preserve content and image markers. "
                    "Normalize condition groups into canonical :::condition-group blocks. "
                    "Return strict JSON only."
                ),
                "input_markdown": q["display_markdown"],
                "condition_group_candidates": [
                    {"formula_id": f["formula_id"], "items": f.get("items", []), "raw_omml_path": f.get("raw_omml_path", "")}
                    for f in groups
                ],
                "expected_output_schema": {
                    "question_id": q["question_id"],
                    "status": "ok|needs_review",
                    "refined_markdown": "string",
                    "condition_groups": [{"formula_id": "string", "items": ["latex"], "markdown": "string"}],
                    "review_flags": [],
                    "notes": "string",
                },
            }
        )
    return {"schema_version": "docx_native_model_refine_prompt_pack.v0.1", "tasks": tasks}


def call_model(task: dict[str, Any], config: dict[str, Any], api_key: str) -> dict[str, Any]:
    model_cfg = config.get("model_refine", {})
    payload = {
        "model": model_cfg.get("model", "doubao-seed-2-0-lite-260428"),
        "temperature": float(model_cfg.get("temperature", 0.1)),
        "max_tokens": int(model_cfg.get("max_tokens", 4096)),
        "messages": [
            {"role": "system", "content": "You are a precise DOCX math transcription reviewer. Return valid JSON only."},
            {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
        ],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        model_cfg.get("endpoint", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=int(model_cfg.get("timeout_seconds", 120))) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    content = raw["choices"][0]["message"]["content"]
    match = re.search(r"\{[\s\S]*\}", content)
    parsed = json.loads(match.group(0) if match else content)
    return {"raw_response": raw, "raw_content": content, "parsed": parsed}


def run_model_refine(out_dir: Path, prompt_pack: dict[str, Any], config: dict[str, Any], limit: int | None, prepare_only: bool) -> dict[str, Any]:
    model_cfg = config.get("model_refine", {})
    api_key_env = str(model_cfg.get("api_key_env", "ARK_API_KEY"))
    api_key = os.environ.get(api_key_env, "")
    model_dir = out_dir / "model_refine_doubao2_0_mini_v01"
    model_dir.mkdir(parents=True, exist_ok=True)
    tasks = list(prompt_pack.get("tasks", []))
    if limit is not None and limit >= 0:
        tasks = tasks[:limit]
    records = []
    if prepare_only or not api_key:
        status = "prepared" if prepare_only else "blocked"
        summary = {
            "schema_version": "docx_native_model_refine_summary.v0.1",
            "status": status,
            "reason": "prepare_only" if prepare_only else "missing_api_key",
            "api_key_env": api_key_env,
            "task_count": len(tasks),
            "no_runtime_import": True,
            "no_database_write": True,
        }
        write_json(model_dir / "model_refine_summary.json", summary)
        return summary
    for index, task in enumerate(tasks, start=1):
        started = time.time()
        record = {"question_id": task["question_id"], "index": index, "status": "pending", "started_at": now_iso()}
        try:
            response = call_model(task, config, api_key)
            record.update({"status": "ok", "parsed": response["parsed"], "latency_seconds": round(time.time() - started, 3)})
        except Exception as exc:
            record.update({"status": "failed", "error": str(exc), "latency_seconds": round(time.time() - started, 3)})
        records.append(record)
        write_json(model_dir / "records" / f"{task['question_id']}.json", record)
    write_json(model_dir / "model_refine_records.json", {"records": records})
    summary = {
        "schema_version": "docx_native_model_refine_summary.v0.1",
        "status": "ok" if all(r["status"] == "ok" for r in records) else "partial",
        "model": model_cfg.get("model"),
        "provider": model_cfg.get("provider"),
        "api_key_env": api_key_env,
        "task_count": len(records),
        "status_counts": dict(Counter(r["status"] for r in records)),
        "out_dir": str(model_dir),
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(model_dir / "model_refine_summary.json", summary)
    return summary


def merge_refine(questions: list[dict[str, Any]], model_dir: Path) -> list[dict[str, Any]]:
    records_path = model_dir / "model_refine_records.json"
    if not records_path.exists():
        return questions
    records = read_json(records_path).get("records", [])
    by_q = {r["question_id"]: r.get("parsed", {}) for r in records if r.get("status") == "ok"}
    merged = json.loads(json.dumps(questions, ensure_ascii=False))
    for q in merged:
        parsed = by_q.get(q["question_id"])
        if not parsed:
            continue
        q["model_refine"] = {
            "status": parsed.get("status", "ok"),
            "model_refined_markdown": parsed.get("refined_markdown", ""),
            "condition_groups": parsed.get("condition_groups", []),
            "review_flags": parsed.get("review_flags", []),
            "notes": parsed.get("notes", ""),
        }
        if parsed.get("refined_markdown"):
            q["display_markdown_model_refined"] = parsed["refined_markdown"]
    return merged


def replace_image_links(markdown: str, insertions: list[dict[str, Any]]) -> str:
    text = str(markdown or "")
    for ins in insertions:
        ref_id = ins.get("image_ref_id", "")
        asset_id = ins.get("asset_id", "")
        native = ins.get("native_path", "")
        if not asset_id:
            continue
        replacement = f"![{asset_id}](asset://{asset_id})"
        if ref_id:
            text = re.sub(rf"!\[[^\]]*{re.escape(ref_id)}[^\]]*\]\([^)]+\)", replacement, text)
        if native:
            text = text.replace(native, f"asset://{asset_id}").replace(native.replace("\\", "/"), f"asset://{asset_id}")
    return text


def split_sections(markdown: str, q: dict[str, Any], insertions: list[dict[str, Any]]) -> dict[str, str]:
    text = replace_image_links(markdown, insertions).strip()
    fallback = {
        "stem_md": replace_image_links(q.get("stem_text_md", ""), insertions),
        "answer_md": replace_image_links(q.get("answer_text_md", ""), insertions),
        "analysis_md": replace_image_links(q.get("analysis_text_md", ""), insertions),
        "display_markdown": text,
    }
    a = text.find("【答案】")
    b = text.find("【分析】")
    if a < 0:
        return fallback
    stem = text[:a].strip()
    if b > a:
        answer = text[a + len("【答案】") : b].strip()
        analysis = text[b + len("【分析】") :].strip()
    else:
        answer = text[a + len("【答案】") :].strip()
        analysis = fallback["analysis_md"]
    return {"stem_md": stem or fallback["stem_md"], "answer_md": answer or fallback["answer_md"], "analysis_md": analysis or fallback["analysis_md"], "display_markdown": text}


def build_backend_aligned(out_dir: Path, questions: list[dict[str, Any]], assets: list[dict[str, Any]], insertions: list[dict[str, Any]], release: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    backend_dir = out_dir / "backend_aligned_v01"
    asset_by_id = {a["asset_id"]: a for a in assets}
    insertion_by_ref = {i["image_ref_id"]: i for i in insertions}
    decision_by_q = {d["question_id"]: d for d in release.get("decisions", [])}
    runtime = config.get("runtime_contract", {})
    aligned_questions = []
    for q in questions:
        q_insertions = [insertion_by_ref[r] for r in q.get("image_ref_ids", []) if r in insertion_by_ref]
        sections = split_sections(q.get("display_markdown_model_refined") or q.get("display_markdown", ""), q, q_insertions)
        visual_assets = []
        image_anchors = []
        for ins in q_insertions:
            asset = asset_by_id.get(ins["asset_id"], {})
            field = ins.get("field") or "stem"
            placement = "after_analysis" if field in {"answer", "analysis"} else "after_stem"
            visual_assets.append(
                {
                    "asset_id": ins["asset_id"],
                    "asset_role": "analysis" if field in {"answer", "analysis"} else "stem",
                    "option_key": None,
                    "placement_scope": placement,
                    "attach_status": "attached",
                    "file_status": "materialized",
                    "display_ref": f"asset://{ins['asset_id']}",
                    "storage_key": asset.get("storage_key") or safe_rel(asset.get("native_path", "")),
                    "bbox_space": "docx_native_paragraph_anchor",
                    "bbox_json": {"paragraph_index": ins.get("paragraph_index"), "mode": ins.get("mode")},
                    "source_image_role": "docx_native_media",
                    "source_image_asset_id": ins["asset_id"],
                    "source_image_storage_key": asset.get("storage_key") or safe_rel(asset.get("native_path", "")),
                    "confidence": 1.0,
                    "runtime_run_id": out_dir.name,
                    "review_flags": [],
                    "docx_anchor": {"image_ref_id": ins["image_ref_id"], "paragraph_index": ins.get("paragraph_index"), "mode": ins.get("mode"), "rId": ins.get("rId"), "zip_path": ins.get("zip_path")},
                    "width_px": asset.get("width_px"),
                    "height_px": asset.get("height_px"),
                    "sha256": asset.get("sha256"),
                    "format": asset.get("format"),
                }
            )
            image_anchors.append({"image_ref_id": ins["image_ref_id"], "asset_id": ins["asset_id"], "paragraph_index": ins.get("paragraph_index"), "field": field, "mode": ins.get("mode"), "storage_key": asset.get("storage_key")})
        content_blocks = []
        order = 1
        model_groups = {}
        if isinstance(q.get("model_refine"), dict):
            for group in q["model_refine"].get("condition_groups", []) or []:
                if isinstance(group, dict) and group.get("formula_id"):
                    model_groups[group["formula_id"]] = group
        for block in q.get("blocks", []):
            if block.get("type") == "image":
                aid = block.get("asset_id")
                if aid:
                    content_blocks.append({"block_id": f"{q['question_id']}_blk_{order:03d}", "block_order": order, "scope": block.get("field", "stem"), "paragraph_index": block.get("paragraph_index"), "block_type": "image", "asset_id": aid, "display_ref": f"asset://{aid}", "image_ref_id": block.get("image_ref_id")})
                    order += 1
                continue
            if block.get("type") == "condition_group":
                fid = (block.get("formula_ids") or [""])[0]
                group = model_groups.get(fid, {"formula_id": fid, "items": block.get("items", []), "markdown": block.get("markdown", "")})
                content_blocks.append({"block_id": f"{q['question_id']}_blk_{order:03d}", "block_order": order, "scope": block.get("field", "answer"), "paragraph_index": block.get("paragraph_index"), "block_type": "condition_group", "semantic_type": "condition_group", "text_md": replace_image_links(group.get("markdown", ""), q_insertions), "formula_ids": block.get("formula_ids", []), "condition_group": group, "source": "omml"})
                order += 1
                continue
            if block.get("markdown"):
                content_blocks.append({"block_id": f"{q['question_id']}_blk_{order:03d}", "block_order": order, "scope": block.get("field", "stem"), "paragraph_index": block.get("paragraph_index"), "block_type": "markdown", "text_md": replace_image_links(block.get("markdown", ""), q_insertions), "formula_ids": block.get("formula_ids", [])})
                order += 1
        decision = decision_by_q.get(q["question_id"], {})
        model_status = q.get("model_refine", {}).get("status") if isinstance(q.get("model_refine"), dict) else "not_run"
        review_flags = list(dict.fromkeys(q.get("review_flags", []) + (q.get("model_refine", {}).get("review_flags", []) if isinstance(q.get("model_refine"), dict) else [])))
        condition_groups = [b["condition_group"] for b in content_blocks if b.get("block_type") == "condition_group"]
        qvs = {
            "schema_version": QVS_SCHEMA,
            "generated_by": "docx_native_pipeline_v01",
            "runtime_run_id": out_dir.name,
            "question_uid": q["question_id"],
            "stem_md": sections["stem_md"],
            "answer_md": sections["answer_md"],
            "analysis_md": sections["analysis_md"],
            "legacy_stem_md": sections["display_markdown"],
            "gating": {"release_status": decision.get("status", "unknown"), "decision_reasons": decision.get("reasons", []), "model_refine_status": model_status, "needs_review": bool(review_flags)},
            "options": [],
            "content_blocks": content_blocks,
            "visual_assets": visual_assets,
            "review_flags": review_flags,
        }
        source_refs = {"schema_versions": {"question_visual_structure": QVS_SCHEMA, "docx_native_pipeline": "docx_native_pipeline.v0.1"}, "page_no": 1, "bbox": {"x": 0, "y": 0, "width": 100, "height": 100}, "question_visual_structure": qvs, "docx_native": {"source_docx_name": Path(str(read_json(out_dir / "summary.json").get("source_docx", ""))).name, "ingest_dir": safe_rel(out_dir), "question_id": q["question_id"], "start_paragraph_index": q.get("start_paragraph_index"), "end_paragraph_index": q.get("end_paragraph_index"), "formula_ids": q.get("formula_ids", []), "image_anchors": image_anchors, "condition_groups": condition_groups, "model_refine": {"status": model_status, "condition_group_count": len(condition_groups)}}}
        aligned_questions.append({"question_uid": q["question_id"], "question_id": q["question_id"], "local_task_id": q["question_id"], "source_node_local_id": "root", "question_type": "math_docx_native_question", "display_markdown": sections["display_markdown"], "stem_text_md": sections["stem_md"], "answer_text_md": sections["answer_md"], "analysis_text_md": sections["analysis_md"], "checkpoint_codes": [], "subject_tags": ["docx_native", runtime.get("track_code", "math_junior")], "difficulty_level": 3, "difficulty_confidence": 0.5, "question_visual_structure": qvs, "source_refs_json": source_refs, "merged_source_refs_json": source_refs, "review_flags": review_flags})
    manifest = {"schema_version": "docx_native_backend_aligned_manifest.v0.1", "payload_type": "question_asset_manifest", "generated_at": now_iso(), "source_docx_name": Path(str(read_json(out_dir / "summary.json").get("source_docx", ""))).name, "runtime_contract": {**runtime, "question_visual_structure_schema": QVS_SCHEMA, "no_runtime_import": True, "no_database_write": True}, "questions": aligned_questions}
    write_json(backend_dir / "docx_native_backend_aligned_question_asset_manifest.json", manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    rows = []
    for q in manifest.get("questions", []):
        qvs = q.get("question_visual_structure", {})
        errors = []
        assets = qvs.get("visual_assets", [])
        asset_ids = {a.get("asset_id") for a in assets}
        for asset in assets:
            storage = str(asset.get("storage_key", ""))
            if re.match(r"^[A-Za-z]:[\\/]", storage) or storage.startswith("/"):
                errors.append(f"asset_storage_key_absolute:{asset.get('asset_id')}")
            if storage and not (WORKSPACE_ROOT / storage).exists():
                errors.append(f"asset_storage_missing:{asset.get('asset_id')}")
            if asset.get("display_ref") != f"asset://{asset.get('asset_id')}":
                errors.append(f"asset_display_ref_noncanonical:{asset.get('asset_id')}")
        for block in qvs.get("content_blocks", []):
            if block.get("asset_id") and block.get("asset_id") not in asset_ids:
                errors.append(f"content_block_asset_missing:{block.get('asset_id')}")
        rows.append({"local_task_id": q.get("local_task_id"), "question_uid": qvs.get("question_uid"), "ok": not errors, "errors": errors, "visual_asset_count": len(assets), "content_block_count": len(qvs.get("content_blocks", [])), "condition_group_block_count": len([b for b in qvs.get("content_blocks", []) if b.get("block_type") == "condition_group"])})
    report = {"schema_version": "docx_native_backend_contract_check.v0.1", "status": "ok" if all(r["ok"] for r in rows) else "fail", "note": "contract check only; no Runtime import and no database write", "task_count": len(rows), "failed_task_count": len([r for r in rows if not r["ok"]]), "visual_asset_count": sum(r["visual_asset_count"] for r in rows), "content_block_count": sum(r["content_block_count"] for r in rows), "condition_group_block_count": sum(r["condition_group_block_count"] for r in rows), "runtime_imported": False, "database_written": False, "rows": rows}
    write_json(out_dir / "backend_aligned_v01" / "docx_native_backend_contract_check.json", report)
    return report


def render_preview(manifest: dict[str, Any], out_dir: Path) -> Path:
    render_dir = out_dir / "backend_aligned_v01" / "render_backend_aligned_v01"
    render_dir.mkdir(parents=True, exist_ok=True)
    def img_html(asset_id: str, assets: dict[str, dict[str, Any]]) -> str:
        asset = assets.get(asset_id)
        if not asset:
            return f"<span class='missing'>missing asset://{html.escape(asset_id)}</span>"
        url = safe_rel(WORKSPACE_ROOT / asset["storage_key"])
        try:
            url = (WORKSPACE_ROOT / asset["storage_key"]).resolve().relative_to(render_dir.resolve()).as_posix()
        except Exception:
            url = "../../../" + asset["storage_key"]
        return f"<figure><img src='{html.escape(url)}'><figcaption>{html.escape(asset_id)} · {html.escape(asset.get('storage_key',''))}</figcaption></figure>"
    def md(text: str, assets: dict[str, dict[str, Any]]) -> str:
        text = html.escape(str(text or ""))
        text = re.sub(r"!\[[^\]]*\]\(asset://([^)]+)\)", lambda m: img_html(m.group(1), assets), text)
        text = re.sub(r":::condition-group(?: source=([A-Za-z0-9._:-]+))?\n([\s\S]*?)\n:::", lambda m: "<div class='cg'><b>condition_group " + html.escape(m.group(1) or "") + "</b><pre>" + m.group(2) + "</pre></div>", text)
        return "".join(f"<p>{p}</p>" for p in re.split(r"\n{2,}", text) if p.strip())
    cards = []
    for q in manifest.get("questions", []):
        qvs = q.get("question_visual_structure", {})
        assets = {a["asset_id"]: a for a in qvs.get("visual_assets", [])}
        cards.append(f"<article id='{q['question_id']}'><h2>{q['question_id']}</h2><div class='meta'>{len(assets)} images · {len([b for b in qvs.get('content_blocks',[]) if b.get('block_type')=='condition_group'])} condition_groups · {html.escape(str(qvs.get('gating',{}).get('release_status','')))}</div>{md(q.get('display_markdown',''), assets)}</article>")
    index = render_dir / "index.html"
    index.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><title>DOCX Native Pipeline Preview</title><script>window.MathJax={{tex:{{inlineMath:[[ '$','$' ]]}}}};</script><script defer src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js'></script><style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;background:#f6f7f9;color:#1d2430;margin:0}}main{{max-width:980px;margin:0 auto;padding:22px}}article{{background:white;border:1px solid #dce2ea;border-radius:8px;margin:0 0 18px;padding:18px}}.meta{{color:#64748b;font-size:13px;margin-bottom:12px}}img{{max-width:520px;width:auto;height:auto;border:1px solid #dce2ea}}figure{{margin:12px 0}}figcaption{{font-size:12px;color:#64748b;overflow-wrap:anywhere}}.cg{{border-left:4px solid #22c55e;background:#f0fdf4;padding:10px 12px;margin:12px 0}}pre{{white-space:pre-wrap;font-family:inherit}}</style></head><body><main><h1>DOCX Native Pipeline Preview</h1>{''.join(cards)}</main></body></html>""", encoding="utf-8")
    return index


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    config_path = args.config if args.config.is_absolute() else WORKSPACE_ROOT / args.config
    config = load_simple_yaml(config_path)
    docx_path = args.docx if args.docx.is_absolute() else WORKSPACE_ROOT / args.docx
    output_root = WORKSPACE_ROOT / str(config.get("pipeline", {}).get("output_root", "outputs/docx_native_pipeline_v0_1"))
    run_id = args.run_id or f"sample_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    if args.clean:
        clean_output_dir(out_dir)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(docx_path, out_dir / docx_path.name)
    parser = DocxParser(docx_path, out_dir)
    paragraphs, parse_summary = parser.parse()
    questions = split_questions(paragraphs, parser.formulas, parser.image_insertions)
    summary = {"schema_version": "docx_native_pipeline_summary.v0.1", "source_docx": str(docx_path), "out_dir": str(out_dir), **parse_summary, "questions": len(questions)}
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "paragraph_stream.json", {"paragraphs": paragraphs})
    write_json(out_dir / "asset_manifest_backend_preview.json", {"schema_version": "docx_native_asset_manifest.v0.1", "assets": parser.assets, "image_insertions": parser.image_insertions})
    write_json(out_dir / "formula_manifest_backend_preview.json", {"formulas": parser.formulas})
    write_json(out_dir / "question_packets_backend_preview.json", {"questions": questions})
    release = build_release_decision(questions)
    write_json(out_dir / "release_decision_preview.json", release)
    prompt_pack = build_prompt_pack(questions, parser.formulas)
    write_json(out_dir / "model_refine_prompt_pack.json", prompt_pack)
    model_summary = run_model_refine(out_dir, prompt_pack, config, args.model_limit, args.prepare_only or args.skip_model)
    merged_questions = merge_refine(questions, out_dir / "model_refine_doubao2_0_mini_v01")
    write_json(out_dir / "model_refine_doubao2_0_mini_v01" / "question_packets_model_refined_preview.json", {"questions": merged_questions})
    manifest = build_backend_aligned(out_dir, merged_questions, parser.assets, parser.image_insertions, release, config)
    contract = validate_manifest(manifest, out_dir)
    preview_path = render_preview(manifest, out_dir)
    pipeline_summary = {
        "schema_version": "docx_native_pipeline_run_summary.v0.1",
        "status": "ok" if contract["status"] == "ok" else "needs_review",
        "source_docx": str(docx_path),
        "out_dir": str(out_dir),
        "counts": {**parse_summary, "questions": len(questions), "model_refine_tasks": len(prompt_pack.get("tasks", [])), "contract_failed_task_count": contract["failed_task_count"]},
        "model_refine": model_summary,
        "artifacts": {
            "summary": str(out_dir / "summary.json"),
            "backend_manifest": str(out_dir / "backend_aligned_v01" / "docx_native_backend_aligned_question_asset_manifest.json"),
            "contract_check": str(out_dir / "backend_aligned_v01" / "docx_native_backend_contract_check.json"),
            "preview_html": str(preview_path),
        },
        "runtime_imported": False,
        "database_written": False,
    }
    write_json(out_dir / "pipeline_summary.json", pipeline_summary)
    return pipeline_summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DOCX native-first ingest pipeline v0.1")
    p.add_argument("--docx", required=True, type=Path)
    p.add_argument("--config", default=Path("config/docx_native_pipeline_v01.yaml"), type=Path)
    p.add_argument("--run-id", default="")
    p.add_argument("--clean", action="store_true")
    p.add_argument("--skip-model", action="store_true")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--model-limit", type=int, default=None, help="0 means no model tasks; omit for all tasks")
    return p.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_pipeline(parse_args()), ensure_ascii=False, indent=2))
