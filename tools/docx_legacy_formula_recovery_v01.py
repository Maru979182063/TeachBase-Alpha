from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


DEFAULT_OUT_ROOT = Path("outputs/docx_legacy_formula_recovery_v0_1")

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "o": "urn:schemas-microsoft-com:office:office",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def qn(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def lname(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def safe_slug(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return (cleaned or "docx")[:limit]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_relationships(zf: zipfile.ZipFile) -> dict[str, str]:
    path = "word/_rels/document.xml.rels"
    if path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(path))
    rels: dict[str, str] = {}
    for rel in root.findall("rel:Relationship", NS):
        rid = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if rid:
            rels[rid] = target
    return rels


def resolve_word_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if normalized.startswith("/"):
        return normalized.lstrip("/")
    if normalized.startswith("word/"):
        return normalized
    return f"word/{normalized}"


def extract_ole_entries(docx_path: Path, out_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    embeddings_dir = out_dir / "embeddings"
    embeddings_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(docx_path) as zf:
        names = set(zf.namelist())
        rels = parse_relationships(zf)
        root = ET.fromstring(zf.read("word/document.xml"))
        omml_count = len(root.findall(".//m:oMath", NS)) + len(root.findall(".//m:oMathPara", NS))
        seen: set[str] = set()
        for ole in root.findall(".//o:OLEObject", NS):
            rid = ole.attrib.get(qn("r", "id"), "")
            target = rels.get(rid, "")
            zip_path = resolve_word_target(target) if target else ""
            entry: dict[str, Any] = {
                "ole_rid": rid,
                "target": target,
                "zip_path": zip_path,
                "ole_object": Path(zip_path).name if zip_path else "",
                "status": "found",
            }
            if not rid:
                entry["status"] = "missing_rid"
                entries.append(entry)
                continue
            if rid in seen:
                entry["status"] = "duplicate_reference_skipped"
                entries.append(entry)
                continue
            seen.add(rid)
            if not zip_path or zip_path not in names:
                entry["status"] = "embedding_not_found"
                entries.append(entry)
                continue
            data = zf.read(zip_path)
            local_name = f"{rid}_{Path(zip_path).name}"
            local_path = embeddings_dir / local_name
            local_path.write_bytes(data)
            entry.update(
                {
                    "status": "extracted",
                    "local_path": str(local_path),
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
            entries.append(entry)
    counts = {
        "omml_elements": omml_count,
        "ole_objects_in_document_xml": sum(1 for e in entries if e.get("ole_rid")),
        "unique_ole_rids": len({e.get("ole_rid") for e in entries if e.get("ole_rid")}),
        "extracted_ole_embeddings": sum(1 for e in entries if e.get("status") == "extracted"),
    }
    return entries, counts


def run_json_child(cmd: list[str], cwd: Path, input_payload: dict[str, Any], input_path: Path, log_path: Path) -> dict[str, Any]:
    write_json(input_path, input_payload)
    result = subprocess.run(cmd + [str(input_path)], cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True)
    write_json(
        log_path,
        {
            "cmd": cmd + [str(input_path)],
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    if result.returncode != 0:
        raise RuntimeError(f"child command failed: {' '.join(cmd)}; see {log_path}")
    return json.loads(result.stdout)


def convert_mathml_to_latex(
    *,
    repo_root: Path,
    out_dir: Path,
    mathml_records: list[dict[str, Any]],
    node_module_dir: Path | None,
) -> dict[str, Any]:
    env = os.environ.copy()
    if node_module_dir:
        env["MATHML_TO_LATEX_NODE_MODULE_DIR"] = str(node_module_dir.resolve())
    input_path = out_dir / "mathml_to_latex_input.json"
    write_json(input_path, {"records": mathml_records})
    node_cmd = ["node", "tools/mathml_to_latex_batch.cjs", str(input_path)]
    result = subprocess.run(node_cmd, cwd=repo_root, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    write_json(
        out_dir / "mathml_to_latex_child_log.json",
        {
            "cmd": node_cmd,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "node_module_dir": str(node_module_dir) if node_module_dir else "",
        },
    )
    if result.returncode != 0:
        return {
            "schema_version": "docx_legacy_mtef_latex_batch.v0.1",
            "backend": "node:mathml-to-latex",
            "converter_available": False,
            "records": [
                {
                    "ole_rid": item.get("ole_rid"),
                    "ole_object": item.get("ole_object"),
                    "status": "mathml_to_latex_child_failed",
                    "latex": None,
                    "latex_clean": None,
                    "error": result.stderr or result.stdout,
                }
                for item in mathml_records
            ],
        }
    return json.loads(result.stdout)


def build_manifest(
    *,
    docx_path: Path,
    extracted_entries: list[dict[str, Any]],
    mathml_batch: dict[str, Any],
    latex_batch: dict[str, Any],
) -> dict[str, Any]:
    by_rid_mathml = {str(item.get("ole_rid")): item for item in mathml_batch.get("records") or []}
    by_rid_latex = {str(item.get("ole_rid")): item for item in latex_batch.get("records") or []}
    formulas: list[dict[str, Any]] = []
    for index, entry in enumerate([e for e in extracted_entries if e.get("status") == "extracted"], start=1):
        rid = str(entry.get("ole_rid") or "")
        mathml_item = by_rid_mathml.get(rid, {})
        latex_item = by_rid_latex.get(rid, {})
        latex = latex_item.get("latex_clean") or latex_item.get("latex") or ""
        status = "ok" if latex else str(latex_item.get("status") or mathml_item.get("status") or "formula_recovery_incomplete")
        formulas.append(
            {
                "formula_id": f"legacy_mtef_{index:04d}",
                "source": "legacy_equation_mtef",
                "ole_rid": rid,
                "ole_object": entry.get("ole_object"),
                "target": entry.get("target"),
                "embedding_sha256": entry.get("sha256"),
                "status": status,
                "mathml_status": mathml_item.get("status"),
                "latex_status": latex_item.get("status"),
                "mathml": mathml_item.get("mathml") or "",
                "latex": latex,
                "latex_raw": latex_item.get("latex") or "",
                "normalization_actions": latex_item.get("normalization_actions") or [],
                "error": latex_item.get("error") or mathml_item.get("error") or "",
            }
        )
    ok = sum(1 for item in formulas if item.get("status") == "ok")
    return {
        "schema_version": "formula_manifest_backend_preview.v0.1",
        "source_docx": str(docx_path),
        "source": "docx_legacy_formula_recovery_v01",
        "total": len(formulas),
        "mathml_ok": sum(1 for item in formulas if item.get("mathml_status") == "mathml_ok"),
        "latex_ok": ok,
        "failed": len(formulas) - ok,
        "formulas": formulas,
    }


def render_report_html(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    rows = []
    for item in manifest.get("formulas", [])[:200]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('formula_id','')))}</td>"
            f"<td>{html.escape(str(item.get('ole_rid','')))}</td>"
            f"<td>{html.escape(str(item.get('status','')))}</td>"
            f"<td><code>{html.escape(str(item.get('latex') or item.get('error') or '')[:300])}</code></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX legacy formula recovery</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#111827}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border:1px solid #d1d5db;padding:6px;vertical-align:top}}
code{{white-space:pre-wrap}}
.bad{{color:#b91c1c}} .ok{{color:#047857}}
</style>
<h1>DOCX legacy formula recovery</h1>
<p>status=<b class="{ 'ok' if report.get('status') == 'ok' else 'bad' }">{report.get('status')}</b>
 · omml={report.get('counts',{}).get('omml_elements')}
 · ole={report.get('counts',{}).get('extracted_ole_embeddings')}
 · latex_ok={manifest.get('latex_ok')}
 · failed={manifest.get('failed')}</p>
<table><thead><tr><th>formula_id</th><th>ole_rid</th><th>status</th><th>latex/error</th></tr></thead><tbody>
{''.join(rows)}
</tbody></table>
"""


def recover(docx_path: Path, out_root: Path, run_id: str, node_module_dir: Path | None, clean: bool) -> dict[str, Any]:
    repo_root = Path.cwd()
    doc_out = out_root / run_id / safe_slug(docx_path.stem)
    if clean and doc_out.exists():
        shutil.rmtree(doc_out)
    doc_out.mkdir(parents=True, exist_ok=True)

    entries, counts = extract_ole_entries(docx_path, doc_out)
    ruby_input = {
        "files": [
            {
                "ole_rid": entry.get("ole_rid"),
                "ole_object": entry.get("ole_object"),
                "path": entry.get("local_path"),
            }
            for entry in entries
            if entry.get("status") == "extracted"
        ]
    }
    ruby_batch = run_json_child(
        ["ruby", "tools/ruby_mtef_to_mathml_batch.rb"],
        repo_root,
        ruby_input,
        doc_out / "mtef_to_mathml_input.json",
        doc_out / "mtef_to_mathml_child_log.json",
    )
    write_json(doc_out / "mtef_mathml_raw.json", ruby_batch)

    latex_batch = convert_mathml_to_latex(
        repo_root=repo_root,
        out_dir=doc_out,
        mathml_records=list(ruby_batch.get("records") or []),
        node_module_dir=node_module_dir,
    )
    write_json(doc_out / "mtef_latex_batch.json", latex_batch)

    manifest = build_manifest(
        docx_path=docx_path,
        extracted_entries=entries,
        mathml_batch=ruby_batch,
        latex_batch=latex_batch,
    )
    write_json(doc_out / "formula_manifest_backend_preview.json", manifest)

    status = "ok" if manifest.get("failed") == 0 else "formula_recovery_incomplete"
    report = {
        "schema_version": "docx_legacy_formula_recovery_report.v0.1",
        "run_id": run_id,
        "source_docx": str(docx_path),
        "status": status,
        "counts": {
            **counts,
            "mathml_ok": manifest.get("mathml_ok"),
            "latex_ok": manifest.get("latex_ok"),
            "failed": manifest.get("failed"),
        },
        "route_decision": {
            "omml_native_available": counts.get("omml_elements", 0) > 0,
            "legacy_ole_detected": counts.get("extracted_ole_embeddings", 0) > 0,
            "legacy_ole_manifest_ready": manifest.get("failed") == 0 and manifest.get("total", 0) > 0,
            "fallback_needed": manifest.get("failed", 0) > 0,
            "fallback_signal": "image_or_pdf_formula_fallback_needed" if manifest.get("failed", 0) > 0 else "",
        },
        "artifacts": {
            "formula_manifest": str(doc_out / "formula_manifest_backend_preview.json"),
            "recovery_report": str(doc_out / "legacy_formula_recovery_report.json"),
            "mathml_raw": str(doc_out / "mtef_mathml_raw.json"),
            "latex_batch": str(doc_out / "mtef_latex_batch.json"),
            "embeddings_dir": str(doc_out / "embeddings"),
        },
        "entries": entries,
    }
    write_json(doc_out / "legacy_formula_recovery_report.json", report)
    (doc_out / "index.html").write_text(render_report_html(report, manifest), encoding="utf-8")
    return report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--mathml-node-module-dir", type=Path, default=None)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    report = recover(
        docx_path=args.docx.resolve(),
        out_root=args.out_root,
        run_id=args.run_id,
        node_module_dir=args.mathml_node_module_dir,
        clean=args.clean,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
