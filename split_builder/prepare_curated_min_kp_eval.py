from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "min_kp_question_coverage_v0.1"
CURATION = BASE / "gold_curation_v0.1"
OUT = BASE / "curated_model_run_v0.2"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def compact_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder in ["junior_math_knowledge_map", "senior_math_knowledge_map"]:
        for row in load_json(ROOT / "outputs" / folder / "knowledge_points.json"):
            rows.append(
                {
                    "knowledge_id": row.get("knowledge_id"),
                    "stage": row.get("stage"),
                    "grade": row.get("grade"),
                    "lesson_id": row.get("lesson_id"),
                    "lesson_title": row.get("lesson_title"),
                    "module": row.get("level_2_module"),
                    "min_knowledge_point": row.get("level_3_min_knowledge_point"),
                }
            )
    return rows


def ids_from_curation(filename: str) -> list[str]:
    rows = load_json(CURATION / filename)
    return [row["test_question_id"] for row in rows]


def make_chunks(items: list[dict[str, Any]], chunk_size: int = 35) -> list[dict[str, Any]]:
    chunks = []
    for idx in range(0, len(items), chunk_size):
        chunk_no = idx // chunk_size + 1
        chunk_items = items[idx : idx + chunk_size]
        path = OUT / f"blind_expanded_chunk_{chunk_no:02d}.json"
        write_json(
            path,
            {
                "chunk_no": chunk_no,
                "purpose": "Curated v0.2 model placement input. No answer labels are included.",
                "items": chunk_items,
            },
        )
        chunks.append({"chunk_no": chunk_no, "path": str(path), "count": len(chunk_items)})
    return chunks


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    blind = {row["test_question_id"]: row for row in load_json(BASE / "blind_input_no_labels.json")}
    clean_ids = ids_from_curation("usable_gold.json")
    expanded_ids = clean_ids + ids_from_curation("usable_with_review.json")

    clean_items = [blind[qid] for qid in clean_ids]
    expanded_items = [blind[qid] for qid in expanded_ids]

    write_json(OUT / "knowledge_catalog_for_model.json", compact_catalog())
    write_json(OUT / "blind_clean_30.json", {"set_name": "clean_30", "items": clean_items})
    write_json(OUT / "blind_expanded_140.json", {"set_name": "expanded_140", "items": expanded_items})
    write_json(
        OUT / "curated_set_manifest.json",
        {
            "clean_30": {"count": len(clean_items), "ids": clean_ids},
            "expanded_140": {"count": len(expanded_items), "ids": expanded_ids},
            "blind_policy": "Question text and page image only. No grade/lesson/module/min knowledge labels.",
        },
    )
    chunks = make_chunks(expanded_items)
    write_json(OUT / "chunk_manifest.json", chunks)
    print(json.dumps({"clean_30": len(clean_items), "expanded_140": len(expanded_items), "chunks": chunks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
