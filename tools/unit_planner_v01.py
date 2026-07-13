from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "unit_plan.v0.1"
PLANNER_VERSION = "open_unit_planner_local_v0.1_visual_first"


@dataclass
class VisualSeedBlock:
    visual_block_id: str
    page: int
    bbox_image: list[int]
    block_type: str
    source: str
    legacy_segment_id: str = ""
    label: str = ""
    checkpoint: str = ""
    confidence: float = 0.65


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _bbox_union(boxes: list[list[int]]) -> list[int]:
    valid = [box for box in boxes if isinstance(box, list) and len(box) == 4]
    if not valid:
        return [0, 0, 0, 0]
    return [
        min(int(box[0]) for box in valid),
        min(int(box[1]) for box in valid),
        max(int(box[2]) for box in valid),
        max(int(box[3]) for box in valid),
    ]


def _intersects(a: list[int], b: list[int]) -> bool:
    if not (isinstance(a, list) and isinstance(b, list) and len(a) == 4 and len(b) == 4):
        return False
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def infer_subject(pdf_path: str, profile: str) -> dict:
    text = f"{pdf_path} {profile}".replace("\\", "/").lower()
    if "english" in text or "英语" in text or "高考一轮" in text:
        return {"value": "english", "source": "path_or_profile", "confidence": 0.95}
    if "biology" in text or "生物" in text:
        return {"value": "biology", "source": "path_or_profile", "confidence": 0.95}
    if "math" in text or "数学" in text or "senior_math" in text or "junior_geometry" in text:
        return {"value": "math", "source": "path_or_profile", "confidence": 0.95}
    return {"value": "unknown", "source": "inferred_unknown", "confidence": 0.2}


def infer_document_flavor(pdf_path: str, subject: str) -> dict:
    text = pdf_path.replace("\\", "/").lower()
    if subject == "english":
        if any(token in text for token in ["阅读", "reading", "主旨题", "应用文-教师版"]):
            return {"value": "english_reading", "source": "path", "confidence": 0.85}
        if any(token in text for token in ["写作", "求助信", "应用文4", "writing"]):
            return {"value": "english_writing", "source": "path", "confidence": 0.85}
        return {"value": "english_general", "source": "subject_default", "confidence": 0.55}
    if subject == "math":
        return {"value": "math_handout", "source": "subject_default", "confidence": 0.65}
    if subject == "biology":
        return {"value": "biology_handout", "source": "subject_default", "confidence": 0.65}
    return {"value": "unknown", "source": "inferred_unknown", "confidence": 0.2}


def build_visual_seed_blocks(segments: list[Any]) -> list[VisualSeedBlock]:
    seeds: list[VisualSeedBlock] = []
    for idx, seg in enumerate(segments or [], start=1):
        seeds.append(
            VisualSeedBlock(
                visual_block_id=f"useg_{idx:05d}",
                page=int(_get(seg, "page", 0) or 0),
                bbox_image=[
                    int(_get(seg, "x0", 0) or 0),
                    int(_get(seg, "y0", 0) or 0),
                    int(_get(seg, "x1", 0) or 0),
                    int(_get(seg, "y1", 0) or 0),
                ],
                block_type=str(_get(seg, "kind", "") or "segment"),
                source="legacy_segment_as_visual_seed",
                legacy_segment_id=str(_get(seg, "segment_id", "") or ""),
                label=str(_get(seg, "label", "") or ""),
                checkpoint=str(_get(seg, "checkpoint", "") or ""),
            )
        )
    return seeds


