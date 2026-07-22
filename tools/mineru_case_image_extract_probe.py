#!/usr/bin/env python
"""Probe MinerU image extraction for selected question cases.

This is a side-path experiment. It does not modify the question ingest runtime.
It reads the existing 208-question runtime source/asset manifest, runs MinerU
on selected question source images, and writes a comparison manifest plus HTML.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_RUNTIME = Path("outputs/visual_transcription_v0.1/runtime_208_full_666_20260713")
DEFAULT_OUT = Path("outputs/mineru_image_extract_probe_20260720")
DEFAULT_CASES = ("case_055", "case_114", "case_135")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def wait_for_health(base_url: str, timeout_s: int = 90) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=3) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if resp.status == 200 and payload.get("status") == "healthy":
                    return payload
        except Exception as exc:  # noqa: BLE001 - surfaced in manifest
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"MinerU API health timeout at {base_url}: {last_error}")


def image_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path.resolve()),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else None,
    }
    if path.exists() and path.suffix.lower() in IMAGE_SUFFIXES:
        try:
            with Image.open(path) as img:
                info["width"], info["height"] = img.size
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            info["image_error"] = str(exc)
    return info


def safe_copy(src: Path, dst: Path) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return image_info(dst)


def copy_current_chain_files(root: Path, out_dir: Path) -> list[dict[str, Any]]:
    backup_dir = out_dir / "backup_current_chain"
    backup_dir.mkdir(parents=True, exist_ok=True)
    rels = [
        "tools/run_question_ingest_skill.py",
        "tools/assetize_question_images.py",
        "tools/prepare_option_visual_source.py",
        "tools/option_anchor_detection.py",
        "tools/option_crop_staging.py",
        "tools/consolidate_visual_assets.py",
        "tools/reconcile_and_refine_visual_assets.py",
        "tools/audit_question_asset_package.py",
    ]
    copied = []
    for rel in rels:
        src = root / rel
        item = {"source": rel, "exists": src.exists()}
        if src.exists():
            dst = backup_dir / src.name
            shutil.copy2(src, dst)
            item.update({"backup_path": str(dst.resolve()), "bytes": dst.stat().st_size})
        copied.append(item)
    return copied


def find_question(questions: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    for q in questions:
        if q.get("question_id") == case_id or q.get("record_id") == case_id or q.get("question_uid") == case_id:
            return q
    raise KeyError(f"case not found: {case_id}")


def resolve_asset_path(runtime: Path, storage_key: str | None) -> Path | None:
    if not storage_key:
        return None
    candidates = [
        runtime / "06_6_asset_reconcile_refine" / storage_key,
        runtime / "06_asset_bundle" / storage_key,
        runtime / storage_key,
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def collect_existing_assets(
    root: Path,
    runtime: Path,
    manifest_questions: list[dict[str, Any]],
    case_id: str,
    out_case_dir: Path,
) -> list[dict[str, Any]]:
    q = find_question(manifest_questions, case_id)
    copied: list[dict[str, Any]] = []
    for idx, asset in enumerate(q.get("assets") or [], start=1):
        storage_key = asset.get("storage_key")
        src = resolve_asset_path(runtime, storage_key)
        item = {
            "asset_id": asset.get("asset_id"),
            "role": asset.get("role") or asset.get("asset_role") or asset.get("kind"),
            "storage_key": storage_key,
            "source_path": str(src.resolve()) if src else None,
            "exists": bool(src and src.exists()),
        }
        if src and src.exists() and src.suffix.lower() in IMAGE_SUFFIXES:
            dst = out_case_dir / f"{idx:02d}_{src.name}"
            item["copied"] = safe_copy(src, dst)
        copied.append(item)
    return copied


def find_content_list(run_dir: Path) -> Path | None:
    candidates = sorted(run_dir.rglob("*_content_list.json"))
    if candidates:
        return candidates[0]
    candidates = sorted(run_dir.rglob("*content_list*.json"))
    return candidates[0] if candidates else None


def collect_mineru_images(run_dir: Path, out_case_dir: Path) -> list[dict[str, Any]]:
    content_list = find_content_list(run_dir)
    entries: list[dict[str, Any]] = []
    used_paths: set[Path] = set()
    if content_list and content_list.exists():
        data = read_json(content_list)
        base = content_list.parent
        for idx, item in enumerate(data if isinstance(data, list) else [], start=1):
            if item.get("type") != "image":
                continue
            rel = item.get("img_path")
            src = (base / rel) if rel else None
            copied = None
            if src and src.exists():
                used_paths.add(src.resolve())
                suffix = src.suffix.lower() or ".jpg"
                dst = out_case_dir / f"{len(entries) + 1:02d}_mineru{suffix}"
                copied = safe_copy(src, dst)
            entries.append(
                {
                    "order": idx,
                    "img_path": rel,
                    "bbox": item.get("bbox"),
                    "page_idx": item.get("page_idx"),
                    "source_path": str(src.resolve()) if src else None,
                    "exists": bool(src and src.exists()),
                    "copied": copied,
                }
            )
    if entries:
        return entries

    # Fallback if content list is absent or MinerU changed schema.
    for src in sorted(run_dir.rglob("*")):
        if src.is_file() and src.suffix.lower() in IMAGE_SUFFIXES and src.resolve() not in used_paths:
            dst = out_case_dir / f"{len(entries) + 1:02d}_{src.name}"
            entries.append({"source_path": str(src.resolve()), "fallback": True, "copied": safe_copy(src, dst)})
    return entries


def run_mineru_case(
    root: Path,
    mineru_scripts: Path,
    api_url: str,
    source_image: Path,
    raw_out: Path,
    env: dict[str, str],
    timeout_s: int,
) -> dict[str, Any]:
    if raw_out.exists():
        shutil.rmtree(raw_out)
    raw_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(mineru_scripts / "mineru.exe"),
        "-p",
        str(source_image),
        "-o",
        str(raw_out),
        "--api-url",
        api_url,
        "-b",
        "pipeline",
        "-m",
        "ocr",
        "-l",
        "ch",
    ]
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        errors="replace",
        timeout=timeout_s,
        env=env,
    )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 3),
        "stdout_tail": proc.stdout[-12000:],
        "raw_output_dir": str(raw_out.resolve()),
    }


def rel_link(path: str | None, base: Path) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except Exception:  # noqa: BLE001
        return Path(path).as_posix()


def render_image_cards(title: str, items: list[dict[str, Any]], base: Path) -> str:
    cards = [f"<h3>{html.escape(title)} <span>{len(items)}</span></h3>", '<div class="grid">']
    for item in items:
        copied = item.get("copied") if isinstance(item.get("copied"), dict) else item
        path = copied.get("path") if isinstance(copied, dict) else None
        meta = []
        for key in ("asset_id", "role", "bbox", "width", "height", "bytes"):
            value = item.get(key)
            if value is None and isinstance(copied, dict):
                value = copied.get(key)
            if value is not None:
                meta.append(f"{key}: {value}")
        img = ""
        if path:
            img = f'<a href="{html.escape(rel_link(path, base))}"><img src="{html.escape(rel_link(path, base))}" /></a>'
        cards.append(f'<figure>{img}<figcaption>{html.escape(" | ".join(meta) or str(item))}</figcaption></figure>')
    cards.append("</div>")
    return "\n".join(cards)


def write_html(out_dir: Path, manifest: dict[str, Any]) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>MinerU image probe</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#222}h1{font-size:24px}h2{margin-top:36px;border-top:1px solid #ddd;padding-top:20px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px}figure{margin:0;border:1px solid #ddd;padding:8px;background:#fafafa}img{max-width:100%;height:auto;background:white}figcaption{font-size:12px;line-height:1.35;word-break:break-all;color:#555}.source img{max-height:720px}code{background:#eee;padding:2px 4px}</style>",
        "<h1>MinerU image extraction probe</h1>",
        f"<p>Runtime: <code>{html.escape(manifest['runtime'])}</code></p>",
        f"<p>MinerU: <code>{html.escape(str(manifest['mineru'].get('version')))}</code>; API: <code>{html.escape(manifest['mineru'].get('api_url',''))}</code></p>",
    ]
    for case in manifest["cases"]:
        parts.append(f"<h2>{html.escape(case['case_id'])}</h2>")
        status = case["mineru_run"]["returncode"]
        parts.append(f"<p>MinerU returncode: <code>{status}</code>; seconds: <code>{case['mineru_run'].get('seconds')}</code>; extracted images: <code>{len(case['mineru_images'])}</code>; existing assets: <code>{len(case['existing_assets'])}</code></p>")
        parts.append('<div class="source">')
        parts.append(render_image_cards("source question image", [case["source_copy"]], out_dir))
        parts.append("</div>")
        parts.append(render_image_cards("existing runtime assets", case["existing_assets"], out_dir))
        parts.append(render_image_cards("MinerU extracted images", case["mineru_images"], out_dir))
        if status != 0:
            parts.append("<pre>" + html.escape(case["mineru_run"].get("stdout_tail", "")) + "</pre>")
    (out_dir / "index.html").write_text("\n".join(parts), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cases", nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--mineru-venv", type=Path, default=Path(r"C:\Users\EDY\AppData\Local\Temp\mineru_probe_venv_20260720"))
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--timeout-s", type=int, default=1200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    runtime = (root / args.runtime).resolve()
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mineru_scripts = args.mineru_venv / "Scripts"
    mineru_exe = mineru_scripts / "mineru.exe"
    api_exe = mineru_scripts / "mineru-api.exe"
    if not mineru_exe.exists() or not api_exe.exists():
        raise SystemExit(f"MinerU executables not found under {mineru_scripts}")

    source_data = read_json(runtime / "source.abs.json")
    refined_manifest = read_json(runtime / "06_6_asset_reconcile_refine/reconciled_refined_manifest.json")

    env = os.environ.copy()
    env.update({"NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": ""})

    logs = out_dir / "logs"
    logs.mkdir(exist_ok=True)
    api_url = f"http://127.0.0.1:{args.port}"
    api_stdout = (logs / f"probe_api_{args.port}.stdout.log").open("w", encoding="utf-8", errors="replace")
    api_stderr = (logs / f"probe_api_{args.port}.stderr.log").open("w", encoding="utf-8", errors="replace")
    api_proc = subprocess.Popen(
        [str(api_exe), "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=root,
        env=env,
        stdout=api_stdout,
        stderr=api_stderr,
    )

    manifest: dict[str, Any] = {
        "schema_version": "mineru_image_extract_probe.v0.1",
        "runtime": str(runtime),
        "out_dir": str(out_dir),
        "backup": {"files": copy_current_chain_files(root, out_dir)},
        "mineru": {
            "venv": str(args.mineru_venv),
            "api_url": api_url,
            "version": None,
            "api_stdout_log": str((logs / f"probe_api_{args.port}.stdout.log").resolve()),
            "api_stderr_log": str((logs / f"probe_api_{args.port}.stderr.log").resolve()),
        },
        "cases": [],
    }

    try:
        health = wait_for_health(api_url)
        manifest["mineru"]["health"] = health
        version_proc = subprocess.run(
            [str(mineru_exe), "--version"],
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
            timeout=30,
        )
        manifest["mineru"]["version"] = version_proc.stdout.strip()

        for case_id in args.cases:
            source_q = find_question(source_data["questions"], case_id)
            source_image = Path(source_q["question_image"])
            case_dir = out_dir / "cases" / case_id
            source_copy = safe_copy(source_image, case_dir / "source" / source_image.name)
            existing_assets = collect_existing_assets(
                root,
                runtime,
                refined_manifest["questions"],
                case_id,
                case_dir / "existing_runtime_assets",
            )
            raw_out = out_dir / "mineru_raw" / case_id
            run = run_mineru_case(root, mineru_scripts, api_url, source_image, raw_out, env, args.timeout_s)
            mineru_images = collect_mineru_images(raw_out, case_dir / "mineru_images") if run["returncode"] == 0 else []
            manifest["cases"].append(
                {
                    "case_id": case_id,
                    "source_ref": source_q.get("source_ref"),
                    "source_image": str(source_image),
                    "source_copy": source_copy,
                    "existing_assets": existing_assets,
                    "mineru_run": run,
                    "mineru_images": mineru_images,
                }
            )
            write_json(out_dir / "probe_manifest.json", manifest)
    finally:
        api_proc.terminate()
        try:
            api_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_proc.kill()
        api_stdout.close()
        api_stderr.close()

    write_json(out_dir / "probe_manifest.json", manifest)
    write_html(out_dir, manifest)
    print(json.dumps({"out_dir": str(out_dir), "manifest": str(out_dir / "probe_manifest.json"), "html": str(out_dir / "index.html")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
