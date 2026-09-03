from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from docx_legacy_formula_recovery_v01 import safe_slug


DEFAULT_OUT_ROOT = Path("outputs/docx_native_stage0_router_v0_1")
DEFAULT_LEGACY_FORMULA_MISSING_TOLERANCE = 50

NS = {
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "o": "urn:schemas-microsoft-com:office:office",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_process_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path.resolve())


def inspect_docx_formula_sources(docx_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(docx_path) as zf:
        names = set(zf.namelist())
        root = ET.fromstring(zf.read("word/document.xml"))
        omml_count = len(root.findall(".//m:oMath", NS)) + len(root.findall(".//m:oMathPara", NS))
        ole_count = len(root.findall(".//o:OLEObject", NS))
        media_count = sum(1 for name in names if name.startswith("word/media/") and not name.endswith("/"))
        embedding_count = sum(1 for name in names if name.startswith("word/embeddings/") and not name.endswith("/"))
    return {
        "omml_elements": omml_count,
        "ole_objects": ole_count,
        "embedding_files": embedding_count,
        "native_media": media_count,
    }


def run_child(cmd: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> dict[str, Any]:
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True)
    stdout = decode_process_bytes(result.stdout or b"")
    stderr = decode_process_bytes(result.stderr or b"")
    write_json(
        log_path,
        {
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    )
    if result.returncode != 0:
        return {
            "status": "child_failed",
            "returncode": result.returncode,
            "log_path": str(log_path),
            "stderr": stderr[-4000:],
        }
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"status": "non_json_stdout", "raw_stdout": stdout, "log_path": str(log_path)}


def find_stage0_out_dir(stage0_summary: dict[str, Any]) -> Path:
    out = stage0_summary.get("out_dir")
    if not out:
        raise RuntimeError("Stage0 summary did not include out_dir")
    return Path(out)


def resolve_mathml_node_module_dir(value: Path | None) -> Path | None:
    candidates: list[Path] = []
    if value:
        candidates.append(value)
    env_value = os.environ.get("MATHML_TO_LATEX_NODE_MODULE_DIR")
    if env_value:
        candidates.append(Path(env_value))
    candidates.extend(
        [
            Path("node_modules"),
        ]
    )
    for candidate in candidates:
        if (candidate / "node_modules" / "mathml-to-latex").exists() or (candidate / "package.json").exists():
            return candidate
    return value


def mathml_to_latex_available(repo_root: Path, node_module_dir: Path | None) -> dict[str, Any]:
    env = os.environ.copy()
    if node_module_dir:
        env["MATHML_TO_LATEX_NODE_MODULE_DIR"] = str(node_module_dir.resolve())
    script = (
        "const paths=[];"
        "if(process.env.MATHML_TO_LATEX_NODE_MODULE_DIR) paths.push(process.env.MATHML_TO_LATEX_NODE_MODULE_DIR);"
        "paths.push(process.cwd());"
        "let resolved='';"
        "for (const base of paths) {"
        "  try { resolved=require.resolve('mathml-to-latex',{paths:[base]}); break; } catch(e) {}"
        "}"
        "if(!resolved){process.exit(1);}"
        "process.stdout.write(resolved);"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=repo_root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return {
        "available": result.returncode == 0,
        "resolved_path": result.stdout.strip() if result.returncode == 0 else "",
        "error": (result.stderr or result.stdout or "").strip() if result.returncode != 0 else "",
        "node_module_dir": str(node_module_dir) if node_module_dir else "",
    }


def render_html(summary: dict[str, Any]) -> str:
    counts = summary.get("stage0_counts") or {}
    route = summary.get("route_decision") or {}
    artifacts = summary.get("artifacts") or {}

    def row(key: str, value: Any) -> str:
        return f"<tr><th>{html.escape(key)}</th><td>{html.escape(str(value))}</td></tr>"

    rows = []
    for key, value in {**(summary.get("source_probe") or {}), **counts, **route}.items():
        rows.append(row(key, value))
    links = []
    for key, value in artifacts.items():
        if value:
            links.append(f"<li>{html.escape(key)}: <code>{html.escape(str(value))}</code></li>")
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX native Stage0 router</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#111827}}
table{{border-collapse:collapse;min-width:760px}}td,th{{border:1px solid #d1d5db;padding:8px;text-align:left}}
code{{white-space:pre-wrap}}.ok{{color:#047857}}.bad{{color:#b91c1c}}
</style>
<h1>DOCX native Stage0 router</h1>
<p>status=<b class="{ 'ok' if summary.get('status') == 'ok' else 'bad' }">{html.escape(str(summary.get('status')))}</b></p>
<table>{''.join(rows)}</table>
<h2>Artifacts</h2>
<ul>{''.join(links)}</ul>
"""


def build_handoff_manifest(
    *,
    summary: dict[str, Any],
    doc_out: Path,
    stage0_summary: dict[str, Any],
    manifest_path: str,
) -> dict[str, Any]:
    route = summary.get("route_decision") or {}
    artifacts = summary.get("artifacts") or {}
    counts = summary.get("stage0_counts") or {}
    fallback_needed = bool(route.get("fallback_needed"))
    hard_fallback_reasons: list[str] = []
    repairable_formula_reasons: list[str] = []
    missing_legacy = int(counts.get("legacy_ole_embeddings") or 0) - int(counts.get("legacy_mtef_tokens") or 0)
    tolerance = int(route.get("legacy_formula_missing_tolerance") or DEFAULT_LEGACY_FORMULA_MISSING_TOLERANCE)
    legacy_gap_is_tolerable = 0 < missing_legacy <= tolerance
    if missing_legacy > tolerance:
        hard_fallback_reasons.append("legacy_formula_recovery_incomplete")
    elif legacy_gap_is_tolerable:
        repairable_formula_reasons.append("legacy_formula_recovery_incomplete_tolerated")
    if route.get("legacy_formula_recovery_status") in {"child_failed", "non_json_stdout"}:
        hard_fallback_reasons.append(f"legacy_formula_recovery_status:{route.get('legacy_formula_recovery_status')}")
    elif route.get("legacy_formula_recovery_status") == "formula_recovery_incomplete":
        if legacy_gap_is_tolerable:
            repairable_formula_reasons.append(f"legacy_formula_recovery_status:{route.get('legacy_formula_recovery_status')}")
        else:
            hard_fallback_reasons.append(f"legacy_formula_recovery_status:{route.get('legacy_formula_recovery_status')}")
    if route.get("mathml_to_latex_dependency_available") is False:
        hard_fallback_reasons.append("mathml_to_latex_dependency_missing")
    if int(counts.get("needs_review_blocks") or 0) > 0:
        repairable_formula_reasons.append("stage0_needs_review_blocks")
    if str(counts.get("audit_status") or "") not in {"", "ok"}:
        repairable_formula_reasons.append(f"formula_audit_status:{counts.get('audit_status')}")
    hard_fallback_required = fallback_needed or bool(hard_fallback_reasons)
    repairable_formula_risk = bool(repairable_formula_reasons)
    may_enter_native = not hard_fallback_required
    handoff_status = (
        "NEEDS_FORMULA_FALLBACK"
        if hard_fallback_required
        else "READY_FOR_BLOCK_TAGGER_WITH_FORMULA_RISK"
        if repairable_formula_risk
        else "READY_FOR_BLOCK_TAGGER"
    )
    fallback_reasons = hard_fallback_reasons + repairable_formula_reasons
    return {
        "schema_version": "docx_native_stage0_handoff_manifest.v0.1",
        "source_docx": summary.get("source_docx", ""),
        "source_pipeline_id": "docx_native_stage0_router_v01",
        "status": handoff_status,
        "routing_contract": {
            "may_enter_native_block_tagger": may_enter_native,
            "must_not_enter_native_block_tagger": hard_fallback_required,
            "required_next_action": "image_or_pdf_formula_fallback" if hard_fallback_required else "native_block_tagger",
            "fallback_reasons": fallback_reasons,
            "hard_fallback_reasons": hard_fallback_reasons,
            "repairable_formula_reasons": repairable_formula_reasons,
            "repairable_formula_risk": repairable_formula_risk,
            "legacy_formula_missing_count": missing_legacy,
            "legacy_formula_missing_tolerance": tolerance,
        },
        "next_node_inputs": {
            "docx_native_block_tagger_v01": {
                "paragraph_stream": artifacts.get("stage0_paragraph_stream", ""),
                "raw_paragraph_stream": artifacts.get("stage0_raw_paragraph_stream", ""),
                "asset_manifest": artifacts.get("stage0_asset_manifest", ""),
            },
            "image_or_pdf_formula_fallback": {
                "enabled": hard_fallback_required,
                "fallback_signal": route.get("fallback_signal", ""),
                "source_docx": summary.get("source_docx", ""),
            },
        },
        "fallback_jobs": [
            {
                "job_id": "formula_visual_fallback_001",
                "status": "PENDING_IMPLEMENTED_RUNNER",
                "fallback_type": "image_or_pdf_formula_fallback",
                "source_docx": summary.get("source_docx", ""),
                "reason_codes": hard_fallback_reasons,
                "blocked_native_artifacts": {
                    "paragraph_stream": artifacts.get("stage0_paragraph_stream", ""),
                    "raw_paragraph_stream": artifacts.get("stage0_raw_paragraph_stream", ""),
                    "formula_audit": artifacts.get("stage0_formula_audit", ""),
                },
                "handoff_policy": "Native downstream is blocked until this fallback produces trustworthy formula text or the run is explicitly resumed with --stage0-fallback-policy allow.",
            }
        ]
        if hard_fallback_required
        else [],
        "formula_inputs": {
            "formula_manifest": str(manifest_path or ""),
            "formula_audit": artifacts.get("stage0_formula_audit", ""),
        },
        "quality_gate": {
            "stage0_audit_status": (summary.get("stage0_counts") or {}).get("audit_status"),
            "stage0_audit_issue_count": (summary.get("stage0_counts") or {}).get("audit_issue_count"),
            "needs_review_blocks": (summary.get("stage0_counts") or {}).get("needs_review_blocks"),
            "fallback_needed": hard_fallback_required,
            "repairable_formula_risk": repairable_formula_risk,
            "repairable_formula_reasons": repairable_formula_reasons,
            "legacy_formula_missing_count": missing_legacy,
            "legacy_formula_missing_tolerance": tolerance,
        },
        "artifacts": {
            "router_summary": rel(doc_out / "router_summary.json"),
            "router_review": rel(doc_out / "index.html"),
            "handoff_manifest": rel(doc_out / "handoff_manifest.json"),
            "stage0_preview_html": stage0_summary.get("artifacts", {}).get("preview_html", ""),
            "run_math_normalization_report": artifacts.get("run_math_normalization_report", ""),
            "run_math_normalization_preview": artifacts.get("run_math_normalization_preview", ""),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path.cwd()
    docx_path = args.docx.resolve()
    doc_out = Path(args.out_root) / args.run_id / safe_slug(docx_path.stem)
    if args.clean and doc_out.exists():
        shutil.rmtree(doc_out)
    doc_out.mkdir(parents=True, exist_ok=True)
    log_dir = doc_out / "child_logs"

    source_probe = inspect_docx_formula_sources(docx_path)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    mathml_node_module_dir = resolve_mathml_node_module_dir(args.mathml_node_module_dir)
    mathml_converter = mathml_to_latex_available(repo_root, mathml_node_module_dir)
    if (source_probe["ole_objects"] > 0 or source_probe["embedding_files"] > 0) and not mathml_converter["available"]:
        summary = {
            "schema_version": "docx_native_stage0_router_summary.v0.1",
            "run_id": args.run_id,
            "source_docx": str(docx_path),
            "status": "needs_review",
            "source_probe": source_probe,
            "route_decision": {
                "omml_native_available": source_probe["omml_elements"] > 0,
                "legacy_ole_detected": True,
                "legacy_formula_recovery_status": "blocked_dependency_missing",
                "mathml_node_module_dir": str(mathml_node_module_dir) if mathml_node_module_dir else "",
                "mathml_to_latex_dependency_available": False,
                "mathml_to_latex_dependency_error": mathml_converter.get("error", ""),
                "legacy_manifest_attached": False,
                "fallback_needed": True,
                "fallback_signal": "mathml_to_latex_dependency_missing",
            },
            "stage0_counts": {
                "paragraphs": None,
                "tables": None,
                "native_media": source_probe["native_media"],
                "image_insertions": None,
                "formula_elements": None,
                "legacy_ole_embeddings": source_probe["embedding_files"],
                "legacy_mtef_manifest_formulas": 0,
                "legacy_mtef_tokens": 0,
                "inline_glyph_assets": None,
                "inline_glyph_blocks": None,
                "needs_review_blocks": None,
                "loss_flag_counts": {"mathml_to_latex_dependency_missing": source_probe["embedding_files"]},
                "audit_status": "not_run_dependency_missing",
                "audit_issue_count": source_probe["embedding_files"],
                "run_math_normalizer_changed_blocks": 0,
                "run_math_normalizer_actions": 0,
                "run_math_normalizer_skipped_blocks": 0,
                "run_math_normalizer_status": "not_run_dependency_missing",
            },
            "artifacts": {
                "router_summary": rel(doc_out / "router_summary.json"),
                "router_review": rel(doc_out / "index.html"),
                "formula_recovery_report": "",
                "formula_manifest": "",
                "stage0_paragraph_stream": "",
                "stage0_raw_paragraph_stream": "",
                "stage0_asset_manifest": "",
                "stage0_formula_audit": "",
                "stage0_preview_html": "",
                "run_math_normalized_stream": "",
                "run_math_normalization_report": "",
                "run_math_normalization_preview": "",
            },
            "no_runtime_import": True,
            "no_database_write": True,
        }
        write_json(doc_out / "router_summary.json", summary)
        handoff = build_handoff_manifest(summary=summary, doc_out=doc_out, stage0_summary={}, manifest_path="")
        write_json(doc_out / "handoff_manifest.json", handoff)
        summary["artifacts"]["handoff_manifest"] = rel(doc_out / "handoff_manifest.json")
        write_json(doc_out / "router_summary.json", summary)
        (doc_out / "index.html").write_text(render_html(summary), encoding="utf-8")
        return summary
    manifest_path = ""
    recovery_report: dict[str, Any] | None = None
    recovery_status = "not_needed"

    if source_probe["ole_objects"] > 0 or source_probe["embedding_files"] > 0:
        recovery_run_id = f"{args.run_id}__formula_recovery"
        recovery_cmd = [
            sys.executable,
            "tools/docx_legacy_formula_recovery_v01.py",
            "--docx",
            str(docx_path),
            "--run-id",
            recovery_run_id,
            "--out-root",
            "outputs/docx_legacy_formula_recovery_v0_1",
            "--clean",
        ]
        if mathml_node_module_dir:
            recovery_cmd.extend(["--mathml-node-module-dir", str(mathml_node_module_dir)])
        recovery_report = run_child(recovery_cmd, repo_root, env, log_dir / "formula_recovery.json")
        recovery_status = str(recovery_report.get("status") or "unknown")
        manifest_path = str(((recovery_report.get("artifacts") or {}).get("formula_manifest") or ""))

    stage0_run_id = f"{args.run_id}__stage0"
    stage0_cmd = [
        sys.executable,
        "tools/docx_native_formula_token_stream_v01.py",
        "--docx",
        str(docx_path),
        "--run-id",
        stage0_run_id,
        "--clean",
    ]
    if manifest_path and Path(manifest_path).exists():
        stage0_cmd.extend(["--formula-manifest", manifest_path])
    stage0_summary = run_child(stage0_cmd, repo_root, env, log_dir / "stage0_token_stream.json")
    stage0_out_dir = find_stage0_out_dir(stage0_summary) if stage0_summary.get("out_dir") else Path()
    audit_path = stage0_out_dir / "formula_token_audit.json" if stage0_out_dir else Path()
    audit = read_json(audit_path) if audit_path.exists() else {}
    raw_paragraph_stream = str(stage0_summary.get("artifacts", {}).get("paragraph_stream", "") or "")
    normalized_paragraph_stream = raw_paragraph_stream
    run_math_summary: dict[str, Any] = {"status": "not_run"}
    run_math_report_path = ""
    run_math_preview_path = ""
    if raw_paragraph_stream and Path(raw_paragraph_stream).exists():
        run_math_cmd = [
            sys.executable,
            "tools/docx_run_math_normalizer_v01.py",
            "--input-block-stream",
            raw_paragraph_stream,
            "--output-root",
            "outputs/docx_run_math_normalizer_v0_1",
            "--run-id",
            f"{args.run_id}__run_math_normalizer",
            "--probe-html",
        ]
        run_math_summary = run_child(run_math_cmd, repo_root, env, log_dir / "run_math_normalizer.json")
        run_math_artifacts = run_math_summary.get("artifacts") or {}
        candidate_stream = str(run_math_artifacts.get("normalized_stream") or "")
        if candidate_stream and Path(candidate_stream).exists():
            normalized_paragraph_stream = candidate_stream
        run_math_report_path = str(run_math_artifacts.get("normalization_report") or "")
        run_math_preview_path = str(run_math_artifacts.get("preview_html") or "")

    missing_legacy = int(stage0_summary.get("legacy_ole_embeddings") or 0) - int(stage0_summary.get("legacy_mtef_tokens") or 0)
    legacy_missing_tolerance = DEFAULT_LEGACY_FORMULA_MISSING_TOLERANCE
    fallback_needed = missing_legacy > legacy_missing_tolerance or recovery_status in {"child_failed", "non_json_stdout"}
    fallback_signal = "image_or_pdf_formula_fallback_needed" if fallback_needed else ""
    run_math_failed = run_math_summary.get("status") in {"child_failed", "non_json_stdout"}
    status = "ok" if not fallback_needed and not run_math_failed and stage0_summary.get("needs_review_blocks") == 0 else "needs_review"

    summary = {
        "schema_version": "docx_native_stage0_router_summary.v0.1",
        "run_id": args.run_id,
        "source_docx": str(docx_path),
        "status": status,
        "source_probe": source_probe,
        "route_decision": {
            "omml_native_available": source_probe["omml_elements"] > 0,
            "legacy_ole_detected": source_probe["ole_objects"] > 0 or source_probe["embedding_files"] > 0,
            "legacy_formula_recovery_status": recovery_status,
            "legacy_formula_missing_count": missing_legacy,
            "legacy_formula_missing_tolerance": legacy_missing_tolerance,
            "mathml_node_module_dir": str(mathml_node_module_dir) if mathml_node_module_dir else "",
            "legacy_manifest_attached": bool(manifest_path and Path(manifest_path).exists()),
            "fallback_needed": fallback_needed,
            "fallback_signal": fallback_signal,
        },
        "stage0_counts": {
            "paragraphs": stage0_summary.get("paragraphs"),
            "tables": stage0_summary.get("tables"),
            "native_media": stage0_summary.get("native_media"),
            "image_insertions": stage0_summary.get("image_insertions"),
            "formula_elements": stage0_summary.get("formula_elements"),
            "legacy_ole_embeddings": stage0_summary.get("legacy_ole_embeddings"),
            "legacy_mtef_manifest_formulas": stage0_summary.get("legacy_mtef_manifest_formulas"),
            "legacy_mtef_tokens": stage0_summary.get("legacy_mtef_tokens"),
            "inline_glyph_assets": stage0_summary.get("inline_glyph_assets"),
            "inline_glyph_blocks": stage0_summary.get("inline_glyph_blocks"),
            "needs_review_blocks": stage0_summary.get("needs_review_blocks"),
            "loss_flag_counts": stage0_summary.get("loss_flag_counts"),
            "audit_status": audit.get("status"),
            "audit_issue_count": audit.get("issue_count"),
            "run_math_normalizer_changed_blocks": run_math_summary.get("changed_block_count"),
            "run_math_normalizer_actions": run_math_summary.get("action_count"),
            "run_math_normalizer_skipped_blocks": run_math_summary.get("skipped_block_count"),
            "run_math_normalizer_status": run_math_summary.get("status", "ok" if run_math_summary.get("run_id") else "not_run"),
        },
        "artifacts": {
            "router_summary": rel(doc_out / "router_summary.json"),
            "router_review": rel(doc_out / "index.html"),
            "formula_recovery_report": rel(Path((recovery_report or {}).get("artifacts", {}).get("recovery_report", ""))) if recovery_report else "",
            "formula_manifest": rel(Path(manifest_path)) if manifest_path else "",
            "stage0_paragraph_stream": normalized_paragraph_stream,
            "stage0_raw_paragraph_stream": raw_paragraph_stream,
            "stage0_asset_manifest": stage0_summary.get("artifacts", {}).get("asset_manifest", ""),
            "stage0_formula_audit": stage0_summary.get("artifacts", {}).get("formula_token_audit", ""),
            "stage0_preview_html": stage0_summary.get("artifacts", {}).get("preview_html", ""),
            "run_math_normalized_stream": normalized_paragraph_stream if normalized_paragraph_stream != raw_paragraph_stream else "",
            "run_math_normalization_report": run_math_report_path,
            "run_math_normalization_preview": run_math_preview_path,
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(doc_out / "router_summary.json", summary)
    handoff = build_handoff_manifest(summary=summary, doc_out=doc_out, stage0_summary=stage0_summary, manifest_path=manifest_path)
    write_json(doc_out / "handoff_manifest.json", handoff)
    summary["artifacts"]["handoff_manifest"] = rel(doc_out / "handoff_manifest.json")
    write_json(doc_out / "router_summary.json", summary)
    (doc_out / "index.html").write_text(render_html(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route a DOCX through formula source detection, optional OLE recovery, and Stage0 token stream.")
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--mathml-node-module-dir", type=Path, default=None)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