def _role_from_text(text: str, subject: str, document_flavor: str, role_hint: str = "") -> tuple[str, list[str]]:
    clean = _norm_text(text)
    reasons: list[str] = []
    if role_hint in {"answer", "analysis", "translation", "question_head"}:
        reasons.append(f"reading_role_hint:{role_hint}")
        return role_hint, reasons

    if re.match(r"^\s*(?:\d{1,2}[\).、]|[A-D][\).、])", clean):
        reasons.append("visible_question_or_choice_head")
        return "question_body", reasons
    if any(token in clean for token in ["【答案】", "答案", "Answer"]):
        reasons.append("answer_marker")
        return "answer", reasons
    if any(token in clean for token in ["【解析】", "解析", "分析", "Explanation"]):
        reasons.append("analysis_marker")
        return "analysis", reasons
    if any(token in clean for token in ["【翻译】", "翻译", "Translation"]):
        reasons.append("translation_marker")
        return "translation", reasons
    if subject == "english" and document_flavor == "english_writing":
        if any(token in clean for token in ["课程目标", "知识梳理", "要点回顾", "要点小测"]):
            reasons.append("writing_knowledge_marker")
            return "knowledge", reasons
        if any(token in clean for token in ["审题", "写作", "求助信", "范文", "Dear", "Yours"]):
            reasons.append("writing_task_marker")
            return "writing_task", reasons
        if any(token in clean for token in ["翻译下列句子", "句子", "词汇", "短语"]):
            reasons.append("writing_drill_marker")
            return "exercise", reasons
    if subject == "english" and document_flavor == "english_reading":
        if any(token in clean for token in ["passage", "阅读", "文章", "主旨", "体裁"]):
            reasons.append("reading_passage_marker")
            return "passage", reasons
    if any(token in clean for token in ["知识", "要点", "课程目标", "方法", "梳理"]):
        reasons.append("generic_knowledge_marker")
        return "knowledge", reasons
    return "text", reasons or ["default_text"]


def _route_for_unit(semantic_role: str, container_role: str, layout_role: str, subject: str, flavor: str) -> str:
    if semantic_role == "question":
        if container_role == "group" and flavor == "english_reading":
            return "passage_group_split"
        return "question_split"
    if semantic_role == "passage":
        return "passage_group_split"
    if semantic_role == "writing_task":
        return "writing_task_split"
    if semantic_role in {"knowledge", "section"}:
        return "knowledge_assemble"
    if semantic_role == "example":
        return "example_group_split"
    if semantic_role in {"answer", "analysis", "translation"}:
        return "attach_to_previous_unit"
    return "review_only"


def _child_contract_for(semantic_role: str, flavor: str) -> list[dict]:
    if semantic_role in {"passage", "question"} and flavor == "english_reading":
        return [
            {"role": "passage_or_stem", "min": 1, "max": 1},
            {"role": "question_items", "min": 1, "max": 99},
            {"role": "answer", "min": 0, "max": 99},
            {"role": "analysis", "min": 0, "max": 99},
            {"role": "translation", "min": 0, "max": 99},
        ]
    if semantic_role == "writing_task":
        return [
            {"role": "task_prompt", "min": 1, "max": 1},
            {"role": "analysis_table", "min": 0, "max": 3},
            {"role": "vocabulary_bank", "min": 0, "max": 3},
            {"role": "model_answer", "min": 0, "max": 3},
            {"role": "answer_analysis", "min": 0, "max": 3},
        ]
    if semantic_role == "question":
        return [
            {"role": "stem", "min": 1, "max": 1},
            {"role": "choices", "min": 0, "max": 1},
            {"role": "answer", "min": 0, "max": 1},
            {"role": "analysis", "min": 0, "max": 1},
        ]
    return [{"role": "content", "min": 1, "max": 99}]


def _layout_role_for(reading_blocks: list[Any], visual_ids: list[str]) -> str:
    text = "\n".join(str(_get(block, "text", "") or "") for block in reading_blocks)
    if visual_ids and reading_blocks:
        return "visual_primary_text_attached"
    if visual_ids:
        return "visual_panel"
    if "|" in text or "____" in text or "表" in text:
        return "table_or_form"
    return "text_only"


