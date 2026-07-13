from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def asset_role(asset: dict[str, Any]) -> str:
    return str(asset.get("asset_role") or asset.get("role") or "").strip()


def asset_placement(asset: dict[str, Any]) -> str:
    return str(asset.get("placement_scope") or asset.get("placement") or "").strip()


def is_cropped_asset(asset: dict[str, Any]) -> bool:
    role = asset_role(asset)
    return role in {"stem", "analysis", "option"}


def is_materialized(asset: dict[str, Any]) -> bool:
    return bool(asset.get("materialized")) and str(asset.get("file_status", "") or "") == "materialized"


def count_option_texts(record: dict[str, Any]) -> int:
    qvs = record.get("question_visual_structure", {}) if isinstance(record.get("question_visual_structure"), dict) else {}
    options = qvs.get("options", []) if isinstance(qvs.get("options"), list) else []
    return len([item for item in options if isinstance(item, dict) and str(item.get("option_key", "") or "").strip()])


def selected_scope_asset_ids(record: dict[str, Any], scope: str) -> list[str]:
    selected = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    values = selected.get(scope, []) if isinstance(selected.get(scope), list) else []
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def selected_option_asset_ids(record: dict[str, Any]) -> list[str]:
    selected = record.get("selected_scope_asset_ids", {}) if isinstance(record.get("selected_scope_asset_ids"), dict) else {}
    raw = selected.get("option_by_key", {}) if isinstance(selected.get("option_by_key"), dict) else {}
    values: list[str] = []
    for items in raw.values():
        if not isinstance(items, list):
            continue
        values.extend([str(item or "").strip() for item in items if str(item or "").strip()])
    return values


def display_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = record.get("display_blocks", [])
    return [item for item in blocks if isinstance(item, dict)] if isinstance(blocks, list) else []


def rendered_image_asset_ids(record: dict[str, Any], fields: set[str]) -> list[str]:
    values: list[str] = []
    for block in display_blocks(record):
        if str(block.get("type", "") or "").strip() != "image":
            continue
        field = str(block.get("field", "") or "").strip()
        asset_id = str(block.get("asset_id", "") or "").strip()
        if field in fields and asset_id:
            values.append(asset_id)
    return values


def field_has_rendered_content(record: dict[str, Any], fields: set[str]) -> bool:
    for block in display_blocks(record):
        field = str(block.get("field", "") or "").strip()
        if field not in fields:
            continue
        if str(block.get("type", "") or "").strip() == "image" and str(block.get("asset_id", "") or "").strip():
            return True
        if str(block.get("type", "") or "").strip() == "markdown" and str(block.get("content", "") or "").strip():
            return True
    return False


