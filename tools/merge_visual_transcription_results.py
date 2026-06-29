from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_runtime_module(workspace_root: Path):
    mod_path = workspace_root / "tools" / "teacher_handout_visual_transcribe_doubao.py"
    spec = importlib.util.spec_from_file_location("doubao_tool", mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_records_from_run(run_dir: Path) -> list[dict]:
    for name in (
        "visual_transcription_results.json",
        "visual_transcription_results.recovered.json",
    ):
        path = run_dir / name
        if path.exists():
            payload = read_json(path)
            return payload.get("records", []) if isinstance(payload, dict) else []
    return []


def rank_status(status: str) -> int:
    order = {"ok": 3, "prepared": 2, "failed": 1}
    return order.get(str(status or ""), 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    workspace_root = Path(".").resolve()
    module = load_runtime_module(workspace_root)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    merged: dict[str, dict] = {}
    for raw_run_dir in args.run_dir:
        run_dir = Path(raw_run_dir).resolve()
        for record in load_records_from_run(run_dir):
            record_id = str(record.get("record_id", "")).strip()
            if not record_id:
                continue
            previous = merged.get(record_id)
            if previous is None or rank_status(record.get("status", "")) >= rank_status(previous.get("status", "")):
                merged[record_id] = record

    ordered_records = [merged[key] for key in sorted(merged)]
    ok_records = [item for item in ordered_records if item.get("status") == "ok"]
    summary = {
        "question_count": len(ordered_records),
        "ok_count": len(ok_records),
        "prepared_count": sum(1 for item in ordered_records if item.get("status") == "prepared"),
        "failed_count": sum(1 for item in ordered_records if item.get("status") == "failed"),
        "usage_totals": module.aggregate_usage(ok_records),
        "latency_summary": module.aggregate_latency(ordered_records),
        "records": ordered_records,
    }

    results_path = out_dir / "visual_transcription_results.json"
    compact_path = out_dir / "visual_transcription_compact.json"
    write_json(results_path, summary)
    compact = []
    for item in ordered_records:
        compact.append(
            module.summarize_record(
                item,
                status=item.get("status", ""),
                parsed=item.get("transcription"),
                error=item.get("error", ""),
            )
        )
    write_json(compact_path, compact)

    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "question_count": summary["question_count"],
                "ok_count": summary["ok_count"],
                "prepared_count": summary["prepared_count"],
                "failed_count": summary["failed_count"],
                "results_path": str(results_path),
                "compact_path": str(compact_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
