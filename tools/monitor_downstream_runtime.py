from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def summarize_out_dir(out_dir: Path) -> dict[str, Any]:
    raw_dir = out_dir / "raw"
    raw_files = list(raw_dir.glob("*")) if raw_dir.exists() else []
    prepared_files = list(raw_dir.glob("*.prepared.json")) if raw_dir.exists() else []
    manifest = read_json(out_dir / "all_questions_manifest.json")
    live = read_json(out_dir / "live_progress.json")
    results = read_json(out_dir / "visual_transcription_results.json")
    asset_manifest = read_json(out_dir / "question_asset_bundle_v0.1" / "question_asset_manifest_v0.1.json")

    question_count = 0
    if isinstance(manifest, dict):
        question_count = len(manifest.get("items", []) or [])
    result_counts = {}
    if isinstance(results, dict):
        result_counts = {
            "question_count": results.get("question_count", 0),
            "ok_count": results.get("ok_count", 0),
            "failed_count": results.get("failed_count", 0),
            "prepared_count": results.get("prepared_count", 0),
        }
    asset_count = 0
    if isinstance(asset_manifest, dict):
        asset_count = int(asset_manifest.get("asset_count", 0) or len(asset_manifest.get("records", []) or []))

    return {
        "out_dir": str(out_dir),
        "exists": out_dir.exists(),
        "manifest_exists": (out_dir / "all_questions_manifest.json").exists(),
        "manifest_question_count": question_count,
        "live_progress_exists": (out_dir / "live_progress.json").exists(),
        "live_progress": live if isinstance(live, dict) else {},
        "raw_file_count": len(raw_files),
        "prepared_file_count": len(prepared_files),
        "results_exists": (out_dir / "visual_transcription_results.json").exists(),
        "result_counts": result_counts,
        "asset_manifest_exists": (out_dir / "question_asset_bundle_v0.1" / "question_asset_manifest_v0.1.json").exists(),
        "asset_count": asset_count,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    docs = [item.strip() for item in str(args.docs or "").split(",") if item.strip()]
    if not docs:
        docs = ["math", "english"]

    while True:
        payload = {
            "schema": "downstream_runtime_monitor_v0.1",
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "root": str(root),
            "docs": {},
        }
        for doc in docs:
            out_dir = root / f"{doc}_downstream_full_live"
            if args.suffix:
                out_dir = root / f"{doc}_{args.suffix}"
            payload["docs"][doc] = summarize_out_dir(out_dir)
        write_json(root / "live_downstream_status.json", payload)
        print(json.dumps(payload, ensure_ascii=False))
        if args.once:
            return 0
        time.sleep(max(float(args.interval), 1.0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Periodically summarize downstream transcription + assetization progress.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--docs", default="math,english")
    parser.add_argument("--suffix", default="downstream_full_live")
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--once", action="store_true")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