def _make_unit(
    unit_id: str,
    semantic_role: str,
    blocks: list[Any],
    visual_seeds: list[VisualSeedBlock],
    subject: str,
    flavor: str,
    reasons: list[str],
    confidence: float,
    continuation_state: str = "none",
) -> dict:
    pages = sorted({int(_get(block, "page", 0) or 0) for block in blocks} | {seed.page for seed in visual_seeds})
    reading_ids = [str(_get(block, "reading_block_id", "") or "") for block in blocks if _get(block, "reading_block_id", "")]
    visual_ids = [seed.visual_block_id for seed in visual_seeds]
    layout_role = _layout_role_for(blocks, visual_ids)
    container_role = "group" if len(blocks) > 1 or len(pages) > 1 else "atomic"
    route = _route_for_unit(semantic_role, container_role, layout_role, subject, flavor)
    risk_flags: list[str] = []
    if len(pages) > 1:
        risk_flags.append("cross_page")
    if route == "review_only":
        risk_flags.append("no_registered_auto_route")
    if visual_ids:
        risk_flags.append("visual_seed_present")
    bbox_by_page = []
    for page in pages:
        boxes: list[list[int]] = []
        for seed in visual_seeds:
            if seed.page == page:
                boxes.append(seed.bbox_image)
        if not boxes:
            for block in blocks:
                if int(_get(block, "page", 0) or 0) == page:
                    boxes.append(list(_get(block, "bbox_image", []) or []))
        bbox_by_page.append({"page": page, "bbox_image": _bbox_union(boxes)})
    return {
        "unit_id": unit_id,
        "semantic_role": semantic_role,
        "container_role": container_role,
        "layout_role": layout_role,
        "route": route,
        "source_refs": {
            "reading_block_ids": reading_ids,
            "visual_block_ids": visual_ids,
            "legacy_segment_ids": [seed.legacy_segment_id for seed in visual_seeds if seed.legacy_segment_id],
        },
        "child_contract": _child_contract_for(semantic_role, flavor),
        "asset_policy": {
            "figure_binding": "question" if semantic_role == "question" else "unit",
            "option_binding": "auto_detect_within_route" if semantic_role == "question" else "none",
        },
        "continuation": {
            "state": continuation_state,
            "previous_unit_id": None,
            "candidate_next_pages": [max(pages) + 1] if continuation_state == "open" and pages else [],
            "candidate_block_ids": [],
            "expected_continuation_roles": ["answer", "analysis", "translation"] if subject == "english" else ["analysis"],
        },
        "pages": pages,
        "bbox_by_page": bbox_by_page,
        "text_stub": _norm_text("\n".join(str(_get(block, "text", "") or "") for block in blocks))[:240],
        "bbox_policy": "visual_seed_primary" if visual_ids else "text_fallback",
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "reasons": reasons,
        "risk_flags": risk_flags,
        "decision": "planned" if route != "review_only" else "needs_review",
    }


def _attach_visual_seeds_to_blocks(blocks: list[Any], seeds: list[VisualSeedBlock]) -> dict[str, list[VisualSeedBlock]]:
    attached: dict[str, list[VisualSeedBlock]] = {}
    for seed in seeds:
        candidates = []
        for block in blocks:
            if int(_get(block, "page", 0) or 0) != seed.page:
                continue
            if _intersects(seed.bbox_image, list(_get(block, "bbox_image", []) or [])):
                candidates.append(block)
        if candidates:
            nearest = sorted(candidates, key=lambda b: abs(int(_get(b, "bbox_image", [0, 0, 0, 0])[1]) - seed.bbox_image[1]))[0]
            attached.setdefault(str(_get(nearest, "reading_block_id", "")), []).append(seed)
        else:
            attached.setdefault(f"__page_{seed.page}", []).append(seed)
    return attached


def _semantic_role_from_seed(seed: VisualSeedBlock, subject: str, flavor: str, block_text: str) -> tuple[str, list[str], float]:
    label_text = _norm_text(f"{seed.block_type} {seed.label} {seed.checkpoint} {block_text}")
    reasons = [f"visual_seed_type:{seed.block_type}"]
    if seed.block_type in {"course_goal", "knowledge", "checkpoint"}:
        return "knowledge", reasons, 0.76
    if subject == "english" and flavor == "english_writing":
        if any(token in label_text for token in ["课程目标", "知识梳理", "要点回顾", "course_goal", "knowledge"]):
            return "knowledge", reasons + ["writing_knowledge_visual_seed"], 0.78
        return "writing_task", reasons + ["english_writing_visual_seed"], 0.74
    if subject == "english" and flavor == "english_reading":
        if seed.block_type in {"example", "practice", "advanced", "after_class"}:
            return "passage", reasons + ["english_reading_group_visual_seed"], 0.74
        return "knowledge", reasons + ["english_reading_structure_visual_seed"], 0.72
    if subject == "math":
        if seed.block_type in {"example", "practice", "advanced", "after_class"}:
            return "question", reasons + ["math_question_visual_seed"], 0.76
        return "knowledge", reasons + ["math_knowledge_visual_seed"], 0.72
    return "question" if seed.block_type in {"example", "practice", "advanced", "after_class"} else "knowledge", reasons, 0.62


