from __future__ import annotations

import argparse
import base64
import html
import json
import os
import shutil
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def asset_role(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_role") or asset.get("role") or "").strip()


def placement(asset: dict[str, Any]) -> str:
    return str(asset.get("placement_scope") or asset.get("placement") or "").strip()


def is_candidate(asset: dict[str, Any]) -> bool:
    if asset_role(asset) in {"question_source", "stem_source", "analysis_source", "evidence"}:
        return False
    if placement(asset) == "option_inline":
        return False
    if not bool(asset.get("materialized")) or str(asset.get("file_status", "")) != "materialized":
        return False
    return bool(asset.get("bbox_json"))


def bbox(asset: dict[str, Any]) -> dict[str, int]:
    raw = asset.get("bbox_json", {}) if isinstance(asset.get("bbox_json"), dict) else {}
    return {
        "x": int(raw.get("x", 0) or 0),
        "y": int(raw.get("y", 0) or 0),
        "w": int(raw.get("w", 0) or 0),
        "h": int(raw.get("h", 0) or 0),
    }


def iou(a: dict[str, int], b: dict[str, int]) -> float:
    ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(a["w"], 0) * max(a["h"], 0)
    area_b = max(b["w"], 0) * max(b["h"], 0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def overlap_smaller(a: dict[str, int], b: dict[str, int]) -> float:
    ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    smaller = min(max(a["w"], 0) * max(a["h"], 0), max(b["w"], 0) * max(b["h"], 0))
    return inter / smaller if smaller > 0 else 0.0


def quality_score(asset: dict[str, Any]) -> float:
    score = 0.0
    flags = set(str(f) for f in (asset.get("review_flags", []) or []))
    box = asset.get("bbox_json", {}) if isinstance(asset.get("bbox_json"), dict) else {}
    detector = str(box.get("detector_source", "") or "")
    if "bbox_audit_invalid" in flags:
        score -= 10
    if "bbox_audit_suspect" in flags:
        score -= 2
    if "bbox_needs_review" in flags:
        score -= 1
    if "analysis_rescan_model" in detector:
        score -= 0.75
    if str(asset.get("bbox_json", "")).find("rejected") >= 0:
        score -= 1
    b = bbox(asset)
    score += min((b["w"] * b["h"]) / 50000, 1.0)
    score += float(asset.get("confidence", 0.0) or 0.0)
    return score


def same_group_key(asset: dict[str, Any]) -> tuple[str, str, str]:
    return (
        asset_role(asset),
        placement(asset),
        str(asset.get("bbox_space", "") or ""),
    )


def asset_local_path(asset: dict[str, Any], manifest_path: Path) -> Path | None:
    debug = asset.get("debug", {}) if isinstance(asset.get("debug"), dict) else {}
    local = str(debug.get("local_path", "") or "")
    if local:
        path = Path(local)
        if path.exists():
            return path
    storage_key = str(asset.get("storage_key", "") or "")
    if storage_key:
        for base in [manifest_path.parent, manifest_path.parent.parent]:
            path = base / storage_key
            if path.exists():
                return path
    return None


def image_data_url(path: Path) -> str:
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def call_pair_model(api_key: str, model: str, asset_a: dict[str, Any], path_a: Path, asset_b: dict[str, Any], path_b: Path) -> dict[str, Any]:
    prompt = f"""你是数学题目入库流水线的“题内图片资产合并审核”节点。
请只判断两张裁图是否代表同一个题内图形资产。

判断口径：
1. 如果 A/B 是同一个图形的不同裁边、一个更干净一个带了少量红字/页眉/空白，输出 relation="same_asset"，并选择更干净、更完整的 keep。
2. 如果 A/B 是同一题里不同步骤、不同图1/图2/图3、不同辅助线版本、不同选项图，输出 relation="different_asset" 或 "variant_asset"，keep="both"。
3. 不要因为图形相似就合并；只有同一处图形的重复裁切才合并。
4. 如果不确定，输出 relation="uncertain"，keep="both"。

资产信息：
A: {asset_a.get('asset_id')} role={asset_role(asset_a)} placement={placement(asset_a)} bbox={bbox(asset_a)}
B: {asset_b.get('asset_id')} role={asset_role(asset_b)} placement={placement(asset_b)} bbox={bbox(asset_b)}

只返回 JSON：
{{
  "relation": "same_asset|different_asset|variant_asset|uncertain",
  "keep": "A|B|both",
  "confidence": 0.0,
  "reason": "简短说明"
}}"""
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url(path_a)}},
                    {"type": "image_url", "image_url": {"url": image_data_url(path_b)}},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    text = str(content).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed["_usage"] = payload.get("usage", {})
        return parsed
    return {"relation": "uncertain", "keep": "both", "confidence": 0.0, "reason": "invalid_model_json"}


def should_compare_pair(a: dict[str, Any], b: dict[str, Any], group_size: int) -> bool:
    box_a = bbox(a)
    box_b = bbox(b)
    if group_size <= 8:
        return True
    return iou(box_a, box_b) >= 0.12 or overlap_smaller(box_a, box_b) >= 0.45


