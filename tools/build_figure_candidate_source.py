from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_gate_records(gate_dir: Path) -> list[dict[str, Any]]:
    summary_path = gate_dir / "model_image_need_gate_summary.json"
    if summary_path.exists():
        payload = read_json(summary_path)
        records = payload.get("results", []) if isinstance(payload, dict) else []
        return [item for item in records if isinstance(item, dict)]
    records: list[dict[str, Any]] = []
    for path in sorted((gate_dir / "gate").glob("*.gate.json")):
        item = read_json(path)
        if isinstance(item, dict):
            records.append(item)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source JSON subsets from model image need gate results.")
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--gate-dir", required=True)
    parser.add_argument("--candidate-json", required=True)
    parser.add_argument("--no-image-json", required=True)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()

    source_json = Path(args.source_json).expanduser().resolve()
    source_payload = read_json(source_json)
    questions = source_payload.get("questions", []) if isinstance(source_payload, dict) else []
    by_qid = {
        str(question.get("question_id", "") or ""): question
        for question in questions
        if isinstance(question, dict)
    }

    gate_dir = Path(args.gate_dir).expanduser().resolve()
    gates = load_gate_records(gate_dir)
    gate_by_qid = {
        str(item.get("question_id", "") or ""): item
        for item in gates
        if isinstance(item, dict) and str(item.get("question_id", "") or "")
    }

    candidate_questions: list[dict[str, Any]] = []
    no_image_questions: list[dict[str, Any]] = []
    missing_gate_questions: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("question_id", "") or "")
        gate = gate_by_qid.get(qid)
        enriched = dict(question)
        if gate:
            enriched["image_need_gate"] = gate
        else:
            missing_gate_questions.append(qid)
            enriched["image_need_gate"] = {
                "question_id": qid,
                "status": "missing",
                "needs_figure_detection": True,
                "image_presence": "uncertain",
                "reason": "missing gate result; route conservatively",
            }
        if bool(enriched["image_need_gate"].get("needs_figure_detection")):
            candidate_questions.append(enriched)
        else:
            no_image_questions.append(enriched)

    base_meta = {k: v for k, v in source_payload.items() if k != "questions"} if isinstance(source_payload, dict) else {}
    candidate_payload = {
        **base_meta,
        "schema_version": "figure_candidate_source.v0.1",
        "source_json": str(source_json),
        "gate_dir": str(gate_dir),
        "questions": candidate_questions,
    }
    no_image_payload = {
        **base_meta,
        "schema_version": "no_image_source.v0.1",
        "source_json": str(source_json),
        "gate_dir": str(gate_dir),
        "questions": no_image_questions,
    }
    candidate_json = Path(args.candidate_json).expanduser().resolve()
    no_image_json = Path(args.no_image_json).expanduser().resolve()
    write_json(candidate_json, candidate_payload)
    write_json(no_image_json, no_image_payload)

    shard_dir = Path(args.shard_dir).expanduser().resolve()
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_count = max(1, int(args.shards))
    shard_paths: list[str] = []
    for index in range(shard_count):
        shard_questions = candidate_questions[index::shard_count]
        shard_payload = {
            **base_meta,
            "schema_version": "figure_candidate_source_shard.v0.1",
            "source_json": str(source_json),
            "gate_dir": str(gate_dir),
            "shard_index": index,
            "shard_count": shard_count,
            "questions": shard_questions,
        }
        shard_path = shard_dir / f"candidate_shard_{index + 1:02d}_of_{shard_count:02d}.json"
        write_json(shard_path, shard_payload)
        shard_paths.append(str(shard_path))

    summary = {
        "source_count": len(questions),
        "gate_count": len(gates),
        "candidate_count": len(candidate_questions),
        "no_image_count": len(no_image_questions),
        "missing_gate_count": len(missing_gate_questions),
        "missing_gate_question_ids": missing_gate_questions,
        "candidate_json": str(candidate_json),
        "no_image_json": str(no_image_json),
        "shard_paths": shard_paths,
    }
    write_json(candidate_json.with_suffix(".summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