def build_unit_plan(
    pdf_path: str,
    profile: str,
    page_manifests: list[Any],
    reading_blocks: list[Any],
    segments: list[Any],
) -> dict:
    subject_info = infer_subject(pdf_path, profile)
    subject = subject_info["value"]
    flavor_info = infer_document_flavor(pdf_path, subject)
    flavor = flavor_info["value"]
    visual_seeds = build_visual_seed_blocks(segments)
    seed_by_block = _attach_visual_seeds_to_blocks(reading_blocks, visual_seeds)
    units: list[dict] = []
    assigned_reading_ids: set[str] = set()
    assigned_visual_ids: set[str] = set()

    current_blocks: list[Any] = []
    current_visual: list[VisualSeedBlock] = []
    current_role = ""
    current_reasons: list[str] = []
    counter = 1

    def flush(confidence: float = 0.72, continuation_state: str = "none") -> None:
        nonlocal current_blocks, current_visual, current_role, current_reasons, counter
        if not current_blocks and not current_visual:
            return
        role = current_role or "knowledge"
        units.append(
            _make_unit(
                f"unit_{counter:05d}",
                role,
                current_blocks,
                current_visual,
                subject,
                flavor,
                list(dict.fromkeys(current_reasons or ["window_grouped_blocks"])),
                confidence,
                continuation_state=continuation_state,
            )
        )
        for block in current_blocks:
            assigned_reading_ids.add(str(_get(block, "reading_block_id", "")))
        for seed in current_visual:
            assigned_visual_ids.add(seed.visual_block_id)
        counter += 1
        current_blocks = []
        current_visual = []
        current_role = ""
        current_reasons = []

    sorted_blocks = sorted(reading_blocks, key=lambda b: (int(_get(b, "page", 0) or 0), int((_get(b, "bbox_image", [0, 0, 0, 0]) or [0, 0, 0, 0])[1]), int((_get(b, "bbox_image", [0, 0, 0, 0]) or [0, 0, 0, 0])[0])))

    if visual_seeds:
        used_reading_ids: set[str] = set()
        for seed in sorted(visual_seeds, key=lambda item: (item.page, item.bbox_image[1], item.bbox_image[0])):
            seed_blocks: list[Any] = []
            for block in sorted_blocks:
                block_id = str(_get(block, "reading_block_id", "") or "")
                if block_id in used_reading_ids:
                    continue
                if int(_get(block, "page", 0) or 0) != seed.page:
                    continue
                if _intersects(seed.bbox_image, list(_get(block, "bbox_image", []) or [])):
                    seed_blocks.append(block)
                    used_reading_ids.add(block_id)
            block_text = "\n".join(str(_get(block, "text", "") or "") for block in seed_blocks)
            semantic_role, reasons, confidence = _semantic_role_from_seed(seed, subject, flavor, block_text)
            units.append(
                _make_unit(
                    f"unit_{counter:05d}",
                    semantic_role,
                    seed_blocks,
                    [seed],
                    subject,
                    flavor,
                    reasons,
                    confidence,
                )
            )
            for block in seed_blocks:
                assigned_reading_ids.add(str(_get(block, "reading_block_id", "")))
            assigned_visual_ids.add(seed.visual_block_id)
            counter += 1
    else:
        for block in sorted_blocks:
            role, reasons = _role_from_text(str(_get(block, "text", "") or ""), subject, flavor, str(_get(block, "role_hint", "") or ""))
            block_id = str(_get(block, "reading_block_id", "") or "")
            block_visual = seed_by_block.get(block_id, [])
            if role in {"answer", "analysis", "translation"} and current_blocks:
                current_blocks.append(block)
                current_visual.extend(block_visual)
                current_reasons.extend(reasons)
                continue
            if role in {"answer", "analysis", "translation"} and units:
                # Late answers without active text stay separate but are marked for attachment.
                current_blocks = [block]
                current_visual = block_visual
                current_role = role
                current_reasons = reasons
                flush(confidence=0.55)
                continue
            if role in {"question_body", "passage", "writing_task", "knowledge", "exercise"}:
                semantic_role = "question" if role in {"question_body", "exercise"} else role
                if current_blocks and semantic_role != current_role:
                    flush()
                current_blocks.append(block)
                current_visual.extend(block_visual)
                current_role = semantic_role
                current_reasons.extend(reasons)
                continue
            if current_blocks:
                current_blocks.append(block)
                current_visual.extend(block_visual)
                current_reasons.extend(reasons)
            else:
                current_blocks = [block]
                current_visual = block_visual
                current_role = "knowledge" if flavor in {"english_writing", "biology_handout"} else "question"
                current_reasons = reasons
        flush(continuation_state="open" if units and units[-1].get("pages", [0])[-1] < len(page_manifests) else "none")

        # Visual-only seeds still matter, especially diagram/table pages without text/OCR.
        for page_key, seeds in seed_by_block.items():
            if not page_key.startswith("__page_"):
                continue
            for seed in seeds:
                if seed.visual_block_id in assigned_visual_ids:
                    continue
                semantic_role = "knowledge" if seed.block_type in {"knowledge", "course_goal", "checkpoint"} else "question"
                units.append(
                    _make_unit(
                        f"unit_{counter:05d}",
                        semantic_role,
                        [],
                        [seed],
                        subject,
                        flavor,
                        ["visual_seed_without_reading_block"],
                        0.52,
                    )
                )
                assigned_visual_ids.add(seed.visual_block_id)
                counter += 1

    for block in sorted_blocks:
        block_id = str(_get(block, "reading_block_id", "") or "")
        if not block_id or block_id in assigned_reading_ids:
            continue
        units.append(
            _make_unit(
                f"unit_{counter:05d}",
                "unknown",
                [block],
                [],
                subject,
                flavor,
                ["unassigned_reading_block_promoted_to_review_unit"],
                0.35,
            )
        )
        assigned_reading_ids.add(block_id)
        counter += 1

    all_reading_ids = {str(_get(block, "reading_block_id", "")) for block in reading_blocks if _get(block, "reading_block_id", "")}
    all_visual_ids = {seed.visual_block_id for seed in visual_seeds}
    route_counts = Counter(unit["route"] for unit in units)
    role_counts = Counter(unit["semantic_role"] for unit in units)
    overlap_conflicts: list[dict] = []
    owner_by_reading: dict[str, str] = {}
    for unit in units:
        for block_id in unit["source_refs"]["reading_block_ids"]:
            previous = owner_by_reading.get(block_id)
            if previous and previous != unit["unit_id"]:
                overlap_conflicts.append({"block_id": block_id, "unit_ids": [previous, unit["unit_id"]]})
            owner_by_reading[block_id] = unit["unit_id"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "planner_version": PLANNER_VERSION,
        "truthfulness_note": "Local open unit planner output. It is an upstream planning artifact and does not replace audited semantic nodes yet.",
        "document": {
            "document_type": "teacher_handout",
            "source_path": pdf_path,
            "profile": profile,
            "subject": subject_info,
            "document_flavor": flavor_info,
        },
        "window": {
            "pages": [int(_get(page, "page", 0) or 0) for page in page_manifests],
            "reading_block_ids": sorted(all_reading_ids),
            "visual_block_ids": sorted(all_visual_ids),
        },
        "visual_seed_blocks": [asdict(seed) for seed in visual_seeds],
        "units": units,
        "coverage": {
            "assigned_reading_block_ids": sorted(assigned_reading_ids & all_reading_ids),
            "unassigned_reading_block_ids": sorted(all_reading_ids - assigned_reading_ids),
            "assigned_visual_block_ids": sorted(assigned_visual_ids & all_visual_ids),
            "unassigned_visual_block_ids": sorted(all_visual_ids - assigned_visual_ids),
            "overlap_conflicts": overlap_conflicts,
        },
        "audit": {
            "unit_count": len(units),
            "route_counts": dict(route_counts),
            "semantic_role_counts": dict(role_counts),
            "coverage_pass": not (all_reading_ids - assigned_reading_ids) and not overlap_conflicts,
            "route_consumer_required": sorted(route_counts),
            "warnings": [],
        },
    }
    if payload["coverage"]["unassigned_visual_block_ids"]:
        payload["audit"]["warnings"].append("visual_seed_unassigned")
    if payload["coverage"]["unassigned_reading_block_ids"]:
        payload["audit"]["warnings"].append("reading_block_unassigned")
    if overlap_conflicts:
        payload["audit"]["warnings"].append("reading_block_overlap_conflict")
    return payload


