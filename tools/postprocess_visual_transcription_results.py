from __future__ import annotations

import argparse
import json
from pathlib import Path

import visual_transcription_core as vision_core
import visual_transcription_strict_eval_adapter as strict_eval_adapter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", choices=("general", "strict_eval"), default="general")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    source_results_path = run_dir / "visual_transcription_results.json"
    source_compact_path = run_dir / "visual_transcription_compact.json"
    if not source_results_path.exists():
        raise SystemExit(f"missing_results_json: {source_results_path}")

    if args.mode == "strict_eval":
        results_path = run_dir / "visual_transcription_results.strict_eval.json"
        compact_path = run_dir / "visual_transcription_compact.strict_eval.json"
    else:
        results_path = source_results_path
        compact_path = source_compact_path

    summary = json.loads(source_results_path.read_text(encoding="utf-8"))
    records = summary.get("records", []) if isinstance(summary, dict) else []

    for record in records:
        if record.get("status") != "ok":
            continue
        transcription = record.get("transcription")
        if not isinstance(transcription, dict):
            continue
        if args.mode == "strict_eval":
            record["transcription"] = strict_eval_adapter.normalize_transcription_fields(transcription)
        else:
            record["transcription"] = vision_core.safe_normalize_transcription_payload(
                transcription,
                record_id=str(transcription.get("record_id", "") or record.get("record_id", "")),
                question_id=str(transcription.get("question_id", "") or record.get("question_id", "")),
                visual_refs={
                    "question_image": str(
                        (transcription.get("visual_refs", {}) or {}).get("question_image", "")
                        or record.get("question_image", "")
                    ),
                    "stem_image": str(
                        (transcription.get("visual_refs", {}) or {}).get("stem_image", "")
                        or record.get("stem_image", "")
                    ),
                    "analysis_image": str(
                        (transcription.get("visual_refs", {}) or {}).get("analysis_image", "")
                        or record.get("analysis_image", "")
                    ),
                },
                prompt_version=str(transcription.get("prompt_version", "") or summary.get("prompt_version", "")),
                model_name=str(transcription.get("model_name", "") or summary.get("model", "")),
            )

    ok_records = [item for item in records if item.get("status") == "ok"]
    summary["usage_totals"] = vision_core.aggregate_usage(ok_records)
    summary["latency_summary"] = vision_core.aggregate_latency(records)
    if args.mode == "strict_eval":
        summary["strict_eval_adapter"] = {"adapter_version": "strict_eval_v0.1"}

    compact = []
    for item in records:
        compact.append(
            vision_core.summarize_record(
                item,
                status=item.get("status", ""),
                parsed=item.get("transcription"),
                error=item.get("error", ""),
            )
        )

    backup_results = run_dir / "visual_transcription_results.pre_postprocess.json"
    backup_compact = run_dir / "visual_transcription_compact.pre_postprocess.json"
    if args.mode == "general":
        if not backup_results.exists():
            backup_results.write_text(source_results_path.read_text(encoding="utf-8"), encoding="utf-8")
        if source_compact_path.exists() and not backup_compact.exists():
            backup_compact.write_text(source_compact_path.read_text(encoding="utf-8"), encoding="utf-8")

    results_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "record_count": len(records),
                "ok_count": len(ok_records),
                "mode": args.mode,
                "results_path": str(results_path),
                "compact_path": str(compact_path),
                "backup_results": str(backup_results) if args.mode == "general" else "",
                "backup_compact": str(backup_compact) if args.mode == "general" else "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