def audit_record(record: dict[str, Any]) -> dict[str, Any]:
    qid = str(record.get("question_id", "") or "")
    assets = [a for a in (record.get("assets", []) or []) if isinstance(a, dict)]
    assets_by_id = {
        str(a.get("asset_id", "") or "").strip(): a
        for a in assets
        if str(a.get("asset_id", "") or "").strip()
    }
    cropped = [a for a in assets if is_cropped_asset(a) and is_materialized(a)]
    stem_selected_ids = selected_scope_asset_ids(record, "stem")
    analysis_selected_ids = selected_scope_asset_ids(record, "analysis")
    option_selected_ids = selected_option_asset_ids(record)
    rendered_stem_ids = rendered_image_asset_ids(record, {"stem"})
    rendered_explanation_ids = rendered_image_asset_ids(record, {"answer", "analysis"})
    rendered_option_ids = rendered_image_asset_ids(record, {"option"})

    stem_assets = (
        [assets_by_id[item] for item in stem_selected_ids if item in assets_by_id]
        if stem_selected_ids
        else [a for a in cropped if asset_placement(a) == "after_stem" or asset_role(a) == "stem"]
    )
    analysis_assets = (
        [assets_by_id[item] for item in analysis_selected_ids if item in assets_by_id]
        if analysis_selected_ids
        else [a for a in cropped if asset_placement(a) == "after_analysis" or asset_role(a) == "analysis"]
    )
    option_assets = (
        [assets_by_id[item] for item in option_selected_ids if item in assets_by_id]
        if option_selected_ids
        else [a for a in cropped if asset_placement(a) == "option_inline" or asset_role(a) == "option"]
    )

    if rendered_stem_ids:
        stem_assets = [assets_by_id[item] for item in rendered_stem_ids if item in assets_by_id]
    if rendered_explanation_ids:
        analysis_assets = [assets_by_id[item] for item in rendered_explanation_ids if item in assets_by_id]
    if rendered_option_ids:
        option_assets = [assets_by_id[item] for item in rendered_option_ids if item in assets_by_id]

    gate = record.get("image_need_gate", {}) if isinstance(record.get("image_need_gate"), dict) else {}
    scope = record.get("figure_detection_scope", {}) if isinstance(record.get("figure_detection_scope"), dict) else {}
    needs_gate = bool(gate.get("needs_figure_detection", False))
    stem_requires_image = bool(record.get("stem_requires_image", False))
    analysis_requires_image = bool(record.get("analysis_requires_image", False))
    scope_option = bool(scope.get("option", False))
    scope_stem = bool(scope.get("stem", False))
    scope_analysis = bool(scope.get("analysis", False))
    explanation_content_present = field_has_rendered_content(record, {"answer", "analysis"})

    issues: list[str] = []
    warnings: list[str] = []
    evidence: list[str] = []

    if record.get("missing_assets"):
        issues.append("materialized_source_missing")
    if needs_gate and not cropped:
        issues.append("figure_detection_zero_assets")
    if scope_stem and not stem_assets and not option_assets:
        issues.append("stem_scope_no_stem_or_option_asset")
    if scope_analysis and explanation_content_present and not analysis_assets:
        issues.append("analysis_scope_no_analysis_asset")
    if stem_requires_image and not stem_assets and not option_assets:
        issues.append("stem_requires_image_no_asset")
    if analysis_requires_image and explanation_content_present and not analysis_assets:
        issues.append("analysis_requires_image_no_asset")

    option_count = count_option_texts(record)
    if scope_option:
        if not option_assets:
            issues.append("option_scope_no_option_asset")
        elif option_count >= 4 and len(option_assets) not in {option_count, 4}:
            issues.append("option_image_count_mismatch")

    if len(cropped) >= 6:
        warnings.append("many_cropped_assets_review_layout")

    for asset in cropped:
        detector = str(asset.get("detector_source", "") or "").strip()
        flags = [str(flag) for flag in (asset.get("review_flags", []) or [])]
        audit = asset.get("bbox_audit", {}) if isinstance(asset.get("bbox_audit"), dict) else {}
        suspect = audit.get("suspect_reasons", []) if isinstance(audit.get("suspect_reasons"), list) else []
        if "fallback" in detector:
            issues.append("fallback_figure_detection_used")
            evidence.append(str(asset.get("asset_id", "")))
        if "bbox_audit_invalid" in flags or audit.get("validity") == "invalid":
            issues.append("bbox_audit_invalid")
            evidence.append(str(asset.get("asset_id", "")))
        if "inline_figure_refine_shrink_rejected" in flags:
            warnings.append("refine_shrink_rejected_kept_coarse")
            evidence.append(str(asset.get("asset_id", "")))
        if "top_clip_risk" in suspect or "top_text_band_risk" in suspect:
            warnings.append("headless_crop_risk")
            evidence.append(str(asset.get("asset_id", "")))

    issues = sorted(set(issues))
    warnings = sorted(set(warnings))
    blocking_issues = {
        "materialized_source_missing",
        "figure_detection_zero_assets",
        "fallback_figure_detection_used",
        "bbox_audit_invalid",
        "stem_scope_no_stem_or_option_asset",
        "analysis_scope_no_analysis_asset",
        "stem_requires_image_no_asset",
        "analysis_requires_image_no_asset",
        "option_scope_no_option_asset",
        "option_image_count_mismatch",
    }
    if any(item in issues for item in blocking_issues):
        status = "fail"
    elif issues or warnings:
        status = "needs_review"
    else:
        status = "pass"

    return {
        "question_id": qid,
        "asset_package_status": status,
        "issues": issues,
        "warnings": warnings,
        "suggested_action": "rerun_figure_detection" if "figure_detection_zero_assets" in issues else ("manual_review" if status != "pass" else "accept"),
        "gate_needs_figure_detection": needs_gate,
        "gate_where": gate.get("where", []),
        "scope": scope,
        "stem_requires_image": stem_requires_image,
        "analysis_requires_image": analysis_requires_image,
        "cropped_asset_count": len(cropped),
        "stem_asset_count": len(stem_assets),
        "analysis_asset_count": len(analysis_assets),
        "option_asset_count": len(option_assets),
        "option_text_count": option_count,
        "evidence_asset_ids": sorted(set(item for item in evidence if item)),
    }


