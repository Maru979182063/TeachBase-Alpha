from __future__ import annotations

import argparse
import base64
import http.client
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from PIL import Image
from PIL import ImageDraw, ImageFont

try:
    from tools import vision_prompt_store
except ImportError:  # pragma: no cover - keeps direct script execution working.
    import vision_prompt_store
from tools.crop_executor_v03 import execute_crops_v03
from tools.cross_page_node_accumulator_v03 import NodeFragmentV03, SemanticNodeV03, write_nodes
from tools.layout_block_extractor_v03 import BlockCandidateV03
from tools.page_render_adapter_v03 import PageManifestV03
from tools.question_slice_auditor_v03 import audit_nodes_v03, write_audit_report
from tools.split_pipeline_v03 import build_legacy_bridge, build_review_repair_pool, write_json


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
TARGET_REASONS = {"page_bottom_may_continue", "short_question_without_solution_evidence", "swallows_next_section"}
JUDGE_REASONS = {"page_bottom_may_continue", "short_question_without_solution_evidence"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _extract_json_block(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_object_not_found")
    return json.loads(clean[start : end + 1])


def _pil_image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _call_model(api_key: str, model: str, image: Image.Image, prompt: str, system_prompt: str) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            return _extract_json_block(payload["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"http_{exc.code}: {detail}")
            if exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, http.client.RemoteDisconnected, json.JSONDecodeError, KeyError, ValueError) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"model_call_failed_after_retries: {last_error}") from last_error


def _load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", size)
    except Exception:
        return ImageFont.load_default()


def _nodes_from_json(payload: dict[str, Any]) -> list[SemanticNodeV03]:
    nodes: list[SemanticNodeV03] = []
    for item in payload.get("nodes", []) or []:
        fragments = [
            NodeFragmentV03(
                int(fragment.get("page", 0) or 0),
                [int(v) for v in fragment.get("bbox_px", [])[:4]],
                str(fragment.get("role", "") or "fragment"),
                [str(v) for v in fragment.get("block_ids", []) or []],
                [str(v) for v in fragment.get("flags", []) or []],
            )
            for fragment in item.get("fragments", []) or []
            if len(fragment.get("bbox_px", []) or []) >= 4
        ]
        nodes.append(
            SemanticNodeV03(
                node_id=str(item.get("node_id", "") or ""),
                node_type=str(item.get("node_type", "") or ""),
                source=str(item.get("source", "") or "semantic_v03"),
                fragments=fragments,
                review_status=str(item.get("review_status", "") or "NEEDS_REVIEW"),
                text_stub=str(item.get("text_stub", "") or ""),
            )
        )
    return nodes


def _manifests_from_json(payload: dict[str, Any]) -> list[PageManifestV03]:
    pages = payload.get("pages", []) if isinstance(payload.get("pages"), list) else []
    return [PageManifestV03(**page) for page in pages]


def _blocks_from_json(payload: dict[str, Any]) -> list[BlockCandidateV03]:
    items = payload.get("blocks", payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and "reading_blocks" in payload:
        items = payload["reading_blocks"]
    return [BlockCandidateV03(**item) for item in items or []]


def _audit_reason_map(payload: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for record in payload.get("records", []) or []:
        node_id = str(record.get("node_id", "") or "")
        if node_id:
            result[node_id] = [str(r) for r in record.get("reasons", []) or []]
    return result


def _union_bbox(fragments: list[NodeFragmentV03], page: int) -> list[int] | None:
    boxes = [f.bbox_px for f in fragments if f.page == page and len(f.bbox_px) >= 4]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _select_target_fragment(node: SemanticNodeV03, reasons: list[str]) -> tuple[int, NodeFragmentV03] | None:
    if not node.fragments:
        return None
    # Most split failures are at the tail: page-bottom continuation, next section swallowed,
    # or a short question whose evidence should extend downward from the current tail.
    indexed = list(enumerate(node.fragments))
    indexed.sort(key=lambda item: (item[1].page, item[1].bbox_px[1], item[1].bbox_px[0]))
    return indexed[-1]


def _fragment_key(fragment: NodeFragmentV03) -> tuple[int, int, int, int, int]:
    box = [int(v) for v in fragment.bbox_px[:4]]
    return (int(fragment.page), box[0], box[1], box[2], box[3])


def _block_height(block: BlockCandidateV03) -> int:
    if len(block.bbox_px) < 4:
        return 0
    return max(0, int(block.bbox_px[3]) - int(block.bbox_px[1]))


def _block_to_fragment(block: BlockCandidateV03, role: str, extra_flags: list[str] | None = None) -> NodeFragmentV03:
    flags = set(block.candidate_flags)
    flags.update(extra_flags or [])
    return NodeFragmentV03(
        page=int(block.page),
        bbox_px=[int(v) for v in block.bbox_px[:4]],
        role=role,
        block_ids=[str(block.block_id)],
        flags=sorted(flags),
    )


def _role_for_continuation_block(block: BlockCandidateV03) -> str:
    flags = set(block.candidate_flags)
    if "answer_like" in flags:
        return "answer_block"
    if "analysis_like" in flags:
        return "analysis_block"
    if "translation_like" in flags:
        return "translation_block"
    return "body_continuation"


def _is_strong_continuation_candidate(block: BlockCandidateV03) -> bool:
    flags = set(block.candidate_flags)
    if "continues_previous_page" in flags or "page_top_continuation" in flags:
        return True
    if {"answer_like", "analysis_like", "translation_like"} & flags:
        return True
    features = block.visual_features or {}
    return bool(features.get("continues_previous_page", False))


def _is_new_boundary(block: BlockCandidateV03) -> bool:
    flags = set(block.candidate_flags)
    if "possible_section_heading" in flags or "knowledge_like" in flags:
        return True
    if "possible_question_start" in flags and not _is_strong_continuation_candidate(block):
        return True
    return False


def _used_block_ids(nodes: list[SemanticNodeV03]) -> set[str]:
    return {str(block_id) for node in nodes for fragment in node.fragments for block_id in fragment.block_ids}


def _block_owner_map(nodes: list[SemanticNodeV03]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for node in nodes:
        for fragment in node.fragments:
            for block_id in fragment.block_ids:
                owners[str(block_id)] = node.node_id
    return owners


def _detach_block_from_other_nodes(nodes: list[SemanticNodeV03], block_id: str, target_node_id: str) -> bool:
    detached = False
    for node in nodes:
        if node.node_id == target_node_id:
            continue
        before = len(node.fragments)
        node.fragments = [
            fragment
            for fragment in node.fragments
            if str(block_id) not in {str(item) for item in fragment.block_ids}
        ]
        if len(node.fragments) != before:
            detached = True
            node.text_stub = "\n".join(
                fragment.role for fragment in node.fragments
            ).strip() or node.text_stub
    return detached


def _append_unique_fragment(node: SemanticNodeV03, fragment: NodeFragmentV03) -> bool:
    existing = {_fragment_key(item) for item in node.fragments}
    if _fragment_key(fragment) in existing:
        return False
    node.fragments.append(fragment)
    node.fragments.sort(key=lambda f: (f.page, f.bbox_px[1], f.bbox_px[0]))
    node.text_stub = (node.text_stub + "\n" + "continuation_attached").strip()
    node.source = f"{node.source}+continuation_finder"
    return True


def _drop_empty_question_shells(nodes: list[SemanticNodeV03]) -> tuple[list[SemanticNodeV03], list[dict[str, Any]]]:
    kept: list[SemanticNodeV03] = []
    actions: list[dict[str, Any]] = []
    for node in nodes:
        if node.node_type == "question" and not node.fragments:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "dropped_empty_question_shell",
                    "reason": "all_fragments_moved_by_model_ownership_conflict_judge",
                }
            )
            continue
        kept.append(node)
    return kept, actions


def _find_same_page_continuation_candidates(
    *,
    blocks: list[BlockCandidateV03],
    node: SemanticNodeV03,
    last_fragment: NodeFragmentV03,
    manifest: PageManifestV03,
) -> tuple[list[BlockCandidateV03], str]:
    last_bottom = int(last_fragment.bbox_px[3])
    candidates = [
        block
        for block in blocks
        if block.page == last_fragment.page
        and int(block.bbox_px[1]) >= last_bottom - max(24, int(manifest.height_px * 0.008))
    ]
    candidates.sort(key=lambda b: (b.bbox_px[1], b.bbox_px[0]))
    selected: list[BlockCandidateV03] = []
    for block in candidates:
        if "page_number_noise" in set(block.candidate_flags):
            continue
        if _is_strong_continuation_candidate(block):
            selected.append(block)
            continue
        # A plain body continuation is allowed only when it visually follows
        # tightly after the target and is not tiny noise.
        gap = int(block.bbox_px[1]) - last_bottom
        if not selected and gap <= int(manifest.height_px * 0.035) and _block_height(block) >= 80:
            selected.append(block)
            continue
        if not selected:
            selected.append(block)
        break
    return selected, "same_page_candidates_found" if selected else "same_page_no_candidate"


def _find_next_page_continuation_candidates(
    *,
    blocks: list[BlockCandidateV03],
    last_fragment: NodeFragmentV03,
    manifest_by_page: dict[int, PageManifestV03],
) -> tuple[list[BlockCandidateV03], str]:
    next_page = int(last_fragment.page) + 1
    manifest = manifest_by_page.get(next_page)
    if manifest is None:
        return [], "missing_next_page_manifest"
    page_top_limit = int(manifest.height_px * 0.26)
    candidates = [
        block
        for block in blocks
        if block.page == next_page
        and int(block.bbox_px[1]) <= page_top_limit
    ]
    candidates.sort(key=lambda b: (b.bbox_px[1], b.bbox_px[0]))
    selected: list[BlockCandidateV03] = []
    for block in candidates:
        if "page_number_noise" in set(block.candidate_flags):
            continue
        if _is_strong_continuation_candidate(block):
            selected.append(block)
            continue
        if selected and int(block.bbox_px[1]) <= page_top_limit:
            selected.append(block)
            continue
        if not selected:
            selected.append(block)
        break
    return selected, "next_page_candidates_found" if selected else "next_page_no_candidate"


def _crop_block(manifest_by_page: dict[int, PageManifestV03], block: BlockCandidateV03, pad: int = 24) -> Image.Image | None:
    manifest = manifest_by_page.get(int(block.page))
    if manifest is None:
        return None
    path = Path(manifest.page_image_master)
    if not path.exists():
        return None
    with Image.open(path) as img:
        x0, y0, x1, y1 = [int(v) for v in block.bbox_px[:4]]
        box = (
            max(0, x0 - pad),
            max(0, y0 - pad),
            min(manifest.width_px, x1 + pad),
            min(manifest.height_px, y1 + pad),
        )
        return img.convert("RGB").crop(box)


def _make_judge_image(
    *,
    manifest_by_page: dict[int, PageManifestV03],
    current_block: BlockCandidateV03,
    candidate_block: BlockCandidateV03,
) -> Image.Image | None:
    current_img = _crop_block(manifest_by_page, current_block, pad=32)
    candidate_img = _crop_block(manifest_by_page, candidate_block, pad=32)
    if current_img is None or candidate_img is None:
        return None
    max_width = max(current_img.width, candidate_img.width, 720)
    label_h = 44
    gap = 16
    canvas = Image.new("RGB", (max_width, label_h * 2 + current_img.height + candidate_img.height + gap), "white")
    draw = ImageDraw.Draw(canvas)
    font = _load_font(24)
    draw.rectangle((0, 0, max_width, label_h), fill=(235, 243, 255))
    draw.text((12, 8), "A 当前题尾 / current question tail", fill=(30, 80, 150), font=font)
    canvas.paste(current_img, (0, label_h))
    y = label_h + current_img.height + gap
    draw.rectangle((0, y, max_width, y + label_h), fill=(255, 241, 230))
    draw.text((12, y + 8), "B 候选续片 / candidate continuation", fill=(170, 80, 20), font=font)
    canvas.paste(candidate_img, (0, y + label_h))
    return canvas


def _block_from_fragment(
    *,
    block_id: str,
    fragment: NodeFragmentV03,
    manifest: PageManifestV03,
    text_stub: str,
) -> BlockCandidateV03:
    return BlockCandidateV03(
        block_id=block_id,
        doc_key=manifest.doc_key,
        page=fragment.page,
        bbox_px=fragment.bbox_px,
        bbox_norm=[
            fragment.bbox_px[0] / max(manifest.width_px, 1),
            fragment.bbox_px[1] / max(manifest.height_px, 1),
            fragment.bbox_px[2] / max(manifest.width_px, 1),
            fragment.bbox_px[3] / max(manifest.height_px, 1),
        ],
        source="node_fragment",
        text_stub=text_stub,
        visual_features={},
        candidate_flags=fragment.flags,
    )


def _make_conflict_image(
    *,
    manifest_by_page: dict[int, PageManifestV03],
    claimant_block: BlockCandidateV03,
    candidate_block: BlockCandidateV03,
    owner_node: SemanticNodeV03,
) -> Image.Image | None:
    if not owner_node.fragments:
        return None
    owner_fragment = sorted(owner_node.fragments, key=lambda f: (f.page, f.bbox_px[1], f.bbox_px[0]))[0]
    owner_manifest = manifest_by_page.get(owner_fragment.page)
    if owner_manifest is None:
        return None
    owner_block = _block_from_fragment(
        block_id=f"{owner_node.node_id}_owner_fragment",
        fragment=owner_fragment,
        manifest=owner_manifest,
        text_stub=owner_node.text_stub,
    )
    parts = [
        ("A claimant tail", _crop_block(manifest_by_page, claimant_block)),
        ("B disputed candidate", _crop_block(manifest_by_page, candidate_block)),
        ("C current owner", _crop_block(manifest_by_page, owner_block)),
    ]
    if any(img is None for _, img in parts):
        return None
    images = [(label, img) for label, img in parts if img is not None]
    max_width = max(img.width for _, img in images)
    label_h = 44
    gap = 16
    total_h = sum(label_h + img.height for _, img in images) + gap * (len(images) - 1)
    canvas = Image.new("RGB", (max_width, total_h), "white")
    draw = ImageDraw.Draw(canvas)
    font = _load_font(24)
    y = 0
    fills = [(235, 243, 255), (255, 241, 230), (238, 255, 240)]
    colors = [(30, 80, 150), (170, 80, 20), (30, 120, 60)]
    for idx, (label, img) in enumerate(images):
        draw.rectangle((0, y, max_width, y + label_h), fill=fills[idx])
        draw.text((12, y + 8), label, fill=colors[idx], font=font)
        canvas.paste(img, (0, y + label_h))
        y += label_h + img.height + gap
    return canvas


def _call_continuation_judge(
    *,
    api_key: str,
    model: str,
    bundle: dict[str, str],
    judge_img: Image.Image,
    node: SemanticNodeV03,
    reasons: list[str],
    candidate: BlockCandidateV03,
) -> dict[str, Any]:
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "NODE_ID": node.node_id,
            "DOC_KEY": candidate.doc_key,
            "FAILURE_REASONS": ", ".join(reasons),
            "CANDIDATE_BLOCK_ID": candidate.block_id,
            "CANDIDATE_FLAGS": ", ".join(candidate.candidate_flags),
        },
    )
    return _call_model(api_key, model, judge_img, prompt, bundle["system_prompt"])


def _call_ownership_conflict_judge(
    *,
    api_key: str,
    model: str,
    bundle: dict[str, str],
    conflict_img: Image.Image,
    claimant_node: SemanticNodeV03,
    owner_node: SemanticNodeV03,
    reasons: list[str],
    candidate: BlockCandidateV03,
    continuation_payload: dict[str, Any],
) -> dict[str, Any]:
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "CLAIMANT_NODE_ID": claimant_node.node_id,
            "OWNER_NODE_ID": owner_node.node_id,
            "CANDIDATE_BLOCK_ID": candidate.block_id,
            "FAILURE_REASONS": ", ".join(reasons),
            "CONTINUATION_DECISION": str(continuation_payload.get("decision", "")),
            "CONTINUATION_REASON": str(continuation_payload.get("reason", "")),
        },
    )
    return _call_model(api_key, model, conflict_img, prompt, bundle["system_prompt"])


