from __future__ import annotations

import argparse
import html
import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import english_ks_contract_v02 as contract
from english_ks_projection_gate_v02 import completeness_for, project_v02
from english_ks_reference_validator_v02 import (
    valid_region_id,
    validate_all,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ELIGIBLE = False
FIXTURE_SPECIFIC = True


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value)).strip("_")


def bbox_to_px(bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return (
        max(0, min(width, round(width * x1 / 1000))),
        max(0, min(height, round(height * y1 / 1000))),
        max(0, min(width, round(width * x2 / 1000))),
        max(0, min(height, round(height * y2 / 1000))),
    )


def baseline_defects(payload: dict[str, Any], old_html_path: Path, call_path: Path) -> dict[str, Any]:
    defects: list[dict[str, Any]] = []
    for doc in payload.get("documents", []) or []:
        for obj in doc.get("semantic_objects", []) or []:
            oid = str(obj.get("object_id", ""))
            completeness = obj.get("completeness", {}) or {}
            projections = obj.get("projections", {}) or {}
            defect_flags = []
            for target_name in ("knowledge_structure", "faithful_material"):
                status = str((projections.get(target_name) or {}).get("status", ""))
                if status == "READY_WITH_SOURCE_REGIONS" and completeness.get("source_region_grounding") != "COMPLETE":
                    defect_flags.append(f"{target_name}_ready_with_unverified_source_region")
            if not obj.get("asset_group_refs") and completeness.get("asset_grounding") != "NOT_CREATED":
                defect_flags.append("no_asset_group_but_asset_grounding_not_not_created")
            if not obj.get("asset_group_refs") and completeness.get("structured_extraction") == "ASSET_ONLY":
                defect_flags.append("no_asset_group_but_asset_only_structured_extraction")
            derivation = projections.get("derivation") or {}
            if derivation.get("status") == "NOT_APPLICABLE" and derivation.get("requires"):
                defect_flags.append("not_applicable_derivation_with_requires")
            qbank = projections.get("qbank_projection") or {}
            if qbank.get("as_is_status") == "BLOCKED" and not qbank.get("blocking_requirements"):
                defect_flags.append("blocked_qbank_without_blocking_requirements")
            if defect_flags:
                defects.append({"doc_id": doc.get("doc_id"), "object_id": oid, "defect_flags": defect_flags})
        object_by_id = {str(obj.get("object_id")): obj for obj in doc.get("semantic_objects", []) or []}
        for region in doc.get("source_regions", []) or []:
            flags = []
            if region.get("verification_status") == "VERIFIED" and not region.get("source_bundle_id"):
                flags.append("verified_evidence_missing_source_bundle_id")
            if not valid_region_id(str(region.get("region_id", ""))):
                flags.append("malformed_region_id")
            if flags:
                defects.append({"doc_id": doc.get("doc_id"), "evidence_id": region.get("evidence_id"), "defect_flags": flags})
        for rel in doc.get("relations", []) or []:
            if rel.get("predicate") == "depends_on":
                subject = object_by_id.get(str(rel.get("subject")), {})
                independence_claim = subject.get("independence_claim", {})
                if (
                    isinstance(independence_claim, dict)
                    and independence_claim.get("value") is True
                    and independence_claim.get("provenance")
                ):
                    defects.append(
                        {
                            "doc_id": doc.get("doc_id"),
                            "relation_id": rel.get("relation_id"),
                            "defect_flags": ["explicit_independence_claim_depends_on_conflict_requires_human_review"],
                        }
                    )
    html_flags = []
    if old_html_path.exists():
        old_html = old_html_path.read_text(encoding="utf-8", errors="replace").lower()
        if "overlay" not in old_html:
            html_flags.append("review_html_lacks_bbox_overlay")
        if "stitched" not in old_html:
            html_flags.append("review_html_lacks_stitched_preview")
    else:
        html_flags.append("previous_review_html_missing")
    if html_flags:
        defects.append({"artifact": rel_workspace(old_html_path), "defect_flags": html_flags})
    call_flags = []
    if call_path.exists():
        call = contract.read_json(call_path)
        if not call.get("input_manifest"):
            call_flags.append("targeted_call_full_input_manifest_not_persisted")
    else:
        call_flags.append("targeted_call_file_missing")
    if call_flags:
        defects.append({"artifact": rel_workspace(call_path), "defect_flags": call_flags})
    return {
        "schema": f"{contract.SCHEMA_VERSION}.contract_closure.baseline_defect_reproduction",
        "source": "actual targeted v0.2 replay artifact",
        "defects": defects,
        "summary": {
            "defect_count": len(defects),
            "ready_with_unverified_source_region": sum(
                1 for item in defects for flag in item["defect_flags"] if "ready_with_unverified_source_region" in flag
            ),
            "asset_state_confusion": sum(
                1
                for item in defects
                for flag in item["defect_flags"]
                if flag in {"no_asset_group_but_asset_grounding_not_not_created", "no_asset_group_but_asset_only_structured_extraction"}
            ),
            "html_review_gaps": sum(1 for item in defects for flag in item["defect_flags"] if flag.startswith("review_html_lacks")),
        },
    }


def owner_for_group(doc: dict[str, Any], group_id: str) -> dict[str, Any] | None:
    for obj in doc.get("semantic_objects", []) or []:
        if group_id in (obj.get("source_region_group_refs") or []):
            return obj
    return None


def group_coverage(doc: dict[str, Any], obj: dict[str, Any]) -> tuple[bool, bool, bool]:
    groups = {
        str(group.get("source_region_group_id")): group
        for group in doc.get("source_region_groups", []) or []
    }
    refs = [str(ref) for ref in obj.get("source_region_group_refs", []) or []]
    statuses = [str(groups.get(ref, {}).get("coverage_status", "")) for ref in refs if ref in groups]
    return bool(refs), "COMPLETE" in statuses, "PARTIAL" in statuses


def bbox_contains(container: list[Any], bbox: list[Any]) -> bool:
    try:
        cx1, cy1, cx2, cy2 = [float(v) for v in container]
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return False
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    return cx1 <= center_x <= cx2 and cy1 <= center_y <= cy2


def spatial_source_bundle_id(doc: dict[str, Any], region: dict[str, Any]) -> str:
    page_no = int(region.get("page_number", 0) or 0)
    bbox = region.get("bbox_norm1000")
    if not isinstance(bbox, list):
        return ""
    page_candidates = []
    for bundle in doc.get("source_bundles", []) or []:
        bundle_id = str(bundle.get("source_bundle_id", ""))
        for frag in (bundle.get("fragments", []) or []) + (bundle.get("child_assets", []) or []):
            if int(frag.get("page", 0) or 0) != page_no:
                continue
            page_candidates.append(bundle_id)
            if bbox_contains(frag.get("bbox_norm1000", []), bbox):
                return bundle_id
    return page_candidates[0] if page_candidates else ""


def close_contract(payload: dict[str, Any]) -> dict[str, Any]:
    closed = deepcopy(payload)
    closed["schema"] = f"{contract.SCHEMA_VERSION}.projection"
    closed["contract_closure"] = {
        "schema": f"{contract.SCHEMA_VERSION}.contract_closure",
        "closed_at": datetime.now().isoformat(timespec="seconds"),
        "new_model_calls": 0,
        "runtime_import_enabled": False,
        "normalization_policy": "deterministic contract closure; no new visual fact generation",
    }
    for doc in closed.get("documents", []) or []:
        object_by_id = {str(obj.get("object_id")): obj for obj in doc.get("semantic_objects", []) or []}
        for group in doc.get("source_region_groups", []) or []:
            owner = owner_for_group(doc, str(group.get("source_region_group_id", "")))
            if owner and (owner.get("completeness") or {}).get("semantic_capture") == "PARTIAL":
                group["coverage_status"] = "PARTIAL"
            elif str(group.get("coverage_status", "")) == "COMPLETE":
                group["coverage_status"] = "COMPLETE"
            elif str(group.get("coverage_status", "")) == "PARTIAL":
                group["coverage_status"] = "PARTIAL"
            else:
                group["coverage_status"] = "UNVERIFIED"
            group["source_region_group_only_not_asset"] = True
            group["asset_group_id"] = ""
        doc["asset_groups"] = [
            group
            for group in doc.get("asset_groups", []) or []
            if group.get("asset_group_id") and group.get("members")
        ]
        for region in doc.get("source_regions", []) or []:
            if not region.get("source_bundle_id"):
                for obj in doc.get("semantic_objects", []) or []:
                    if region.get("evidence_id") in (obj.get("typed_evidence_refs") or []) and obj.get("source_bundle_refs"):
                        region["source_bundle_id"] = obj["source_bundle_refs"][0]
                        break
            if not region.get("source_bundle_id"):
                region["source_bundle_id"] = spatial_source_bundle_id(doc, region)
            if region.get("source_bundle_id"):
                for obj in doc.get("semantic_objects", []) or []:
                    if region.get("evidence_id") in (obj.get("typed_evidence_refs") or []):
                        refs = obj.setdefault("source_bundle_refs", [])
                        if region["source_bundle_id"] not in refs:
                            refs.append(region["source_bundle_id"])
            if not valid_region_id(str(region.get("region_id", ""))):
                region["source_region_id_raw"] = region.get("region_id", "")
                region["source_region_id_parse_status"] = "UNPARSEABLE"
                region["raw_id_unchanged"] = True
        group_by_id = {
            str(group.get("source_region_group_id")): group
            for group in doc.get("source_region_groups", []) or []
        }
        for group in doc.get("source_region_groups", []) or []:
            fixed_members = []
            for index, member in enumerate(sorted(group.get("members", []) or [], key=lambda item: int(item.get("sequence", 0) or 0)), start=1):
                evidence = next((r for r in doc.get("source_regions", []) or [] if r.get("evidence_id") == member.get("evidence_id")), None)
                if evidence:
                    member["page_id"] = evidence.get("page_id", member.get("page_id", ""))
                    member["region_id"] = evidence.get("region_id", member.get("region_id", ""))
                member["sequence"] = index
                fixed_members.append(member)
            group["members"] = fixed_members
        for obj in doc.get("semantic_objects", []) or []:
            has_region_group, has_complete_region_group, has_partial_region_group = group_coverage(doc, obj)
            has_complete_asset_group = False
            obj["asset_group_refs"] = []
            obj["completeness"] = completeness_for(
                obj,
                has_region_group=has_region_group,
                has_complete_region_group=has_complete_region_group,
                has_partial_region_group=has_partial_region_group,
                has_complete_asset_group=has_complete_asset_group,
            )
            obj["projections"] = project_v02(
                obj,
                has_region_group=has_region_group,
                has_complete_region_group=has_complete_region_group,
                has_partial_region_group=has_partial_region_group,
                has_complete_asset_group=has_complete_asset_group,
            )
            if obj["completeness"]["source_region_grounding"] == "COMPLETE" and obj["completeness"]["semantic_capture"] == "COMPLETE":
                obj["human_review_status"] = "NOT_REVIEWED"
            else:
                obj["human_review_status"] = "REQUIRED"
            obj["contract_closure_notes"] = [
                "asset_group_not_created" if not obj.get("asset_group_refs") else "asset_group_present",
                f"source_region_grounding={obj['completeness']['source_region_grounding']}",
            ]
            for group_id in obj.get("source_region_group_refs", []) or []:
                group = group_by_id.get(str(group_id))
                if group and group.get("coverage_status") != "COMPLETE":
                    obj.setdefault("uncertainties", [])
                    uncertainty = f"source region group {group_id} coverage is {group.get('coverage_status')}"
                    if uncertainty not in obj["uncertainties"]:
                        obj["uncertainties"].append(uncertainty)
        for rel in doc.get("relations", []) or []:
            if rel.get("predicate") == "depends_on":
                subject = object_by_id.get(str(rel.get("subject")), {})
                independence_claim = subject.get("independence_claim", {})
                if (
                    isinstance(independence_claim, dict)
                    and independence_claim.get("value") is True
                    and independence_claim.get("provenance")
                ):
                    rel["human_review_required"] = True
                    rel["contract_warning"] = "EXPLICIT_CLAIM_CONFLICT: independence claim coexists with depends_on relation"
    return closed


def copy_images_and_render_overlays(payload: dict[str, Any], out_dir: Path) -> dict[str, dict[str, str]]:
    assets_dir = out_dir / "review_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, str]] = {}
    color_by_status = {"COMPLETE": "#16a34a", "PARTIAL": "#f97316", "UNVERIFIED": "#2563eb"}
    for doc in payload.get("documents", []) or []:
        doc_id = str(doc.get("doc_id", "doc"))
        page_regions: dict[str, list[dict[str, Any]]] = {}
        region_to_group = {}
        for group in doc.get("source_region_groups", []) or []:
            for member in group.get("members", []) or []:
                region_to_group[str(member.get("evidence_id"))] = group
        for region in doc.get("source_regions", []) or []:
            page_regions.setdefault(str(region.get("page_id")), []).append(region)
        for image in doc.get("source_page_images", []) or []:
            src = workspace_path(str(image.get("path", "")))
            if not src.exists():
                continue
            copied = assets_dir / f"{doc_id}_{src.name}"
            shutil.copy2(src, copied)
            overlay = assets_dir / f"{doc_id}_{src.stem}_overlay.png"
            with Image.open(src) as im:
                canvas = im.convert("RGB")
                draw = ImageDraw.Draw(canvas)
                width, height = canvas.size
                for region in page_regions.get(str(image.get("page_id")), []):
                    bbox = region.get("bbox_norm1000")
                    if not isinstance(bbox, list) or len(bbox) != 4:
                        continue
                    group = region_to_group.get(str(region.get("evidence_id")), {})
                    status = str(group.get("coverage_status", "UNVERIFIED"))
                    color = color_by_status.get(status, "#64748b")
                    box = bbox_to_px(bbox, width, height)
                    draw.rectangle(box, outline=color, width=4)
                    draw.text((box[0] + 4, box[1] + 4), f"{region.get('evidence_id')} {status}", fill=color)
                canvas.save(overlay)
            image["review_asset_path"] = copied.relative_to(out_dir).as_posix()
            image["overlay_asset_path"] = overlay.relative_to(out_dir).as_posix()
            result[str(image.get("page_id"))] = {
                "source": image["review_asset_path"],
                "overlay": image["overlay_asset_path"],
            }
    return result


def render_stitched_previews(payload: dict[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    assets_dir = out_dir / "review_assets"
    previews: list[dict[str, Any]] = []
    for doc in payload.get("documents", []) or []:
        page_by_id = {str(page.get("page_id")): page for page in doc.get("source_page_images", []) or []}
        region_by_id = {str(region.get("evidence_id")): region for region in doc.get("source_regions", []) or []}
        owner_by_group = {
            group_id: str(obj.get("object_id"))
            for obj in doc.get("semantic_objects", []) or []
            for group_id in obj.get("source_region_group_refs", []) or []
        }
        for group in doc.get("source_region_groups", []) or []:
            group_id = str(group.get("source_region_group_id", ""))
            owner_id = owner_by_group.get(group_id, "")
            if str(group.get("coverage_status", "")) != "COMPLETE":
                continue
            crops = []
            for member in sorted(group.get("members", []) or [], key=lambda item: int(item.get("sequence", 0) or 0)):
                region = region_by_id.get(str(member.get("evidence_id")))
                if not region:
                    continue
                page = page_by_id.get(str(region.get("page_id")))
                if not page:
                    continue
                image_path = workspace_path(str(page.get("path", "")))
                if not image_path.exists():
                    continue
                with Image.open(image_path) as im:
                    box = bbox_to_px(region["bbox_norm1000"], im.width, im.height)
                    crops.append(im.convert("RGB").crop(box))
            if not crops:
                continue
            width = max(crop.width for crop in crops)
            height = sum(crop.height for crop in crops) + 18 * (len(crops) - 1)
            stitched = Image.new("RGB", (width, height), "white")
            y = 0
            for crop in crops:
                stitched.paste(crop, (0, y))
                y += crop.height + 18
            target = assets_dir / f"stitched_{safe_id(group_id)}_review_only.png"
            stitched.save(target)
            previews.append(
                {
                    "source_region_group_id": group_id,
                    "owner_object_id": owner_id,
                    "path": target.relative_to(out_dir).as_posix(),
                    "review_derivative_only_not_asset_group": True,
                    "members": group.get("members", []),
                }
            )
    return previews


def object_validation_index(report: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    indexed: dict[str, list[dict[str, str]]] = {}
    for key in (
        "reference_integrity_errors",
        "reference_integrity_warnings",
        "semantic_contract_errors",
        "semantic_contract_warnings",
        "projection_gate_errors",
        "projection_gate_warnings",
    ):
        severity = "warning" if key.endswith("warnings") else "error"
        for item in report.get(key, []) or []:
            path = str(item.get("path", ""))
            indexed.setdefault(path, []).append({"severity": severity, "message": str(item.get("message", "")), "source": key})
    return indexed


def render_review(payload: dict[str, Any], out_dir: Path, validation: dict[str, Any], stitched: list[dict[str, Any]]) -> Path:
    index = object_validation_index(validation)
    stitched_by_owner: dict[str, list[dict[str, Any]]] = {}
    for preview in stitched:
        stitched_by_owner.setdefault(str(preview.get("owner_object_id")), []).append(preview)
    sections = []
    for doc in payload.get("documents", []) or []:
        image_html = []
        for page in doc.get("source_page_images", []) or []:
            image_html.append(
                "<figure>"
                f"<img src='{html.escape(str(page.get('overlay_asset_path','')))}' loading='lazy'>"
                f"<figcaption>{html.escape(str(page.get('page_id','')))} overlay</figcaption>"
                "</figure>"
            )
        rows = []
        for obj in doc.get("semantic_objects", []) or []:
            oid = str(obj.get("object_id", ""))
            previews = "".join(
                f"<figure><img src='{html.escape(str(item['path']))}' loading='lazy'><figcaption>stitched preview, review only, not asset_group<br>{html.escape(str(item['source_region_group_id']))}</figcaption></figure>"
                for item in stitched_by_owner.get(oid, [])
            )
            findings = index.get(oid, [])
            findings_html = "".join(
                f"<li class='{html.escape(item['severity'])}'>{html.escape(item['severity'])}: {html.escape(item['message'])}</li>"
                for item in findings
            ) or "<li>no object-level validator finding</li>"
            groups = [
                group
                for group in doc.get("source_region_groups", []) or []
                if group.get("source_region_group_id") in (obj.get("source_region_group_refs") or [])
            ]
            rows.append(
                "<tr>"
                f"<td><b>{html.escape(oid)}</b><br>{html.escape(str(obj.get('open_description','')))}</td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('completeness', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(groups, ensure_ascii=False, indent=2))}</pre>{previews}</td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('projections', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td>{html.escape(str(obj.get('human_review_status','')))}<ul>{findings_html}</ul></td>"
                "</tr>"
            )
        sections.append(
            f"<section><h2>{html.escape(str(doc.get('doc_id','')))}</h2>"
            f"<div class='image-grid'>{''.join(image_html)}</div>"
            "<table><thead><tr><th>Object</th><th>Completeness</th><th>Source Regions</th><th>Projections</th><th>Review</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></section>"
        )
    html_text = f"""<!doctype html><html><head><meta charset="utf-8"><title>Knowledge Structure Contract Closure v0.2</title>
<style>
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f8fb;color:#172033}}
.note{{background:#ecfeff;border:1px solid #67e8f9;border-radius:8px;padding:10px;margin:10px 0}}
section{{background:#fff;border:1px solid #dbe4f0;border-radius:8px;padding:14px;margin-bottom:18px}}
.image-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:12px 0}}
figure{{margin:0}}img{{max-width:100%;border:1px solid #d7deea;background:white}}figcaption{{font-size:11px;color:#64748b;word-break:break-all}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{border:1px solid #d8e0ea;padding:8px;vertical-align:top}}th{{background:#eef3f8}}
pre{{white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;max-height:300px;overflow:auto}}
.warning{{color:#b45309}}.error{{color:#b91c1c}}
</style></head><body>
<h1>Knowledge Structure Contract Closure v0.2</h1>
<div class="note">This is a local deterministic contract closure. No new model calls. Stitched previews are review derivatives only, not asset groups.</div>
<h2>Validation Summary</h2><pre>{html.escape(json.dumps(validation, ensure_ascii=False, indent=2))}</pre>
{''.join(sections)}
</body></html>"""
    path = out_dir / "knowledge_structure_review.html"
    contract.write_text(path, html_text)
    return path


def write_reports(
    out_dir: Path,
    payload: dict[str, Any],
    validation: dict[str, Any],
    baseline: dict[str, Any],
    call_path: Path,
    stitched: list[dict[str, Any]],
) -> dict[str, Any]:
    contract.write_json(out_dir / "baseline_defect_reproduction.json", baseline)
    contract.write_text(
        out_dir / "baseline_defect_reproduction.md",
        "# Baseline Defect Reproduction\n\n"
        + "\n".join(f"- `{item.get('object_id') or item.get('evidence_id') or item.get('relation_id') or item.get('artifact')}`: {', '.join(item['defect_flags'])}" for item in baseline["defects"])
        + "\n",
    )
    contract.write_json(out_dir / "knowledge_structure_projection_v02_closed.json", payload)
    contract.write_json(out_dir / "knowledge_structure_projection_v02_closed.schema.json", contract.contract_schema())
    contract.write_json(out_dir / "reference_integrity_report.json", {k: v for k, v in validation.items() if k.startswith("reference")})
    contract.write_json(out_dir / "semantic_contract_report.json", {k: v for k, v in validation.items() if k.startswith("semantic")})
    contract.write_json(out_dir / "relation_validation_report.json", {k: v for k, v in validation.items() if k.startswith("reference") or k.startswith("projection")})
    contract.write_json(out_dir / "projection_gate_report.json", {k: v for k, v in validation.items() if k.startswith("projection")})
    repro = {
        "schema": f"{contract.SCHEMA_VERSION}.targeted_call_reproducibility",
        "targeted_call_path": rel_workspace(call_path),
        "input_manifest_persistence": "NOT_PERSISTED",
        "call_reproducibility": "PARTIAL",
        "reason": "The targeted verifier artifact contains prompt/image hashes and response, but not the full model input manifest content.",
    }
    if call_path.exists():
        call = contract.read_json(call_path)
        repro["prompt_snapshot_present"] = bool(call.get("prompt_snapshot"))
        repro["image_manifest_present"] = bool(call.get("image_manifest"))
        repro["input_manifest_sha256_present"] = bool(call.get("input_manifest_sha256"))
    contract.write_json(out_dir / "targeted_call_reproducibility_report.json", repro)
    contract.write_json(
        out_dir / "human_review_template.json",
        {
            "schema": f"{contract.SCHEMA_VERSION}.human_review_template",
            "human_review_status": "NOT_REVIEWED",
            "rows": [
                {
                    "doc_id": doc.get("doc_id"),
                    "object_id": obj.get("object_id"),
                    "source_region_coverage_verdict": "NOT_REVIEWED",
                    "semantic_contract_verdict": "NOT_REVIEWED",
                    "projection_verdict": "NOT_REVIEWED",
                    "accepted_corrected_rejected": "NOT_REVIEWED",
                    "reviewer_note": "",
                }
                for doc in payload.get("documents", [])
                for obj in doc.get("semantic_objects", [])
            ],
        },
    )
    contract.write_json(
        out_dir / "review_asset_manifest.json",
        {
            "schema": f"{contract.SCHEMA_VERSION}.review_asset_manifest",
            "stitched_previews_are_assets": False,
            "stitched_previews": stitched,
        },
    )
    contract.write_text(
        out_dir / "implementation_report.md",
        "# Contract Closure Implementation Report\n\n"
        "- New model calls: 0\n"
        "- Runtime import: disabled\n"
        "- Source-region groups and asset groups are separated.\n"
        "- Stitched previews are review derivatives only and are not referenced as asset groups.\n",
    )
    return repro


def final_label(validation: dict[str, Any], repro: dict[str, Any]) -> str:
    hard_valid = all(
        validation.get(key)
        for key in (
            "json_schema_valid",
            "reference_integrity_valid",
            "semantic_contract_valid",
            "projection_gate_valid",
        )
    )
    if not hard_valid:
        return "CONTRACT_CLOSURE_FAILED"
    has_warnings = any(
        validation.get(key)
        for key in (
            "reference_integrity_warnings",
            "semantic_contract_warnings",
            "projection_gate_warnings",
        )
    )
    if has_warnings or repro.get("call_reproducibility") != "FULL":
        return "CONTRACT_CLOSED_WITH_WARNINGS"
    return "KNOWLEDGE_STRUCTURE_EVIDENCE_CONTRACT_READY_FOR_HUMAN_REVIEW"


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = workspace_path(args.input)
    old_html_path = workspace_path(args.previous_review_html) if args.previous_review_html else Path("__missing_previous_review_html__")
    call_path = workspace_path(args.targeted_call)
    out_dir = workspace_path(args.out)
    if out_dir.exists():
        if args.clean:
            shutil.rmtree(out_dir)
        else:
            raise SystemExit(f"output_exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    source_payload = contract.read_json(input_path)
    baseline = baseline_defects(source_payload, old_html_path, call_path)
    closed = close_contract(source_payload)
    validation = validate_all(closed)
    closed["validation_summary"] = validation
    copy_images_and_render_overlays(closed, out_dir)
    stitched = render_stitched_previews(closed, out_dir)
    review_html = render_review(closed, out_dir, validation, stitched)
    repro = write_reports(out_dir, closed, validation, baseline, call_path, stitched)
    summary = {
        "schema": f"{contract.SCHEMA_VERSION}.contract_closure.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_input": rel_workspace(input_path),
        "out_dir": rel_workspace(out_dir),
        "new_model_calls": 0,
        "runtime_import_enabled": False,
        "json_schema_valid": validation["json_schema_valid"],
        "reference_integrity_valid": validation["reference_integrity_valid"],
        "semantic_contract_valid": validation["semantic_contract_valid"],
        "projection_gate_valid": validation["projection_gate_valid"],
        "projection_gate_warning_count": len(validation.get("projection_gate_warnings", [])),
        "baseline_defect_count": baseline["summary"]["defect_count"],
        "input_manifest_persistence": repro["input_manifest_persistence"],
        "call_reproducibility": repro["call_reproducibility"],
        "review_html": rel_workspace(review_html),
        "review_assets_dir": rel_workspace(out_dir / "review_assets"),
        "final_label": final_label(validation, repro),
    }
    contract.write_json(out_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Close English KS v0.2 evidence contract without model calls.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--targeted-call", required=True)
    parser.add_argument("--previous-review-html", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
