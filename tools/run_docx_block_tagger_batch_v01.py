from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE0_ROOT = ROOT / "outputs" / "docx_native_formula_token_stream_v0_1"
DEFAULT_BATCH_ROOT = ROOT / "outputs" / "docx_native_block_tagger_v0_1"

DEFAULT_DOC_KEYS = [
    "doc1_14_3",
    "doc2_rational_ops",
    "doc3_hebei",
    "doc4_folding",
    "doc5_circle",
    "doc6_transform",
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_stream(stage0_root: Path, key: str) -> Path:
    run_dir = stage0_root / f"stage0_content_verdict_20260716_{key}"
    matches = sorted(run_dir.rglob("paragraph_stream_formula_tokens.json"))
    if not matches:
        raise FileNotFoundError(f"paragraph stream not found for {key}: {run_dir}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DOCX native block tagger over a fixed document batch.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-key", action="append", default=[])
    parser.add_argument("--stage0-root", type=Path, default=DEFAULT_STAGE0_ROOT)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    doc_keys = args.doc_key or DEFAULT_DOC_KEYS
    batch_dir = args.batch_root / args.run_id
    status_path = batch_dir / "batch_status.json"
    status: dict[str, Any] = {
        "schema_version": "docx_native_block_tagger_batch.v0.1",
        "run_id": args.run_id,
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "doc_keys": doc_keys,
        "results": [],
    }
    write_json(status_path, status)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if not env.get("ARK_API_KEY"):
        status["status"] = "failed"
        status["error"] = "missing ARK_API_KEY"
        write_json(status_path, status)
        return 2

    for index, key in enumerate(doc_keys, start=1):
        stream = find_stream(args.stage0_root, key)
        item: dict[str, Any] = {
            "doc_key": key,
            "source_stream": str(stream),
            "status": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "index": index,
            "total": len(doc_keys),
        }
        status["current"] = item
        write_json(status_path, status)

        cmd = [
            args.python,
            str(ROOT / "tools" / "docx_native_block_tagger_v01.py"),
            "--paragraph-stream",
            str(stream),
            "--run-id",
            args.run_id,
            "--max-workers",
            str(args.max_workers),
            "--timeout",
            str(args.timeout),
        ]
        if args.max_windows > 0:
            cmd.extend(["--max-windows", str(args.max_windows)])
        started = time.time()
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        elapsed = round(time.time() - started, 3)
        item.update(
            {
                "status": "ok" if proc.returncode == 0 else "failed",
                "returncode": proc.returncode,
                "elapsed_seconds": elapsed,
                "stdout_bytes": len(proc.stdout or b""),
                "stderr_bytes": len(proc.stderr or b""),
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        )
        if proc.returncode != 0:
            item["stderr_tail"] = (proc.stderr or b"").decode("utf-8", "ignore")[-2000:]
        status["results"].append(item)
        status.pop("current", None)
        write_json(status_path, status)
        if proc.returncode != 0:
            status["status"] = "failed"
            status["failed_doc_key"] = key
            write_json(status_path, status)
            return proc.returncode

    status["status"] = "complete"
    status["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    write_json(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