def attach_continuation_candidates(
    *,
    nodes: list[SemanticNodeV03],
    reading_blocks: list[BlockCandidateV03],
    reasons_by_node: dict[str, list[str]],
    manifest_by_page: dict[int, PageManifestV03],
    api_key: str,
    model: str,
    prompt_bundle: dict[str, str],
    conflict_prompt_bundle: dict[str, str],
    out_dir: Path,
    max_calls: int,
) -> tuple[list[dict[str, Any]], int, int]:
    actions: list[dict[str, Any]] = []
    calls = 0
    conflict_calls = 0
    blocks = sorted(reading_blocks, key=lambda b: (b.page, b.bbox_px[1], b.bbox_px[0]))
    block_by_id = {block.block_id: block for block in blocks}
    node_by_id = {node.node_id: node for node in nodes}
    for node in nodes:
        if node.node_type != "question":
            continue
        reasons = reasons_by_node.get(node.node_id, [])
        if not JUDGE_REASONS.intersection(reasons):
            continue
        if calls >= max_calls:
            actions.append({"node_id": node.node_id, "action": "continuation_judge_skipped_max_calls", "reasons": reasons})
            continue
        target = _select_target_fragment(node, reasons)
        if target is None:
            actions.append({"node_id": node.node_id, "action": "continuation_missing_fragment", "reasons": reasons})
            continue
        _, last_fragment = target
        manifest = manifest_by_page.get(last_fragment.page)
        if manifest is None:
            actions.append({"node_id": node.node_id, "action": "continuation_missing_manifest", "reasons": reasons})
            continue
        owner_by_block = _block_owner_map(nodes)
        current_block = None
        if last_fragment.block_ids:
            current_block = block_by_id.get(str(last_fragment.block_ids[0]))
        if current_block is None:
            current_block = BlockCandidateV03(
                block_id=f"{node.node_id}_current_fragment",
                doc_key=manifest.doc_key,
                page=last_fragment.page,
                bbox_px=last_fragment.bbox_px,
                bbox_norm=[
                    last_fragment.bbox_px[0] / max(manifest.width_px, 1),
                    last_fragment.bbox_px[1] / max(manifest.height_px, 1),
                    last_fragment.bbox_px[2] / max(manifest.width_px, 1),
                    last_fragment.bbox_px[3] / max(manifest.height_px, 1),
                ],
                source="node_fragment",
                text_stub=node.text_stub,
                visual_features={},
                candidate_flags=last_fragment.flags,
            )
        same_page, same_reason = _find_same_page_continuation_candidates(
            blocks=blocks,
            node=node,
            last_fragment=last_fragment,
            manifest=manifest,
        )
        selected = same_page
        search_reason = same_reason
        if not selected:
            next_page, next_reason = _find_next_page_continuation_candidates(
                blocks=blocks,
                last_fragment=last_fragment,
                manifest_by_page=manifest_by_page,
            )
            selected = next_page
            search_reason = next_reason
        attached: list[str] = []
        judge_payloads: list[dict[str, Any]] = []
        for block in selected[:2]:
            judge_img = _make_judge_image(manifest_by_page=manifest_by_page, current_block=current_block, candidate_block=block)
            if judge_img is None:
                judge_payloads.append({"candidate_block_id": block.block_id, "error": "judge_image_unavailable"})
                continue
            debug_dir = out_dir / "debug_continuation_judge" / node.node_id
            debug_dir.mkdir(parents=True, exist_ok=True)
            judge_path = debug_dir / f"{node.node_id}_{block.block_id}.png"
            judge_img.save(judge_path)
            try:
                payload = _call_continuation_judge(
                    api_key=api_key,
                    model=model,
                    bundle=prompt_bundle,
                    judge_img=judge_img,
                    node=node,
                    reasons=reasons,
                    candidate=block,
                )
                calls += 1
            except Exception as exc:
                payload = {"decision": "manual_review", "error": str(exc)[:240], "review_flags": ["judge_failed"]}
            payload["candidate_block_id"] = block.block_id
            payload["judge_image"] = _portable(judge_path, out_dir)
            judge_payloads.append(payload)
            decision = str(payload.get("decision", "")).strip().lower()
            if decision != "attach":
                continue
            role = str(payload.get("role") or _role_for_continuation_block(block))
            if role not in {"body_continuation", "answer_block", "analysis_block", "translation_block"}:
                role = _role_for_continuation_block(block)
            fragment = _block_to_fragment(block, role, ["continues_previous_page", "continuation_finder_attached", "continuation_judge_attached"])
            original_owner = owner_by_block.get(block.block_id, "")
            if original_owner and original_owner != node.node_id and "_q_" in original_owner:
                payload["original_owner_node_id"] = original_owner
                owner_node = node_by_id.get(original_owner)
                conflict_payload: dict[str, Any] = {
                    "decision": "manual_review",
                    "review_flags": ["owner_node_missing"],
                }
                if owner_node is not None:
                    conflict_img = _make_conflict_image(
                        manifest_by_page=manifest_by_page,
                        claimant_block=current_block,
                        candidate_block=block,
                        owner_node=owner_node,
                    )
                    if conflict_img is not None and (calls + conflict_calls) < max_calls:
                        conflict_dir = out_dir / "debug_ownership_conflict_judge" / node.node_id
                        conflict_dir.mkdir(parents=True, exist_ok=True)
                        conflict_path = conflict_dir / f"{node.node_id}_{block.block_id}_vs_{original_owner}.png"
                        conflict_img.save(conflict_path)
                        try:
                            conflict_payload = _call_ownership_conflict_judge(
                                api_key=api_key,
                                model=model,
                                bundle=conflict_prompt_bundle,
                                conflict_img=conflict_img,
                                claimant_node=node,
                                owner_node=owner_node,
                                reasons=reasons,
                                candidate=block,
                                continuation_payload=payload,
                            )
                            conflict_calls += 1
                        except Exception as exc:
                            conflict_payload = {
                                "decision": "manual_review",
                                "error": str(exc)[:240],
                                "review_flags": ["ownership_conflict_judge_failed"],
                            }
                        conflict_payload["judge_image"] = _portable(conflict_path, out_dir)
                    else:
                        conflict_payload["review_flags"] = [*conflict_payload.get("review_flags", []), "conflict_image_unavailable_or_call_limit"]
                payload["ownership_conflict_payload"] = conflict_payload
                conflict_decision = str(conflict_payload.get("decision", "")).strip().lower()
                if conflict_decision != "move_to_claimant":
                    payload["review_flags"] = [*payload.get("review_flags", []), "candidate_owned_by_question"]
                    payload["auto_attach_blocked"] = True
                    continue
                payload["review_flags"] = [*payload.get("review_flags", []), "candidate_owner_moved_by_model"]
            detached = False
            if original_owner and original_owner != node.node_id:
                detached = _detach_block_from_other_nodes(nodes, block.block_id, node.node_id)
            if _append_unique_fragment(node, fragment):
                attached.append(block.block_id)
                payload["original_owner_node_id"] = original_owner
                payload["detached_from_original_owner"] = detached
                break
            if calls >= max_calls:
                break
        if attached:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "continuation_judge_attached",
                    "reasons": reasons,
                    "attached_block_ids": attached,
                    "search_reason": search_reason,
                    "judge_payloads": judge_payloads,
                }
            )
        else:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "continuation_judge_not_attached",
                    "reasons": reasons,
                    "search_reason": search_reason,
                    "judge_payloads": judge_payloads,
                    "last_page": last_fragment.page,
                    "last_bbox": last_fragment.bbox_px,
                }
            )
        if calls >= max_calls:
            continue
    return actions, calls, conflict_calls


