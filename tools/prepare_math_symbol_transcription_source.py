from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_component_label(row: dict[str, str]) -> str:
    candidates = [
        row.get("component_label", ""),
        row.get("source_ref", ""),
        row.get("note_zh", ""),
    ]
    labels = ["例题讲解", "强化训练", "课后落实", "题目区回退", "人工精选"]
    for text in candidates:
        for label in labels:
            if label and label in text:
                return label
    return "题图样本"


def build_question(row: dict[str, str], pack_dir: Path) -> dict[str, object]:
    image_abs = (pack_dir / row["packaged_image"]).resolve()
    component_label = detect_component_label(row)
    return {
        "question_id": row["case_id"],
        "checkpoint": row.get("submodule_zh", "") or row.get("module_zh", ""),
        "component_label": component_label,
        "local_number": row["case_id"],
        "visual_pages": [],
        "text_preview": row.get("source_ref", ""),
        "stem_text": "",
        "answer_text": "",
        "analysis_text": "",
        "question_image": str(image_abs),
        "stem_image": "",
        "analysis_image": "",
        "module_en": row.get("module_en", ""),
        "module_zh": row.get("module_zh", ""),
        "submodule_en": row.get("submodule_en", ""),
        "submodule_zh": row.get("submodule_zh", ""),
        "tags_en": [item for item in row.get("tags_en", "").split(";") if item],
        "tags_zh": [item for item in row.get("tags_zh", "").split(";") if item],
        "needs_human_review": str(row.get("needs_human_review", "")).lower() == "true",
        "source_type": row.get("source_type", ""),
        "source_run": row.get("source_run", ""),
        "source_ref": row.get("source_ref", ""),
        "note_zh": row.get("note_zh", ""),
        "audit_status": row.get("audit_status", ""),
    }


def build_manifest_items(source_json_path: Path, questions: list[dict[str, object]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for question in questions:
        qid = str(question["question_id"])
        items.append(
            {
                "sample_id": qid,
                "source_transcription_json": str(source_json_path),
                "question_id": qid,
                "tag": str(question.get("module_en", "")),
            }
        )
    return items


def shard_items(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    if size <= 0:
        return [items]
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare clean-main math symbol image pack as visual transcription source JSON.")
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--shard-size", type=int, default=25)
    args = parser.parse_args()

    pack_dir = Path(args.pack_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    manifest_csv = pack_dir / "manifest.csv"
    rows = read_rows(manifest_csv)
    questions = [build_question(row, pack_dir) for row in rows]

    source_json_path = out_dir / "teacher_visual_question_transcription_v0.1.json"
    write_json(
        source_json_path,
        {
            "package_name": pack_dir.name,
            "question_count": len(questions),
            "questions": questions,
        },
    )

    all_items = build_manifest_items(source_json_path, questions)
    all_manifest_path = out_dir / "all_questions_manifest.json"
    write_json(all_manifest_path, {"items": all_items})

    shard_dir = out_dir / "manifests"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = shard_items(all_items, args.shard_size)
    shard_paths: list[str] = []
    for idx, shard in enumerate(shards, start=1):
        shard_path = shard_dir / f"manifest_shard_{idx:02d}_of_{len(shards):02d}.json"
        write_json(shard_path, {"items": shard})
        shard_paths.append(str(shard_path))

    summary = {
        "pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "question_count": len(questions),
        "source_json": str(source_json_path),
        "all_manifest": str(all_manifest_path),
        "shard_count": len(shards),
        "shard_size": args.shard_size,
        "shards": shard_paths,
    }
    write_json(out_dir / "prepare_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
