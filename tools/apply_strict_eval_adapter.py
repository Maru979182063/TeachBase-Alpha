from __future__ import annotations

import argparse
import json
from pathlib import Path

from visual_transcription_core import aggregate_latency, aggregate_usage, summarize_record
from visual_transcription_strict_eval_adapter import normalize_transcription_fields


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    results_path = run_dir / "visual_transcription_results.json"
    if not results_path.exists():
        raise SystemExit(f"missing_results_json: {results_path}")

    summary = json.loads(results_path.read_text(encoding="utf-8"))
    records = summary.get("records", []) if isinstance(summary, dict) else []
    adapted_records = []
    for record in records:
        item = dict(record)
        transcription = item.get("transcription")
        if item.get("status") == "ok" and isinstance(transcription, dict):
            item["transcription"] = normalize_transcription_fields(transcription)
        adapted_records.append(item)

    ok_records = [item for item in adapted_records if item.get("status") == "ok"]
    adapted_summary = dict(summary)
    adapted_summary["records"] = adapted_records
    adapted_summary["usage_totals"] = aggregate_usage(ok_records)
    adapted_summary["latency_summary"] = aggregate_latency(adapted_records)
    adapted_summary["strict_eval_adapter"] = {
        "adapter_version": "strict_eval_v0.1",
        "source_results_path": str(results_path),
    }

    adapted_results_path = run_dir / "visual_transcription_results.strict_eval.json"
    adapted_compact_path = run_dir / "visual_transcription_compact.strict_eval.json"
    adapted_results_path.write_text(
        json.dumps(adapted_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    adapted_compact = []
    for item in adapted_records:
        adapted_compact.append(
            summarize_record(
                item,
                status=item.get("status", ""),
                parsed=item.get("transcription"),
                error=item.get("error", ""),
            )
        )
    adapted_compact_path.write_text(
        json.dumps(adapted_compact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "adapted_results_path": str(adapted_results_path),
                "adapted_compact_path": str(adapted_compact_path),
                "record_count": len(adapted_records),
                "ok_count": len(ok_records),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