def render_html(rows: list[dict[str, Any]], manifest_path: Path) -> str:
    cards = []
    for row in rows:
        status = row["asset_package_status"]
        cls = {"pass": "ok", "needs_review": "warn", "fail": "bad"}.get(status, "warn")
        issues = ", ".join(row["issues"]) or "-"
        warnings = ", ".join(row["warnings"]) or "-"
        cards.append(
            "<tr>"
            f"<td>{html.escape(row['question_id'])}</td>"
            f"<td class='{cls}'>{html.escape(status)}</td>"
            f"<td>{html.escape(str(row['cropped_asset_count']))}</td>"
            f"<td>{html.escape(str(row['stem_asset_count']))}</td>"
            f"<td>{html.escape(str(row['analysis_asset_count']))}</td>"
            f"<td>{html.escape(str(row['option_asset_count']))}</td>"
            f"<td>{html.escape(issues)}</td>"
            f"<td>{html.escape(warnings)}</td>"
            f"<td>{html.escape(row['suggested_action'])}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>单题图片包审核</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 24px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d7deea; padding: 8px; vertical-align: top; }}
    th {{ background: #f1f5fb; position: sticky; top: 0; }}
    .ok {{ color: #047857; font-weight: 700; }}
    .warn {{ color: #b45309; font-weight: 700; }}
    .bad {{ color: #be123c; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>单题图片包审核</h1>
  <p>Manifest: {html.escape(str(manifest_path))}</p>
  <table>
    <thead><tr><th>题号</th><th>状态</th><th>裁图数</th><th>题干图</th><th>解析图</th><th>选项图</th><th>问题</th><th>警告</th><th>建议</th></tr></thead>
    <tbody>{''.join(cards)}</tbody>
  </table>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit per-question image asset packages after assetization.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    payload = read_json(manifest_path)
    records = payload.get("questions", []) if isinstance(payload, dict) else []
    rows = [audit_record(record) for record in records if isinstance(record, dict)]
    status_counts = Counter(row["asset_package_status"] for row in rows)
    issue_counts = Counter(issue for row in rows for issue in row["issues"])
    warning_counts = Counter(warning for row in rows for warning in row["warnings"])
    summary = {
        "schema_version": "question_asset_package_audit.v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": str(manifest_path),
        "question_count": len(rows),
        "status_counts": dict(status_counts),
        "issue_counts": dict(issue_counts),
        "warning_counts": dict(warning_counts),
        "fail_question_ids": [row["question_id"] for row in rows if row["asset_package_status"] == "fail"],
        "needs_review_question_ids": [row["question_id"] for row in rows if row["asset_package_status"] == "needs_review"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "asset_package_audit_summary.json", summary)
    write_json(out_dir / "asset_package_audit_rows.json", rows)
    (out_dir / "asset_package_audit.html").write_text(render_html(rows, manifest_path), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
