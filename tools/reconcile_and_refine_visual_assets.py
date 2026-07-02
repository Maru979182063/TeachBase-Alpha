from __future__ import annotations

import argparse
import base64
import html
import json
import os
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

import option_anchor_detection
import assetize_question_images


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def asset_role(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_role") or asset.get("role") or "").strip()


def placement(asset: dict[str, Any]) -> str:
    return str(asset.get("placement_scope") or asset.get("placement") or "").strip()


def is_materialized(asset: dict[str, Any]) -> bool:
    return bool(asset.get("materialized")) and str(asset.get("file_status", "") or "") == "materialized"


def is_cropped_asset(asset: dict[str, Any]) -> bool:
    return asset_role(asset) in {"stem", "analysis", "option"} and is_materialized(asset)


def local_path(asset: dict[str, Any], manifest_path: Path) -> Path | None:
    debug = asset.get("debug", {}) if isinstance(asset.get("debug"), dict) else {}
    raw = str(debug.get("local_path", "") or "")
    if raw and Path(raw).exists():
        return Path(raw)
    key = str(asset.get("storage_key", "") or "")
    if key:
        for base in (manifest_path.parent, manifest_path.parent.parent):
            path = base / key
            if path.exists():
                return path
    return None


def cropped_by_role(record: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [
        item
        for item in (record.get("assets", []) or [])
        if isinstance(item, dict) and is_cropped_asset(item) and asset_role(item) == role
    ]


def clone_for_role(asset: dict[str, Any], role: str, index: int, reason: str) -> dict[str, Any]:
    cloned = deepcopy(asset)
    old_id = str(asset.get("asset_id", "") or f"asset_{index:03d}")
    new_id = f"{old_id}__as_{role}_{index:03d}"
    cloned["asset_id"] = new_id
    cloned["asset_role"] = role
    cloned["role"] = role
    cloned["placement_scope"] = "after_stem" if role == "stem" else "after_analysis"
    cloned["placement"] = cloned["placement_scope"]
    cloned["display_ref"] = f"asset://{new_id}"
    cloned["attach_status"] = "attached"
    cloned["ownership_relinked_from_asset_id"] = old_id
    cloned["ownership_relink_reason"] = reason
    cloned["review_flags"] = sorted(
        set([str(f) for f in (cloned.get("review_flags", []) or [])] + [f"asset_ownership_relinked_to_{role}"])
    )
    debug = cloned.get("debug", {}) if isinstance(cloned.get("debug"), dict) else {}
    debug["ownership_relinked_from_asset_id"] = old_id
    cloned["debug"] = debug
    return cloned


def reconcile_ownership(record: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    assets = record.get("assets", []) if isinstance(record.get("assets"), list) else []
    scope = record.get("figure_detection_scope", {}) if isinstance(record.get("figure_detection_scope"), dict) else {}
    scope_stem = bool(scope.get("stem", False))
    scope_analysis = bool(scope.get("analysis", False))

    stem_assets = cropped_by_role(record, "stem")
    analysis_assets = cropped_by_role(record, "analysis")
    option_assets = cropped_by_role(record, "option")

    if scope_stem and not stem_assets and not option_assets and analysis_assets:
        candidates = [a for a in analysis_assets if str(a.get("bbox_space", "") or "") == "question_image"] or analysis_assets
        for idx, asset in enumerate(candidates, start=1):
            assets.append(clone_for_role(asset, "stem", idx, "planner_requires_stem_but_asset_was_analysis"))
            actions.append(
                {
                    "question_id": record.get("question_id", ""),
                    "action": "copy_analysis_asset_to_stem",
                    "source_asset_id": asset.get("asset_id", ""),
                }
            )

    stem_assets = cropped_by_role(record, "stem")
    analysis_assets = cropped_by_role(record, "analysis")
    if scope_analysis and not analysis_assets and stem_assets:
        candidates = [a for a in stem_assets if str(a.get("bbox_space", "") or "") == "question_image"] or stem_assets
        for idx, asset in enumerate(candidates, start=1):
            assets.append(clone_for_role(asset, "analysis", idx, "planner_requires_analysis_but_asset_was_stem"))
            actions.append(
                {
                    "question_id": record.get("question_id", ""),
                    "action": "copy_stem_asset_to_analysis",
                    "source_asset_id": asset.get("asset_id", ""),
                }
            )

    record["assets"] = assets
    if actions:
        record["asset_ownership_reconcile_actions"] = actions
    return actions


def valid_bbox(raw: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, dict):
        return None
    try:
        x = int(float(raw.get("x", 0) or 0))
        y = int(float(raw.get("y", 0) or 0))
        w = int(float(raw.get("w", 0) or 0))
        h = int(float(raw.get("h", 0) or 0))
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    x1 = max(0, min(x, width - 1))
    y1 = max(0, min(y, height - 1))
    x2 = max(x1 + 1, min(x + w, width))
    y2 = max(y1 + 1, min(y + h, height))
    return x1, y1, x2, y2


def refine_asset(
    record: dict[str, Any],
    asset: dict[str, Any],
    *,
    manifest_path: Path,
    out_dir: Path,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    qid = str(record.get("question_id", "") or "question")
    aid = str(asset.get("asset_id", "") or "asset")
    path = local_path(asset, manifest_path)
    flags = [str(f) for f in (asset.get("review_flags", []) or [])]
    if not path:
        asset["review_flags"] = sorted(set(flags + ["final_asset_quality_missing_local_path"]))
        return {"question_id": qid, "asset_id": aid, "action": "missing_local_path"}
    if not api_key:
        asset["review_flags"] = sorted(set(flags + ["final_asset_quality_model_not_run_missing_api_key"]))
        return {"question_id": qid, "asset_id": aid, "action": "model_not_run_missing_api_key"}
    try:
        with Image.open(path) as im:
            image = im.convert("RGB")
            width, height = image.size
            payload = option_anchor_detection._call_inline_figure_refine_model(api_key, model, image)
            asset["final_asset_quality_model_payload"] = payload
            if not bool(payload.get("is_valid_figure", True)):
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_model_invalid_figure"]))
                return {"question_id": qid, "asset_id": aid, "action": "model_invalid_figure"}
            bbox = valid_bbox(payload.get("bbox", {}), width, height)
            if not bbox:
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_bbox_invalid"]))
                return {"question_id": qid, "asset_id": aid, "action": "bbox_invalid"}
            x1, y1, x2, y2 = bbox
            area_ratio = ((x2 - x1) * (y2 - y1)) / max(width * height, 1)
            if area_ratio < 0.55:
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_shrink_rejected_keep_current"]))
                return {
                    "question_id": qid,
                    "asset_id": aid,
                    "action": "shrink_rejected_keep_current",
                    "area_ratio": round(area_ratio, 4),
                }
            if area_ratio > 0.985 and x1 <= 2 and y1 <= 2:
                asset["review_flags"] = sorted(set(flags + ["final_asset_quality_checked_no_change"]))
                return {"question_id": qid, "asset_id": aid, "action": "checked_no_change"}
            refined = image.crop((x1, y1, x2, y2))
            refined_dir = out_dir / "refined_assets" / qid
            refined_dir.mkdir(parents=True, exist_ok=True)
            refined_path = refined_dir / f"{aid}.png"
            refined.save(refined_path)
            debug = asset.get("debug", {}) if isinstance(asset.get("debug"), dict) else {}
            debug["pre_final_refine_local_path"] = str(path)
            debug["local_path"] = str(refined_path)
            asset["debug"] = debug
            asset["storage_key"] = str(refined_path.relative_to(out_dir)).replace("\\", "/")
            asset["image_width"] = refined.width
            asset["image_height"] = refined.height
            asset["review_flags"] = sorted(set(flags + ["final_asset_quality_refined_by_model"]))
            return {
                "question_id": qid,
                "asset_id": aid,
                "action": "refined_by_model",
                "area_ratio": round(area_ratio, 4),
            }
    except Exception as exc:
        asset["review_flags"] = sorted(set(flags + ["final_asset_quality_model_failed"]))
        return {"question_id": qid, "asset_id": aid, "action": "model_failed", "error": str(exc)[:240]}


def image_data_url(path: Path) -> str:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def render_review(records: list[dict[str, Any]], manifest_path: Path) -> str:
    cards: list[str] = []
    for record in records:
        qid = html.escape(str(record.get("question_id", "") or ""))
        cropped = [a for a in (record.get("assets", []) or []) if isinstance(a, dict) and is_cropped_asset(a)]
        if not cropped:
            continue
        imgs: list[str] = []
        for asset in cropped:
            path = local_path(asset, manifest_path)
            if not path:
                continue
            flags = ", ".join(str(f) for f in (asset.get("review_flags", []) or []))
            imgs.append(
                "<figure>"
                f"<img src='{image_data_url(path)}'>"
                f"<figcaption>{html.escape(asset_role(asset))} | {html.escape(str(asset.get('asset_id','')))}<br>{html.escape(flags)}</figcaption>"
                "</figure>"
            )
        cards.append(f"<section><h2>{qid}</h2><div class='assets'>{''.join(imgs)}</div></section>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Asset Ownership Reconcile & Final Quality Review</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;background:#f6f3ed;color:#172033;margin:24px}}
section{{background:white;border:1px solid #ded4c6;border-radius:14px;padding:16px;margin:0 0 18px}}
h2{{font-size:18px;margin:0 0 12px}}
.assets{{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}}
figure{{margin:0;border:1px solid #d9e0ec;border-radius:10px;padding:10px;background:#fbfdff;max-width:360px}}
img{{max-width:330px;max-height:260px;display:block;margin:auto}}
figcaption{{font-size:12px;line-height:1.45;color:#4a5870;margin-top:8px;word-break:break-all}}
</style>
</head>
<body>
<h1>Asset Ownership Reconcile & Final Quality Review</h1>
{''.join(cards)}
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--skip-model-refine", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = read_json(manifest_path)
    records = payload.get("questions", []) if isinstance(payload.get("questions"), list) else []

    ownership_actions: list[dict[str, Any]] = []
    quality_actions: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        ownership_actions.extend(reconcile_ownership(record))
        for asset in list(record.get("assets", []) or []):
            if not isinstance(asset, dict) or not is_cropped_asset(asset):
                continue
            if args.skip_model_refine:
                asset["review_flags"] = sorted(
                    set([str(f) for f in (asset.get("review_flags", []) or [])] + ["final_asset_quality_model_skipped"])
                )
                continue
            quality_actions.append(
                refine_asset(
                    record,
                    asset,
                    manifest_path=manifest_path,
                    out_dir=out_dir,
                    api_key=str(args.api_key or ""),
                    model=str(args.model or ""),
                )
            )
        try:
            record["display_blocks"] = assetize_question_images.build_display_blocks(record)
            record["display_markdown"] = assetize_question_images.build_markdown(record)
        except Exception as exc:
            record["display_rebuild_error"] = str(exc)[:240]

    payload["questions"] = records
    payload["asset_ownership_reconcile"] = {
        "schema_version": "asset_ownership_reconcile.v0.1",
        "action_count": len(ownership_actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in ownership_actions)),
    }
    payload["final_asset_quality"] = {
        "schema_version": "final_asset_quality.v0.1",
        "action_count": len(quality_actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in quality_actions)),
        "model_refine_enabled": not args.skip_model_refine and bool(str(args.api_key or "")),
    }
    out_manifest = out_dir / "reconciled_refined_manifest.json"
    write_json(out_manifest, payload)
    write_json(out_dir / "ownership_actions.json", ownership_actions)
    write_json(out_dir / "quality_actions.json", quality_actions)
    summary = {
        "manifest": str(out_manifest),
        "ownership_action_count": len(ownership_actions),
        "ownership_action_counts": dict(Counter(str(a.get("action", "")) for a in ownership_actions)),
        "quality_action_count": len(quality_actions),
        "quality_action_counts": dict(Counter(str(a.get("action", "")) for a in quality_actions)),
    }
    write_json(out_dir / "reconcile_refine_summary.json", summary)
    (out_dir / "reconcile_refine_review.html").write_text(render_review(records, out_manifest), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