def _band_for_fragment(fragment: NodeFragmentV03, manifest: PageManifestV03, reasons: list[str]) -> tuple[list[int], list[int]]:
    box = [int(v) for v in fragment.bbox_px[:4]]
    if len(box) < 4:
        return [0, 0, manifest.width_px, manifest.height_px], [0, 0, manifest.width_px, manifest.height_px]
    x0, y0, x1, y1 = box
    pad_x = int(manifest.width_px * 0.06)
    top_pad = int(manifest.height_px * 0.035)
    bottom_ratio = 0.10
    if "page_bottom_may_continue" in reasons:
        bottom_ratio = 0.18
    if "short_question_without_solution_evidence" in reasons:
        bottom_ratio = 0.24
    if "swallows_next_section" in reasons:
        bottom_ratio = max(bottom_ratio, 0.12)
    bottom_pad = int(manifest.height_px * bottom_ratio)
    band = [
        max(0, x0 - pad_x),
        max(0, y0 - top_pad),
        min(manifest.width_px, x1 + pad_x),
        min(manifest.height_px, y1 + bottom_pad),
    ]
    # Keep enough right/left margin for English answer/analysis labels and math diagrams.
    if band[2] - band[0] < manifest.width_px * 0.55:
        center = (band[0] + band[2]) // 2
        half = int(manifest.width_px * 0.32)
        band[0] = max(0, center - half)
        band[2] = min(manifest.width_px, center + half)
    return box, band


