from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_question_complexity_router_v01.yaml"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_blocks(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    blocks = payload.get("paragraphs") or payload.get("blocks") or []
    return {str(block.get("block_id") or f"b_{index:06d}"): block for index, block in enumerate(blocks) if isinstance(block, dict)}


def load_tags(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    tags = payload.get("tags") or payload.get("block_tags") or []
    return {str(item.get("block_id")): item for item in tags if isinstance(item, dict)}


def load_groups(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    return [item for item in (payload.get("groups") or payload.get("membership_groups") or []) if isinstance(item, dict)]


def block_text(block: dict[str, Any]) -> str:
    return str(block.get("display_markdown") or block.get("markdown") or block.get("text") or block.get("plain_text_lossy") or "")


def image_refs(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (block.get("image_refs") or block.get("asset_refs") or []) if isinstance(item, dict)]


def storage_key_missing(image: dict[str, Any]) -> bool:
    storage_key = str(image.get("storage_key") or "").strip()
    if not storage_key:
        return False
    path = Path(storage_key)
    if not path.is_absolute():
        path = ROOT / path
    return not path.exists()


def formula_count(block: dict[str, Any]) -> int:
    try:
        return int(block.get("formula_count") or 0)
    except (TypeError, ValueError):
        return 0


def route_group(
    group: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
    tags_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    block_ids = [str(item) for item in group.get("block_ids") or [] if str(item)]
    missing_block_refs = [block_id for block_id in block_ids if block_id not in blocks_by_id]
    blocks = [blocks_by_id[block_id] for block_id in block_ids if block_id in blocks_by_id]
    nonempty_blocks = [block for block in blocks if block_text(block).strip()]
    images = [image for block in blocks for image in image_refs(block)]
    missing_asset_images = [image for image in images if storage_key_missing(image)]
    table_blocks = [block for block in blocks if str(block.get("source_block_type") or "") == "docx_table" or "table" in (block.get("content_tags") or [])]
    role_counts = Counter(str(tags_by_id.get(block_id, {}).get("primary_role") or "unknown") for block_id in block_ids)
    noise_counts = Counter(noise for block_id in block_ids for noise in (tags_by_id.get(block_id, {}).get("noise_tags") or []))
    content_counts = Counter(tag for block in blocks for tag in (block.get("content_tags") or tags_by_id.get(str(block.get("block_id")), {}).get("content_tags") or []))
    total_formula_count = sum(formula_count(block) for block in blocks)
    metrics = {
        "block_count": len(block_ids),
        "resolved_block_count": len(blocks),
        "nonempty_block_count": len(nonempty_blocks),
        "missing_block_ref_count": len(missing_block_refs),
        "image_count_total": len(images),
        "missing_asset_count": len(missing_asset_images),
        "table_block_count": len(table_blocks),
        "formula_count_total": total_formula_count,
        "role_counts": dict(sorted(role_counts.items())),
        "noise_counts": dict(sorted(noise_counts.items())),
        "content_tag_counts": dict(sorted(content_counts.items())),
    }

    hard_fail_config = config.get("hard_fail") or {}
    hard_reasons: list[str] = []
    if hard_fail_config.get("fail_on_empty_source_blocks", True) and not block_ids:
        hard_reasons.append("empty_source_block_ids")
    if hard_fail_config.get("fail_on_missing_block_refs", True) and missing_block_refs:
        hard_reasons.append("missing_block_refs")
    if hard_fail_config.get("fail_on_zero_nonempty_blocks", True) and block_ids and not nonempty_blocks:
        hard_reasons.append("zero_nonempty_blocks")
    if hard_fail_config.get("fail_on_missing_asset_files", True) and missing_asset_images:
        hard_reasons.append("missing_asset_files")
    if hard_reasons:
        return {
            "group_id": str(group.get("group_id") or group.get("packet_id") or ""),
            "route": "hard_fail",
            "route_reason": hard_reasons,
            "metrics": metrics,
            "missing_block_refs": missing_block_refs,
            "missing_asset_refs": [image.get("asset_id") for image in missing_asset_images],
        }

    thresholds = config.get("route_thresholds") or {}
    long_reasons: list[str] = []
    if len(block_ids) >= int(thresholds.get("long_block_count", 35)):
        long_reasons.append("block_count")
    if len(nonempty_blocks) >= int(thresholds.get("long_nonempty_block_count", 28)):
        long_reasons.append("nonempty_block_count")
    if len(images) >= int(thresholds.get("long_image_count", 3)):
        long_reasons.append("image_count")
    if len(table_blocks) >= int(thresholds.get("long_table_block_count", 1)) and len(block_ids) >= int(thresholds.get("long_table_min_blocks", 12)):
        long_reasons.append("table_with_many_blocks")
    if total_formula_count >= int(thresholds.get("long_formula_count", 80)) and len(block_ids) >= int(thresholds.get("long_formula_min_blocks", 20)):
        long_reasons.append("formula_dense_long_packet")
    if len(block_ids) >= int(thresholds.get("mixed_block_count", 28)) and len(images) >= int(thresholds.get("mixed_image_count", 2)):
        long_reasons.append("mixed_many_blocks_and_images")

    route = "long_part_normalizer" if long_reasons else "normal_part_normalizer"
    return {
        "group_id": str(group.get("group_id") or group.get("packet_id") or ""),
        "route": route,
        "route_reason": long_reasons or ["default_normal"],
        "metrics": metrics,
        "missing_block_refs": [],
        "missing_asset_refs": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Route DOCX question packets to normal or long part normalization.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--membership-groups", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out-root", default="")
    parser.add_argument("--no-hard-fail-exit", action="store_true")
    args = parser.parse_args()

    config = read_json(Path(args.config))
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_question_complexity_router_v0_1")
    out_dir = out_root / args.run_id / args.doc_id / "complexity_router"
    blocks_by_id = load_blocks(args.paragraph_stream)
    tags_by_id = load_tags(args.block_tags)
    groups = load_groups(args.membership_groups)
    routes = [route_group(group, blocks_by_id, tags_by_id, config) for group in groups]
    route_counts = Counter(item["route"] for item in routes)
    hard_fail_items = [item for item in routes if item["route"] == "hard_fail"]
    long_items = [item for item in routes if item["route"] == "long_part_normalizer"]

    write_json(
        out_dir / "question_complexity_routes.json",
        {
            "schema_version": "docx_question_complexity_routes.v0.1",
            "doc_id": args.doc_id,
            "source_membership_groups": safe_rel(args.membership_groups),
            "items": routes,
        },
    )
    write_json(
        out_dir / "hard_fail_items.json",
        {"schema_version": "docx_question_complexity_hard_fail_items.v0.1", "items": hard_fail_items},
    )
    summary = {
        "schema_version": "docx_question_complexity_router_summary.v0.1",
        "status": "hard_fail" if hard_fail_items else "ok",
        "doc_id": args.doc_id,
        "input_group_count": len(groups),
        "route_counts": dict(sorted(route_counts.items())),
        "long_group_count": len(long_items),
        "hard_fail_count": len(hard_fail_items),
        "artifacts": {
            "question_complexity_routes": safe_rel(out_dir / "question_complexity_routes.json"),
            "hard_fail_items": safe_rel(out_dir / "hard_fail_items.json"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if hard_fail_items and not args.no_hard_fail_exit:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
