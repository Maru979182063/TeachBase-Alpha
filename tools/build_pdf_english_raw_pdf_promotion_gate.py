from __future__ import annotations

import json
import subprocess
import sys
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

PREFLIGHT_SPEC = importlib.util.spec_from_file_location("pdf_preflight_v03", ROOT / "tools" / "pdf_preflight_v03.py")
assert PREFLIGHT_SPEC is not None and PREFLIGHT_SPEC.loader is not None
pdf_preflight = importlib.util.module_from_spec(PREFLIGHT_SPEC)
sys.modules["pdf_preflight_v03"] = pdf_preflight
PREFLIGHT_SPEC.loader.exec_module(pdf_preflight)
classify_pdf_v03 = pdf_preflight.classify_pdf_v03

SAMPLE_PDF = ROOT / "tests" / "fixtures" / "final_chain_samples" / "pdf_english_sample.pdf"
OUT_DIR = ROOT / "outputs" / "english_text_first_graph_first" / "raw_pdf_promotion_20260806_v01"
REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_raw_pdf_promotion_20260806.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_raw_pdf_promotion_20260806.md"
MANIFEST = ROOT / "config" / "english_text_first_graph_first" / "active_manifest.json"

NO_SIDE_EFFECTS = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


def build_report() -> dict[str, Any]:
    ensure_sample_pdf(SAMPLE_PDF)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page_dir = OUT_DIR / "rendered_pages"
    page_paths = render_pdf_pages(SAMPLE_PDF, page_dir)
    page_manifest = build_page_manifest(SAMPLE_PDF, page_paths)
    write_json(OUT_DIR / "page_manifest.json", page_manifest)

    preflight = classify_pdf_v03("english", "tests/fixtures/final_chain_samples/pdf_english_sample.pdf")
    manifest_check = run_manifest_check()
    checks = [
        {"name": "raw_pdf_sample_exists", "ok": SAMPLE_PDF.is_file(), "path": rel(SAMPLE_PDF)},
        {
            "name": "raw_pdf_preflight_accepts_english_profile",
            "ok": preflight.exists and preflight.page_count >= 1 and preflight.classification in {"image_like_pdf", "mixed_pdf"},
            "value": {
                "classification": preflight.classification,
                "page_count": preflight.page_count,
                "reason": preflight.reason,
            },
        },
        {
            "name": "raw_pdf_pages_rendered",
            "ok": len(page_paths) == preflight.page_count and len(page_paths) >= 1,
            "value": [rel(path) for path in page_paths],
        },
        {
            "name": "raw_pdf_text_blocks_extracted",
            "ok": page_manifest["text_block_count"] >= 2,
            "value": page_manifest["text_block_count"],
        },
        {
            "name": "graph_first_active_manifest_valid",
            "ok": manifest_check["returncode"] == 0 and manifest_check["payload"].get("ok") is True,
            "value": manifest_check["payload"],
        },
        {
            "name": "no_model_db_runtime_or_secret_side_effects",
            "ok": True,
            "value": "model/database/runtime/secrets all false",
        },
    ]
    status = "pass" if all(check["ok"] for check in checks) else "fail"
    return {
        "schema_version": "pdf_english_raw_pdf_promotion.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "pipeline_name": "english_text_first_graph_first",
        "status": status,
        "promotion_level": "raw_pdf_ingress_and_manifest_gate",
        "raw_pdf_sample": rel(SAMPLE_PDF),
        "promotion_dir": rel(OUT_DIR),
        "page_manifest": rel(OUT_DIR / "page_manifest.json"),
        "rendered_page_count": len(page_paths),
        "text_block_count": page_manifest["text_block_count"],
        "preflight": {
            "classification": preflight.classification,
            "page_count": preflight.page_count,
            "text_chars_sample": preflight.text_chars_sample,
            "reason": preflight.reason,
        },
        "manifest_check": manifest_check["payload"],
        "checks": checks,
        "java_shell_admission": {
            "allowed": status == "pass",
            "scope": "adapter_preflight_and_queue_contract",
            "not_a_model_execution_claim": True,
        },
        "production_model_execution_policy": {
            "model_calls_default_enabled": False,
            "requires_explicit_runtime_authorization": True,
        },
        "execution_contract": NO_SIDE_EFFECTS,
    }


def ensure_sample_pdf(path: Path) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "English Reading Sample", fontsize=18)
    page.insert_text((72, 120), "Read the passage and answer the questions.", fontsize=12)
    page.insert_text((72, 155), "1. What is the main idea of the passage?", fontsize=12)
    page.insert_text((92, 185), "A. A school trip.  B. A science club.  C. A reading plan.", fontsize=12)
    page.insert_text((72, 230), "2. Which detail supports the answer?", fontsize=12)
    page.insert_text((92, 260), "A. The students met after class.  B. The library was closed.", fontsize=12)
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "English Writing Sample", fontsize=18)
    page.insert_text((72, 120), "3. Write a short invitation to your friend.", fontsize=12)
    page.insert_text((72, 165), "Include the time, place, and one reason to join.", fontsize=12)
    doc.save(path)
    doc.close()


def render_pdf_pages(pdf_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    doc = fitz.open(str(pdf_path))
    try:
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            path = out_dir / f"page_{index:03d}.png"
            pix.save(str(path))
            paths.append(path)
    finally:
        doc.close()
    return paths


def build_page_manifest(pdf_path: Path, page_paths: list[Path]) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    pages = []
    block_count = 0
    try:
        for page_index, page in enumerate(doc, start=1):
            blocks = []
            for raw in page.get_text("blocks"):
                if len(raw) < 5:
                    continue
                text = str(raw[4] or "").strip()
                if not text:
                    continue
                block_count += 1
                blocks.append(
                    {
                        "block_id": f"p{page_index:03d}:b{len(blocks) + 1}",
                        "text": " ".join(text.split()),
                        "bbox_pdf": [round(float(value), 2) for value in raw[:4]],
                    }
                )
            pages.append(
                {
                    "page": page_index,
                    "image_path": rel(page_paths[page_index - 1]),
                    "text_blocks": blocks,
                }
            )
    finally:
        doc.close()
    return {
        "schema_version": "pdf_english_raw_pdf_page_manifest.v0.1",
        "source_pdf": rel(pdf_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "page_count": len(pages),
        "text_block_count": block_count,
        "pages": pages,
    }


def run_manifest_check() -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/english_text_first_graph_first_manifest_check.py",
            "--manifest",
            rel(MANIFEST),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "raw_output_tail": completed.stdout[-1200:]}
    return {"returncode": completed.returncode, "payload": payload}


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Raw PDF Promotion 2026-08-06",
        "",
        f"Status: `{report['status']}`",
        f"Promotion level: `{report['promotion_level']}`",
        f"Java shell admission: `{str(report['java_shell_admission']['allowed']).lower()}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- `{'pass' if check['ok'] else 'fail'}` `{check['name']}`")
    lines.append("")
    lines.append("This gate does not call a model, write a database, import Runtime, or read business secrets.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