def write_unit_plan_outputs(payload: dict, out_dir: Path) -> None:
    plan_dir = out_dir / "unit_planner_v0.1"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "unit_plan_v0.1.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for unit in payload.get("units", []):
        refs = unit.get("source_refs", {})
        rows.append(
            "<article class='card'>"
            f"<h2>{html.escape(unit.get('unit_id',''))} <span>{html.escape(unit.get('semantic_role',''))} / {html.escape(unit.get('route',''))}</span></h2>"
            f"<div class='meta'>pages: {html.escape(','.join(map(str, unit.get('pages', []))))} | confidence: {unit.get('confidence', 0)}</div>"
            f"<div class='meta'>container: {html.escape(unit.get('container_role',''))} | layout: {html.escape(unit.get('layout_role',''))} | decision: {html.escape(unit.get('decision',''))}</div>"
            f"<div class='meta'>reading: {html.escape(', '.join(refs.get('reading_block_ids', [])))}</div>"
            f"<div class='meta'>visual: {html.escape(', '.join(refs.get('visual_block_ids', [])))}</div>"
            f"<div class='flags'>{html.escape(', '.join(unit.get('risk_flags', [])))}</div>"
            f"<pre>{html.escape(unit.get('text_stub',''))}</pre>"
            f"<div class='reason'>{html.escape('; '.join(unit.get('reasons', [])))}</div>"
            "</article>"
        )
    audit = payload.get("audit", {})
    coverage = payload.get("coverage", {})
    doc = payload.get("document", {})
    html_text = f"""<!doctype html>
<meta charset="utf-8">
<title>Unit Planner v0.1</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;color:#172033;margin:24px}}
.summary{{background:#fff;border:1px solid #d9e1ef;border-radius:12px;padding:16px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:16px}}
.card{{background:#fff;border:1px solid #d9e1ef;border-radius:12px;padding:14px;box-shadow:0 1px 4px rgba(10,30,60,.06)}}
h1{{margin:0 0 10px}} h2{{font-size:16px;margin:0 0 8px}} h2 span{{font-size:12px;color:#5d6b82}}
.meta{{font-size:13px;color:#35445c;margin-bottom:7px}}.flags{{font-size:13px;color:#9b341f;margin-bottom:7px}}.reason{{font-size:12px;color:#606f85}}
pre{{white-space:pre-wrap;background:#f8fafc;border-radius:8px;padding:8px;max-height:180px;overflow:auto}}
code{{background:#eef4ff;padding:1px 4px;border-radius:4px}}
</style>
<body>
<section class="summary">
<h1>Unit Planner v0.1</h1>
<p>这是开放 unit planner 的候选产物：它引用 block/visual seed，只规划业务单元和 route，不直接裁最终图。</p>
<p>subject: <code>{html.escape(str((doc.get('subject') or {}).get('value','')))}</code> |
flavor: <code>{html.escape(str((doc.get('document_flavor') or {}).get('value','')))}</code> |
profile: <code>{html.escape(str(doc.get('profile','')))}</code></p>
<p>units: <b>{audit.get('unit_count', 0)}</b> |
routes: <code>{html.escape(json.dumps(audit.get('route_counts', {}), ensure_ascii=False))}</code> |
roles: <code>{html.escape(json.dumps(audit.get('semantic_role_counts', {}), ensure_ascii=False))}</code></p>
<p>unassigned reading: {len(coverage.get('unassigned_reading_block_ids', []))} |
unassigned visual: {len(coverage.get('unassigned_visual_block_ids', []))} |
conflicts: {len(coverage.get('overlap_conflicts', []))}</p>
<p>warnings: <code>{html.escape(', '.join(audit.get('warnings', [])))}</code></p>
</section>
<main class="grid">
{''.join(rows)}
</main>
</body>
"""
    (plan_dir / "unit_plan_v0.1.html").write_text(html_text, encoding="utf-8")
