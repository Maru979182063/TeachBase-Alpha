from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

from english_ks_contract_v02 import write_text


def copy_review_assets(payload: dict[str, Any], out_dir: Path, workspace_root: Path) -> dict[str, str]:
    assets_dir = out_dir / "review_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for doc in payload.get("documents", []) or []:
        for image in doc.get("source_page_images", []) or []:
            source_path = workspace_root / str(image.get("path", ""))
            if not source_path.exists():
                continue
            target = assets_dir / f"{doc.get('doc_id')}_{source_path.name}"
            shutil.copy2(source_path, target)
            copied[str(image.get("page_id"))] = target.relative_to(out_dir).as_posix()
            image["review_asset_path"] = target.relative_to(out_dir).as_posix()
    return copied


def render_review(payload: dict[str, Any], out_dir: Path, workspace_root: Path) -> Path:
    copy_review_assets(payload, out_dir, workspace_root)
    sections: list[str] = []
    for doc in payload.get("documents", []) or []:
        images = []
        for image in doc.get("source_page_images", []) or []:
            src = image.get("review_asset_path", "")
            images.append(
                f"<figure><img src='{html.escape(src)}' loading='lazy'><figcaption>{html.escape(str(image.get('page_id','')))}</figcaption></figure>"
            )
        rows = []
        for obj in doc.get("semantic_objects", []) or []:
            rows.append(
                "<tr>"
                f"<td><b>{html.escape(str(obj.get('object_id','')))}</b><br>{html.escape(str(obj.get('open_description','')))}</td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('primary_role', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('completeness', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps({'region_groups': obj.get('source_region_group_refs', []), 'asset_groups': obj.get('asset_group_refs', [])}, ensure_ascii=False, indent=2))}</pre></td>"
                f"<td><pre>{html.escape(json.dumps(obj.get('projections', {}), ensure_ascii=False, indent=2))}</pre></td>"
                f"<td>{html.escape(str(obj.get('human_review_status','')))}</td>"
                "</tr>"
            )
        sections.append(
            f"<section><h2>{html.escape(str(doc.get('doc_id','')))}</h2>"
            f"<p>capture: {html.escape(str(doc.get('requested_page_range_capture_status','')))}; objects: {len(doc.get('semantic_objects', []))}; relations: {len(doc.get('relations', []))}</p>"
            f"<div class='image-grid'>{''.join(images)}</div>"
            "<table><thead><tr><th>Object</th><th>Role</th><th>Completeness</th><th>Grounding</th><th>Projections</th><th>Human</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></section>"
        )
    html_text = f"""<!doctype html><html><head><meta charset="utf-8"><title>Knowledge Structure Contract v0.2 Review</title>
<style>
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f8fb;color:#172033}}
section{{background:#fff;border:1px solid #dbe4f0;border-radius:10px;padding:14px;margin-bottom:18px}}
.note{{background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:10px}}
.image-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:12px 0}}
figure{{margin:0}}img{{max-width:100%;border:1px solid #d7deea;background:white}}figcaption{{font-size:11px;color:#64748b;word-break:break-all}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{border:1px solid #d8e0ea;padding:8px;vertical-align:top}}th{{background:#eef3f8}}
pre{{white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;max-height:280px;overflow:auto}}
</style></head><body>
<h1>Knowledge Structure Contract v0.2 Review</h1>
<div class="note">Portable review: images are copied into review_assets/. Human review status is NOT_REVIEWED or REQUIRED unless explicitly filled.</div>
<h2>Validation Summary</h2><pre>{html.escape(json.dumps(payload.get('validation_summary', {}), ensure_ascii=False, indent=2))}</pre>
{''.join(sections)}
</body></html>"""
    path = out_dir / "knowledge_structure_review.html"
    write_text(path, html_text)
    return path
