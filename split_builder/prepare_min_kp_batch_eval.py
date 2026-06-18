from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "min_kp_question_coverage_v0.1"
BATCH = BASE / "batch_model_run"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def compact_catalog() -> list[dict]:
    rows = []
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


def make_chunks(chunk_size: int = 40) -> None:
    blind = load_json(BASE / "blind_input_no_labels.json")
    catalog = compact_catalog()
    write_json(BATCH / "knowledge_catalog_for_model.json", catalog)
    chunks = []
    for idx in range(0, len(blind), chunk_size):
        chunk_no = idx // chunk_size + 1
        items = blind[idx : idx + chunk_size]
        path = BATCH / f"blind_chunk_{chunk_no:02d}.json"
        write_json(
            path,
            {
                "chunk_no": chunk_no,
                "purpose": "Model placement input. No answer labels are included.",
                "items": items,
            },
        )
        chunks.append({"chunk_no": chunk_no, "path": str(path), "count": len(items)})
    write_json(BATCH / "chunk_manifest.json", chunks)


if __name__ == "__main__":
    make_chunks()
