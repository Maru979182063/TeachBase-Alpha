from __future__ import annotations

from question_visual_structure_contract import normalize_review_flags


def compose_legacy_stem_md(
    stem_md: str,
    options: list[dict] | None,
    content_blocks: list[dict] | None,
    visual_assets: list[dict] | None,
) -> tuple[str, list[str]]:
    blocks = [item for item in (content_blocks or []) if isinstance(item, dict) and str(item.get("scope", "")) in {"stem", "option"}]
    blocks = sorted(blocks, key=lambda item: int(item.get("block_order", 0) or 0))
    asset_by_id = {str(item.get("asset_id", "") or ""): item for item in (visual_assets or []) if isinstance(item, dict)}
    option_asset_ids: dict[str, set[str]] = {}
    for option in options or []:
        key = str(option.get("option_key", "") or "")
        option_asset_ids[key] = {str(asset_id) for asset_id in (option.get("asset_ids", []) or []) if str(asset_id)}

    parts: list[str] = []
    review_flags: list[str] = []
    for block in blocks:
        block_type = str(block.get("block_type", "") or "")
        if block_type == "markdown":
            text_md = str(block.get("text_md", "") or "")
            if text_md.strip():
                parts.append(text_md.strip())
            continue
        if block_type != "image":
            continue
        asset_id = str(block.get("asset_id", "") or "")
        option_key = str(block.get("option_key", "") or "")
        asset = asset_by_id.get(asset_id)
        if not asset:
            review_flags.append("legacy_structure_mismatch")
            continue
        if str(asset.get("attach_status", "") or "") != "attached":
            continue
        if str(asset.get("placement_scope", "") or "") == "evidence_only":
            continue
        if option_key and asset_id not in option_asset_ids.get(option_key, set()):
            review_flags.append("legacy_structure_mismatch")
        parts.append(f"![{asset_id}]({asset.get('display_ref', '')})")

    if not parts and str(stem_md or "").strip():
        parts.append(str(stem_md or "").strip())
    return "\n\n".join(part for part in parts if str(part).strip()), normalize_review_flags(review_flags)
