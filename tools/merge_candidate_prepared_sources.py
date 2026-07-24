from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge prepared figure-candidate shards back into full source order.")
    parser.add_argument("--full-source-json", required=True)
    parser.add_argument("--gate-dir", required=True)
    parser.add_argument("--prepared-shards", nargs="+", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    full_source = Path(args.full_source_json).expanduser().resolve()
    full_payload = read_json(full_source)
    full_questions = full_payload.get("questions", []) if isinstance(full_payload, dict) else []

    prepared_by_qid: dict[str, dict[str, Any]] = {}
    shard_debug: list[dict[str, Any]] = []
    for raw_path in args.prepared_shards:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            continue
        payload = read_json(path)
        questions = payload.get("questions", []) if isinstance(payload, dict) else []
        for question in questions:
            if not isinstance(question, dict):
                continue
            qid = str(question.get("question_id", "") or "")
            if qid:
                prepared_by_qid[qid] = question
        debug_rows = payload.get("option_visual_debug", []) if isinstance(payload, dict) else []
        if isinstance(debug_rows, list):
            shard_debug.extend(item for item in debug_rows if isinstance(item, dict))

    gate_dir = Path(args.gate_dir).expanduser().resolve()
    merged_questions: list[dict[str, Any]] = []
    candidate_count = 0
    no_image_count = 0
    for question in full_questions:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("question_id", "") or "")
        if qid in prepared_by_qid:
            merged_questions.append(prepared_by_qid[qid])
            candidate_count += 1
            continue
        copied = dict(question)
        gate_path = gate_dir / "gate" / f"{qid}.gate.json"
        if gate_path.exists():
            copied["image_need_gate"] = read_json(gate_path)
        copied["staged_visual_assets"] = []
        copied["option_visual_blocks"] = []
        copied["stem_image_bboxes"] = []
        copied["analysis_image_bboxes"] = []
        copied["unassigned_image_bboxes"] = []
        copied["option_detection_review_flags"] = ["figure_detection_skipped_by_model_gate"]
        no_image_count += 1
        merged_questions.append(copied)

    out_payload = {
        **({k: v for k, v in full_payload.items() if k != "questions"} if isinstance(full_payload, dict) else {}),
        "schema_version": "option_visual_source.merged_gate_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "full_source_json": str(full_source),
        "gate_dir": str(gate_dir),
        "candidate_prepared_count": candidate_count,
        "no_image_skipped_count": no_image_count,
        "questions": merged_questions,
        "option_visual_debug": shard_debug,
    }
    out_json = Path(args.out_json).expanduser().resolve()
    write_json(out_json, out_payload)
    summary = {
        "question_count": len(merged_questions),
        "candidate_prepared_count": candidate_count,
        "no_image_skipped_count": no_image_count,
        "debug_rows": len(shard_debug),
        "out_json": str(out_json),
    }
    write_json(out_json.with_suffix(".summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
