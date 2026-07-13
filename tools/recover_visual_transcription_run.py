from __future__ import annotations

import argparse
import json
from pathlib import Path

import visual_transcription_core as vision_core

def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def recover_records(run_dir: Path) -> list[dict]:
    raw_dir = run_dir / "raw"
    prepared_files = sorted(raw_dir.glob("*.prepared.json"))
    records: list[dict] = []

    for prepared_path in prepared_files:
        prepared = read_json(prepared_path)
        record_id = str(prepared.get("record_id", "")).strip() or prepared_path.name.replace(".prepared.json", "")
        base = {
            "record_id": record_id,
            "question_id": prepared.get("question_id", ""),
            "source_transcription_json": prepared.get("source_transcription_json", ""),
            "tag": prepared.get("tag", ""),
            "question_image": prepared.get("question_image", ""),
            "stem_image": prepared.get("stem_image", ""),
            "analysis_image": prepared.get("analysis_image", ""),
        }

        response_json_path = raw_dir / f"{record_id}.response.json"
        response_failed_path = raw_dir / f"{record_id}.response_failed_parse.json"

        if response_json_path.exists():
            raw_response = read_json(response_json_path)
            content = (
                raw_response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            started_at = prepared_path.stat().st_mtime
            finished_at = response_json_path.stat().st_mtime
            latency_seconds = round(max(finished_at - started_at, 0.0), 3)
            try:
                parsed = vision_core.extract_json_block(content)
                parsed = vision_core.safe_normalize_transcription_payload(
                    parsed,
                    record_id=record_id,
                    question_id=str(prepared.get("question_id", "") or ""),
                    visual_refs={
                        "question_image": str(prepared.get("question_image", "") or ""),
                        "stem_image": str(prepared.get("stem_image", "") or ""),
                        "analysis_image": str(prepared.get("analysis_image", "") or ""),
                    },
                    prompt_version=str(prepared.get("prompt_version", "") or ""),
                    model_name=str(raw_response.get("model", "") or ""),
                )
                records.append(
                    {
                        **base,
                        "status": "ok",
                        "request_started_at": started_at,
                        "request_finished_at": finished_at,
                        "latency_seconds": latency_seconds,
                        "usage": raw_response.get("usage", {}) or {},
                        "transcription": parsed,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                records.append(
                    {
                        **base,
                        "status": "failed",
                        "request_started_at": started_at,
                        "request_finished_at": finished_at,
                        "latency_seconds": latency_seconds,
                        "error": f"recover_parse_failed: {exc}",
                        "usage": raw_response.get("usage", {}) or {},
                    }
                )
            continue

        if response_failed_path.exists():
            raw_response = read_json(response_failed_path)
            records.append(
                {
                    **base,
                    "status": "failed",
                    "error": "response_failed_parse",
                    "usage": raw_response.get("usage", {}) or {},
                }
            )
            continue

        records.append({**base, "status": "prepared"})

    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--manifest", default="")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    records = recover_records(run_dir)
    ok_records = [item for item in records if item.get("status") == "ok"]
    summary = {
        "run_dir": str(run_dir),
        "question_count": len(records),
        "ok_count": len(ok_records),
        "prepared_count": sum(1 for item in records if item.get("status") == "prepared"),
        "failed_count": sum(1 for item in records if item.get("status") == "failed"),
        "usage_totals": vision_core.aggregate_usage(ok_records),
        "latency_summary": vision_core.aggregate_latency(records),
        "records": records,
    }

    recovered_results = run_dir / "visual_transcription_results.recovered.json"
    recovered_compact = run_dir / "visual_transcription_compact.recovered.json"
    write_json(recovered_results, summary)
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
    write_json(recovered_compact, compact)

    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
        manifest = read_json(manifest_path)
        done_ids = {str(item.get("record_id", "")) for item in records if item.get("status") == "ok"}
        remaining_items = [item for item in manifest.get("items", []) if str(item.get("sample_id", "")).strip() not in done_ids and str(item.get("record_id", "")).strip() not in done_ids]
        write_json(run_dir / "remaining_manifest.recovered.json", {"items": remaining_items})

    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "recovered_results": str(recovered_results),
                "recovered_compact": str(recovered_compact),
                "record_count": len(records),
                "ok_count": len(ok_records),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