def consolidate_record(
    record: dict[str, Any],
    *,
    manifest_path: Path,
    api_key: str = "",
    model: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assets = [a for a in (record.get("assets", []) or []) if isinstance(a, dict)]
    keep_ids: set[str] = {str(a.get("asset_id", "")) for a in assets if str(a.get("asset_id", ""))}
    actions: list[dict[str, Any]] = []

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for asset in assets:
        if is_candidate(asset):
            grouped.setdefault(same_group_key(asset), []).append(asset)

    for key, group in grouped.items():
        group = sorted(group, key=lambda a: (bbox(a)["y"], bbox(a)["x"], str(a.get("asset_id", ""))))
        consumed: set[str] = set()
        for idx, current in enumerate(group):
            current_id = str(current.get("asset_id", ""))
            if not current_id or current_id in consumed or current_id not in keep_ids:
                continue
            cluster = [current]
            current_box = bbox(current)
            for other in group[idx + 1 :]:
                other_id = str(other.get("asset_id", ""))
                if not other_id or other_id in consumed or other_id not in keep_ids:
                    continue
                other_box = bbox(other)
                is_same = False
                model_decision: dict[str, Any] = {}
                if api_key and model and should_compare_pair(current, other, len(group)):
                    path_a = asset_local_path(current, manifest_path)
                    path_b = asset_local_path(other, manifest_path)
                    if path_a and path_b:
                        try:
                            model_decision = call_pair_model(api_key, model, current, path_a, other, path_b)
                        except Exception as exc:
                            model_decision = {
                                "relation": "uncertain",
                                "keep": "both",
                                "confidence": 0.0,
                                "reason": f"pair_model_failed:{type(exc).__name__}",
                            }
                        relation = str(model_decision.get("relation", "") or "")
                        confidence = float(model_decision.get("confidence", 0.0) or 0.0)
                        is_same = relation == "same_asset" and confidence >= 0.68
                        if relation in {"different_asset", "variant_asset"}:
                            actions.append(
                                {
                                    "question_id": record.get("question_id", ""),
                                    "action": "keep_distinct",
                                    "strategy": "visual_pair_model",
                                    "group_key": list(key),
                                    "asset_ids": [current_id, other_id],
                                    "confidence": confidence,
                                    "reason": str(model_decision.get("reason", "")),
                                }
                            )
                            continue
                else:
                    is_same = iou(current_box, other_box) >= 0.72 or overlap_smaller(current_box, other_box) >= 0.88
                if is_same:
                    cluster.append(other)
                    consumed.add(other_id)
            if len(cluster) <= 1:
                continue
            keep = max(cluster, key=quality_score)
            keep_id = str(keep.get("asset_id", ""))
            drop = [item for item in cluster if str(item.get("asset_id", "")) != keep_id]
            drop_ids = [str(item.get("asset_id", "")) for item in drop]
            keep_ids.difference_update(drop_ids)
            actions.append(
                {
                    "question_id": record.get("question_id", ""),
                    "action": "merge_assets",
                    "strategy": "visual_pair_model" if api_key and model else "bbox_overlap_safe",
                    "group_key": list(key),
                    "keep_asset_id": keep_id,
                    "drop_asset_ids": drop_ids,
                    "confidence": 0.86,
                    "reason": "same visual asset according to pair review; kept cleaner candidate",
                }
            )

    new_record = dict(record)
    new_record["assets"] = [asset for asset in assets if str(asset.get("asset_id", "")) in keep_ids or not str(asset.get("asset_id", ""))]
    new_record["asset_consolidation_actions"] = [a for a in actions if a.get("question_id") == record.get("question_id")]
    return new_record, actions


def render_html(actions: list[dict[str, Any]], out_manifest: Path) -> str:
    rows = []
    for action in actions:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(action.get('question_id', '')))}</td>"
            f"<td>{html.escape(str(action.get('action', '')))}</td>"
            f"<td>{html.escape(str(action.get('keep_asset_id', '')))}</td>"
            f"<td>{html.escape(', '.join(action.get('drop_asset_ids', []) or action.get('asset_ids', []) or []))}</td>"
            f"<td>{html.escape(str(action.get('reason', '')))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Asset Visual Consolidation</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #132033; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d8e0ec; padding: 8px; vertical-align: top; }}
    th {{ background: #f3f6fb; text-align: left; }}
  </style>
</head>
<body>
  <h1>Asset Visual Consolidation</h1>
  <p>Consolidated manifest: {html.escape(str(out_manifest))}</p>
  <table>
    <thead><tr><th>question</th><th>action</th><th>keep</th><th>drop</th><th>reason</th></tr></thead>
    <tbody>{''.join(rows) if rows else '<tr><td colspan="5">No automatic merges.</td></tr>'}</tbody>
  </table>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate duplicate visual assets after assetization.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("VISUAL_TRANSCRIBE_MODEL", "doubao-seed-2-0-lite-260428"))
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = read_json(manifest_path)
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    new_questions = []
    actions: list[dict[str, Any]] = []
    for record in questions:
        if not isinstance(record, dict):
            continue
        new_record, record_actions = consolidate_record(
            record,
            manifest_path=manifest_path,
            api_key=str(args.api_key or "").strip(),
            model=str(args.model or "").strip(),
        )
        new_questions.append(new_record)
        actions.extend(record_actions)

    consolidated = dict(payload)
    consolidated["questions"] = new_questions
    consolidated["consolidation"] = {
        "schema_version": "asset_visual_consolidation.v0.1",
        "source_manifest": str(manifest_path),
        "action_count": len(actions),
    }
    summary = {
        "schema_version": "asset_visual_consolidation.v0.1",
        "source_manifest": str(manifest_path),
        "consolidated_manifest": str(out_dir / "consolidated_manifest.json"),
        "question_count": len(new_questions),
        "action_count": len(actions),
        "action_counts": dict(Counter(str(a.get("action", "")) for a in actions)),
    }
    write_json(out_dir / "consolidated_manifest.json", consolidated)
    write_json(out_dir / "consolidation_actions.json", actions)
    write_json(out_dir / "asset_visual_consolidation_summary.json", summary)
    (out_dir / "consolidation_review.html").write_text(render_html(actions, out_dir / "consolidated_manifest.json"), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