def _norm_bbox_in_band(box: list[int], band: list[int]) -> dict[str, int]:
    bw = max(1, band[2] - band[0])
    bh = max(1, band[3] - band[1])
    return {
        "x": int(round((box[0] - band[0]) * 1000 / bw)),
        "y": int(round((box[1] - band[1]) * 1000 / bh)),
        "w": int(round((box[2] - box[0]) * 1000 / bw)),
        "h": int(round((box[3] - box[1]) * 1000 / bh)),
    }


def _denorm_bbox_from_band(raw: dict[str, Any], band: list[int]) -> list[int] | None:
    try:
        x = float(raw.get("x", 0) or 0)
        y = float(raw.get("y", 0) or 0)
        w = float(raw.get("w", 0) or 0)
        h = float(raw.get("h", 0) or 0)
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    bw = max(1, band[2] - band[0])
    bh = max(1, band[3] - band[1])
    x0 = int(round(band[0] + x * bw / 1000))
    y0 = int(round(band[1] + y * bh / 1000))
    x1 = int(round(x0 + w * bw / 1000))
    y1 = int(round(y0 + h * bh / 1000))
    return [max(band[0], x0), max(band[1], y0), min(band[2], x1), min(band[3], y1)]


def _replace_fragment(
    node: SemanticNodeV03,
    fragment_index: int,
    bbox: list[int],
    manifest: PageManifestV03,
    extra_flags: list[str] | None = None,
) -> None:
    if fragment_index < 0 or fragment_index >= len(node.fragments):
        return
    old = node.fragments[fragment_index]
    flags = set([*old.flags, "split_node_refined_by_model", *(extra_flags or [])])
    # The original near-bottom flag is a candidate feature, not a permanent
    # truth. Once the model trims the fragment away from page bottom, clear it
    # so the auditor does not keep failing a repaired bbox on stale metadata.
    if len(bbox) >= 4 and int(bbox[3]) < int(manifest.height_px * 0.93):
        flags.discard("near_page_bottom")
    node.fragments[fragment_index] = NodeFragmentV03(
        page=old.page,
        bbox_px=bbox,
        role=old.role or "question_body",
        block_ids=old.block_ids,
        flags=sorted(flags),
    )
    node.fragments.sort(key=lambda f: (f.page, f.bbox_px[1], f.bbox_px[0]))
    node.source = f"{node.source}+split_node_refine"


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def refine_nodes(
    *,
    doc_dir: Path,
    semantic_nodes_path: Path,
    audit_path: Path,
    out_dir: Path,
    api_key: str,
    model: str,
    max_nodes: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = _nodes_from_json(read_json(semantic_nodes_path))
    manifests = _manifests_from_json(read_json(doc_dir / "page_manifests.json"))
    manifest_by_page = {m.page: m for m in manifests}
    reasons_by_node = _audit_reason_map(read_json(audit_path))
    reading_blocks_path = doc_dir / "reading_blocks.json"
    reading_blocks = _blocks_from_json(read_json(reading_blocks_path)) if reading_blocks_path.exists() else []
    bundle = vision_prompt_store.get_split_node_refine_prompt_bundle()
    continuation_bundle = vision_prompt_store.get_continuation_judge_prompt_bundle()
    conflict_bundle = vision_prompt_store.get_ownership_conflict_judge_prompt_bundle()

    actions: list[dict[str, Any]] = []
    continuation_actions, continuation_calls, ownership_conflict_calls = attach_continuation_candidates(
        nodes=nodes,
        reading_blocks=reading_blocks,
        reasons_by_node=reasons_by_node,
        manifest_by_page=manifest_by_page,
        api_key=api_key,
        model=model,
        prompt_bundle=continuation_bundle,
        conflict_prompt_bundle=conflict_bundle,
        out_dir=out_dir,
        max_calls=max_nodes,
    )
    actions.extend(continuation_actions)
    if continuation_actions:
        nodes, drop_actions = _drop_empty_question_shells(nodes)
        actions.extend(drop_actions)
        refreshed_audit = audit_nodes_v03(nodes)
        reasons_by_node = {record.node_id: list(record.reasons) for record in refreshed_audit}
    refine_calls = 0
    for node in nodes:
        if node.node_type != "question":
            continue
        reasons = reasons_by_node.get(node.node_id, [])
        if not TARGET_REASONS.intersection(reasons):
            continue
        if refine_calls >= max_nodes:
            actions.append({"node_id": node.node_id, "action": "skipped_max_nodes", "reasons": reasons})
            continue
        target = _select_target_fragment(node, reasons)
        if target is None:
            actions.append({"node_id": node.node_id, "action": "missing_fragment", "reasons": reasons})
            continue
        fragment_index, target_fragment = target
        page = target_fragment.page
        manifest = manifest_by_page.get(page)
        if manifest is None:
            actions.append({"node_id": node.node_id, "action": "missing_manifest", "reasons": reasons})
            continue
        candidate_box, band = _band_for_fragment(target_fragment, manifest, reasons)
        with Image.open(manifest.page_image_master) as img:
            band_img = img.convert("RGB").crop(tuple(band))
        candidate_norm = _norm_bbox_in_band(candidate_box, band)
        prompt = vision_prompt_store.render_template(
            bundle["user_template"],
            {
                "NODE_ID": node.node_id,
                "DOC_KEY": manifest.doc_key,
                "PAGE": str(page),
                "FAILURE_REASONS": ", ".join(reasons),
                "CANDIDATE_BBOX_NORM": json.dumps(candidate_norm, ensure_ascii=False),
            },
        )
        debug_dir = out_dir / "debug_refine_inputs" / node.node_id
        debug_dir.mkdir(parents=True, exist_ok=True)
        input_path = debug_dir / f"{node.node_id}_f{fragment_index + 1:02d}_p{page:03d}_band.png"
        band_img.save(input_path)
        try:
            payload = _call_model(api_key, model, band_img, prompt, bundle["system_prompt"])
            refine_calls += 1
        except Exception as exc:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "model_failed",
                    "reasons": reasons,
                    "error": str(exc)[:240],
                    "input_image": _portable(input_path, out_dir),
                }
            )
            continue
        refined = _denorm_bbox_from_band(payload.get("bbox", {}) if isinstance(payload.get("bbox"), dict) else {}, band)
        if not bool(payload.get("is_repaired", False)) or refined is None:
            actions.append(
                {
                    "node_id": node.node_id,
                    "action": "needs_manual_review",
                    "reasons": reasons,
                    "model_payload": payload,
                    "input_image": _portable(input_path, out_dir),
                }
            )
            continue
        extra_flags = []
        if "page_bottom_may_continue" in reasons and not payload.get("review_flags"):
            extra_flags.append("cross_page_checked_no_continuation")
        _replace_fragment(node, fragment_index, refined, manifest, extra_flags)
        actions.append(
            {
                "node_id": node.node_id,
                "action": "refined_node_bbox",
                "reasons": reasons,
                "target_fragment_index": fragment_index,
                "target_fragment_role": target_fragment.role,
                "page": page,
                "old_bbox": candidate_box,
                "new_bbox": refined,
                "band_bbox": band,
                "model_payload": payload,
                "input_image": _portable(input_path, out_dir),
            }
        )

    crop_records = execute_crops_v03(nodes, manifests, out_dir / "docs" / "refined")
    audit_records = audit_nodes_v03(nodes)
    bridge = build_legacy_bridge([asdict(node) for node in nodes], crop_records)
    repair_pool = build_review_repair_pool([asdict(node) for node in nodes], crop_records, [asdict(record) for record in audit_records])
    write_nodes(out_dir / "semantic_nodes_refined.json", nodes)
    write_audit_report(out_dir / "audit_report_refined.json", audit_records)
    write_json(out_dir / "legacy_bridge_questions_refined.json", bridge)
    write_json(out_dir / "review_repair_pool_refined.json", repair_pool)
    write_json(out_dir / "split_node_refine_actions.json", actions)
    report = {
        "schema": "split_node_refine_report_v0.1",
        "doc_dir": str(doc_dir),
        "semantic_nodes_input": str(semantic_nodes_path),
        "audit_input": str(audit_path),
        "model": model,
        "actual_vlm_calls": continuation_calls + ownership_conflict_calls + refine_calls,
        "vlm_calls_by_stage": {
            "continuation_judge": continuation_calls,
            "ownership_conflict_judge": ownership_conflict_calls,
            "split_node_refine": refine_calls,
        },
        "node_stage_contract": {
            "continuation_judge": "VLM only decides whether one candidate block continues one current question tail; it must not crop or rewrite content.",
            "ownership_conflict_judge": "VLM only resolves disputed ownership when a continuation candidate is already owned by another question; it must not crop or rewrite content.",
            "split_node_refine": "VLM only tightens one failed fragment bbox inside a local band; it must not attach cross-page blocks.",
        },
        "action_counts": {action: sum(1 for item in actions if item.get("action") == action) for action in sorted({str(item.get("action")) for item in actions})},
        "ready_count": len(bridge["questions"]),
        "review_repair_pool_count": len(repair_pool["items"]),
        "artifacts": [
            str(out_dir / "semantic_nodes_refined.json"),
            str(out_dir / "audit_report_refined.json"),
            str(out_dir / "legacy_bridge_questions_refined.json"),
            str(out_dir / "review_repair_pool_refined.json"),
            str(out_dir / "split_node_refine_actions.json"),
            str(out_dir / "docs" / "refined" / "crop_manifest.json"),
        ],
    }
    write_json(out_dir / "split_node_refine_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Refine failed split_v03 semantic question nodes one candidate at a time.")
    parser.add_argument("--doc-dir", required=True)
    parser.add_argument("--semantic-nodes", required=True)
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--max-nodes", type=int, default=12)
    args = parser.parse_args()
    if not str(args.api_key or "").strip():
        raise SystemExit("missing_api_key")
    report = refine_nodes(
        doc_dir=Path(args.doc_dir).resolve(),
        semantic_nodes_path=Path(args.semantic_nodes).resolve(),
        audit_path=Path(args.audit_report).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        api_key=str(args.api_key or ""),
        model=str(args.model or ""),
        max_nodes=args.max_nodes,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
