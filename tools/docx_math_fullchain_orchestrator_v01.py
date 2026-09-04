from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT_ROOT = Path("outputs/docx_math_fullchain_orchestrator_v0_1")
QUESTION_REFINER_OUT_ROOT = Path("outputs/docx_math_question_refiner_v0_1")
LONG_COMPOSITE_OUT_ROOT = Path("outputs/docx_math_long_composite_refiner_v0_1")
REFINE_GATE_REPAIR_OUT_ROOT = Path("outputs/docx_math_refine_gate_repair_orchestrator_v0_1")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_draft_payload(input_draft_root: Path, doc_id_contains: str) -> dict[str, Any]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in input_draft_root.rglob("docx_math_source_backed_draft_items.json"):
        payload = read_json(path)
        doc_id = str(payload.get("doc_id") or "")
        if not doc_id_contains or doc_id_contains in doc_id:
            candidates.append((path, payload))
    if not candidates:
        raise FileNotFoundError(f"no draft payload matched doc_id_contains={doc_id_contains!r} under {input_draft_root}")
    if len(candidates) > 1:
        matches = "\n".join(str(path) for path, _ in candidates)
        raise RuntimeError(f"doc_id_contains matched multiple draft payloads; narrow it first:\n{matches}")
    path, payload = candidates[0]
    payload["_draft_payload_path"] = str(path)
    return payload


def load_draft_payload(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    payload["_draft_payload_path"] = str(path)
    return payload


def group_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in payload.get("draft_items") or []:
        gid = item.get("source_group_id")
        if gid:
            ids.append(str(gid))
    return ids


def field_markdown_len(draft: dict[str, Any], field_name: str) -> int:
    return len(str(((draft.get("fields") or {}).get(field_name) or {}).get("markdown") or "").strip())


def field_block_count(draft: dict[str, Any], field_name: str) -> int:
    return len(((draft.get("fields") or {}).get(field_name) or {}).get("block_ids") or [])


def is_auto_long_composite_candidate(
    draft: dict[str, Any],
    *,
    min_chars: int,
    min_blocks: int,
    min_explanation_chars: int,
) -> bool:
    fields = draft.get("fields") or {}
    record_kind = str(draft.get("record_kind") or "")
    has_subquestions = bool(str((fields.get("subquestions") or {}).get("markdown") or "").strip())
    is_composite_kind = record_kind in {
        "math_composite_question",
        "math_composite_question_with_solution",
    }
    if not (has_subquestions or is_composite_kind):
        return False
    content_chars = sum(
        field_markdown_len(draft, field)
        for field in ["stem", "subquestions", "answer", "explanation", "teaching_note"]
    )
    source_blocks = sum(
        field_block_count(draft, field)
        for field in ["stem", "subquestions", "answer", "explanation", "teaching_note"]
    )
    explanation_chars = field_markdown_len(draft, "explanation")
    return (
        content_chars >= min_chars
        or source_blocks >= min_blocks
        or explanation_chars >= min_explanation_chars
    )


def auto_long_composite_group_ids(
    payload: dict[str, Any],
    selected_group_ids: list[str],
    *,
    enabled: bool,
    min_chars: int,
    min_blocks: int,
    min_explanation_chars: int,
) -> set[str]:
    if not enabled:
        return set()
    selected = set(selected_group_ids)
    out: set[str] = set()
    for draft in payload.get("draft_items") or []:
        group_id = str(draft.get("source_group_id") or "")
        if not group_id or group_id not in selected:
            continue
        if is_auto_long_composite_candidate(
            draft,
            min_chars=min_chars,
            min_blocks=min_blocks,
            min_explanation_chars=min_explanation_chars,
        ):
            out.add(group_id)
    return out


def run_child(cmd: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> dict[str, Any]:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, encoding="utf-8", capture_output=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(
            {
                "cmd": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"child command failed: {' '.join(cmd)}; see {log_path}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw_stdout": result.stdout}


def run_question_refiner(
    *,
    repo_root: Path,
    env: dict[str, str],
    input_draft_root: Path,
    run_id: str,
    doc_id_contains: str,
    group_ids: list[str],
    max_workers: int,
    log_path: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "tools/docx_math_question_refiner_v01.py",
        "--input-draft-root",
        str(input_draft_root),
        "--run-id",
        run_id,
        "--doc-id-contains",
        doc_id_contains,
        "--max-workers",
        str(max_workers),
    ]
    if group_ids:
        cmd.append("--group-ids")
        cmd.extend(group_ids)
    return run_child(cmd, repo_root, env, log_path)


def run_long_composite_refiner(
    *,
    repo_root: Path,
    env: dict[str, str],
    input_draft_root: Path,
    run_id: str,
    doc_id_contains: str,
    group_id: str,
    max_workers: int,
    log_path: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "tools/docx_math_long_composite_refiner_v01.py",
        "--input-draft-root",
        str(input_draft_root),
        "--run-id",
        run_id,
        "--doc-id-contains",
        doc_id_contains,
        "--group-ids",
        group_id,
        "--max-workers",
        str(max_workers),
    ]
    return run_child(cmd, repo_root, env, log_path)


def run_refine_gate_repair(
    *,
    repo_root: Path,
    env: dict[str, str],
    input_draft_root: Path,
    run_id: str,
    doc_id_contains: str,
    refiner_run_id: str,
    group_ids: list[str],
    max_workers: int,
    log_path: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "tools/docx_math_refine_gate_repair_orchestrator_v01.py",
        "--input-draft-root",
        str(input_draft_root),
        "--run-id",
        run_id,
        "--doc-id-contains",
        doc_id_contains,
        "--refiner-run-id",
        refiner_run_id,
        "--skip-refiner",
        "--max-workers",
        str(max_workers),
    ]
    if group_ids:
        cmd.append("--group-ids")
        cmd.extend(group_ids)
    return run_child(cmd, repo_root, env, log_path)


def failed_groups(refiner_summary: dict[str, Any]) -> list[str]:
    groups: list[str] = []
    for record in refiner_summary.get("records") or []:
        if record.get("refine_status") != "REFINED_READY":
            gid = record.get("source_group_id")
            if gid:
                groups.append(str(gid))
    return groups


def load_refined_packets(refiner_run_id: str) -> dict[str, dict[str, Any]]:
    path = QUESTION_REFINER_OUT_ROOT / refiner_run_id / "refined_question_packets.json"
    payload = read_json(path)
    return {str(packet.get("source_group_id")): packet for packet in payload.get("refined_packets") or []}


def load_gate_repair_packets(gate_repair_run_id: str) -> dict[str, dict[str, Any]]:
    path = REFINE_GATE_REPAIR_OUT_ROOT / gate_repair_run_id / "refined_question_packets.json"
    payload = read_json(path)
    return {str(packet.get("source_group_id")): packet for packet in payload.get("packets") or []}


def collect_packets_by_group(
    *,
    normal_run_id: str | None,
    retry_run_ids: list[str],
    retry_groups_by_run: dict[str, list[str]],
    long_run_ids: dict[str, str],
) -> dict[str, dict[str, Any]]:
    packets_by_group = load_refined_packets(normal_run_id) if normal_run_id else {}
    for retry_run_id in retry_run_ids:
        retry_packets = load_refined_packets(retry_run_id)
        for group_id in retry_groups_by_run.get(retry_run_id, []):
            if group_id in retry_packets:
                packets_by_group[group_id] = retry_packets[group_id]
    for group_id, long_run_id in long_run_ids.items():
        packets_by_group[group_id] = load_long_packet(long_run_id)
    return packets_by_group


def write_refiner_snapshot(
    *,
    run_id: str,
    payload: dict[str, Any],
    ordered_group_ids: list[str],
    packets_by_group: dict[str, dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    snapshot_dir = QUESTION_REFINER_OUT_ROOT / run_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    packets = [packets_by_group[group_id] for group_id in ordered_group_ids if group_id in packets_by_group]
    records = [
        {
            "draft_id": packet.get("source_draft_id"),
            "source_group_id": packet.get("source_group_id"),
            "refine_status": packet.get("refine_status"),
            "artifact_path": "",
        }
        for packet in packets
    ]
    summary = {
        "schema": "docx_math_question_refiner.snapshot_summary",
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": payload.get("doc_id"),
        "source": "docx_math_fullchain_orchestrator.pre_gate_repair_snapshot",
        "packet_count": len(packets),
        "records": records,
        "total_tokens": 0,
    }
    write_json(snapshot_dir / "run_summary.json", summary)
    write_json(
        snapshot_dir / "refined_question_packets.json",
        {
            "schema": "docx_math_question_refiner.snapshot_packets_v0.1",
            "refined_packets": packets,
            "summary": summary,
        },
    )
    write_json(out_dir / "pre_gate_repair_refiner_snapshot.json", summary)
    return summary


def adapt_long_packet(packet: dict[str, Any]) -> dict[str, Any]:
    standard_question = packet.get("standard_question") or {}
    normalized_question = dict(standard_question)
    nested_subquestions = normalized_question.get("nested_subquestions")
    if not isinstance(normalized_question.get("subquestions"), list):
        normalized_question["subquestions"] = nested_subquestions if isinstance(nested_subquestions, list) else []
    for item in normalized_question.get("subquestions") or []:
        if isinstance(item, dict) and "markdown" not in item and item.get("prompt_md"):
            item["markdown"] = item.get("prompt_md")
    normalized_question.pop("nested_subquestions", None)
    normalized_question.setdefault("title", "")
    normalized_question.setdefault("stem_md", "")
    normalized_question.setdefault("options", [])
    normalized_question.setdefault("answer_md", "")
    normalized_question.setdefault("explanation_md", "")
    normalized_question.setdefault("teaching_note_md", "")
    normalized_question.setdefault("context_md", "")
    normalized_question.setdefault("render_markdown", "")
    return {
        "schema": "docx_math_refined_question_packet_v0.1",
        "doc_id": packet.get("doc_id"),
        "source_draft_id": packet.get("source_draft_id"),
        "source_group_id": packet.get("source_group_id"),
        "prompt_version": f"{packet.get('planner_prompt_version')} + {packet.get('segment_prompt_version')}",
        "refine_status": "REFINED_READY" if packet.get("status") == "READY" else "REFINE_FAILED",
        "question_type": standard_question.get("question_type", "composite"),
        "solution_policy": "required",
        "standard_question": normalized_question,
        "condition_groups": [],
        "source_refs": {},
        "asset_refs": packet.get("asset_refs") or {},
        "missing_fields": [],
        "warnings": [],
        "normalization_actions": [
            {
                "action": "long_composite_two_stage_refine",
                "segment_ids": packet.get("segment_ids") or [],
            }
        ]
        + list(packet.get("normalization_actions") or []),
        "status_breakdown": {
            "content_status": "CLEAN" if packet.get("status") == "READY" else "BROKEN",
            "source_status": "CLEAN" if packet.get("status") == "READY" else "MODEL_FAILED",
            "projection_status": "READY" if packet.get("status") == "READY" else "BLOCKED",
            "risk_codes": [],
        },
        "long_composite_plan": packet.get("plan"),
    }


def load_long_packet(long_run_id: str) -> dict[str, Any]:
    path = LONG_COMPOSITE_OUT_ROOT / long_run_id / "long_composite_refined_packet.json"
    return adapt_long_packet(read_json(path))


def subquestion_markdown(item: Any, *, include_solution: bool = True) -> str:
    if not isinstance(item, dict):
        return str(item or "").strip()
    parts: list[str] = []
    label = str(item.get("label") or "").strip()
    markdown = str(item.get("markdown") or item.get("prompt_md") or "").strip()
    if label and markdown and not markdown.startswith(label):
        parts.append(f"{label} {markdown}")
    elif markdown:
        parts.append(markdown)
    options = item.get("options") if isinstance(item.get("options"), list) else []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_label = str(option.get("label") or "").strip()
        option_markdown = str(option.get("markdown") or "").strip()
        if option_label or option_markdown:
            parts.append(f"{option_label}. {option_markdown}".strip())
    if include_solution:
        answer = str(item.get("answer_md") or "").strip()
        if answer:
            parts.append(f"【答案】{answer}")
        explanation = str(item.get("explanation_md") or "").strip()
        if explanation:
            parts.append(f"【解析】{explanation}")
    children = item.get("children") if isinstance(item.get("children"), list) else []
    nested = item.get("nested_subquestions") if isinstance(item.get("nested_subquestions"), list) else []
    for child in children + nested:
        value = subquestion_markdown(child, include_solution=include_solution)
        if value:
            parts.append(value)
    return "\n\n".join(part for part in parts if part)


def synthesize_render_markdown(packet: dict[str, Any]) -> str:
    q = packet.get("standard_question") or {}
    parts: list[str] = []
    title = str(q.get("title") or "").strip()
    if title:
        parts.append(title)
    stem = str(q.get("stem_md") or "").strip()
    if stem:
        parts.append(stem)
    subquestions = q.get("subquestions") if isinstance(q.get("subquestions"), list) else []
    nested_subquestions = q.get("nested_subquestions") if isinstance(q.get("nested_subquestions"), list) else []
    question_type = str(packet.get("question_type") or q.get("question_type") or "")
    inline_subquestion_solutions = question_type != "composite"
    for item in subquestions + nested_subquestions:
        value = subquestion_markdown(item, include_solution=inline_subquestion_solutions)
        if value:
            parts.append(value)
    options = q.get("options") if isinstance(q.get("options"), list) else []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        markdown = str(option.get("markdown") or "").strip()
        if label or markdown:
            parts.append(f"{label}. {markdown}".strip())
    options_md = str(q.get("options_md") or "").strip()
    if options_md:
        parts.append(options_md)
    asset_fallback_md = str(q.get("asset_fallback_md") or "").strip()
    if asset_fallback_md:
        parts.append(asset_fallback_md)
    answer = str(q.get("answer_md") or "").strip()
    if answer:
        parts.append(f"【答案】{answer}")
    explanation = str(q.get("explanation_md") or "").strip()
    if explanation:
        parts.append(f"【解析】{explanation}")
    teaching_note = str(q.get("teaching_note_md") or "").strip()
    if teaching_note:
        parts.append(f"【点睛】{teaching_note}")
    return "\n\n".join(part for part in parts if part)


def ensure_render_markdown(packet: dict[str, Any]) -> None:
    q = packet.get("standard_question")
    if not isinstance(q, dict):
        return
    previous = str(q.get("render_markdown") or "").strip()
    rendered = synthesize_render_markdown(packet)
    if not rendered:
        return
    q["render_markdown"] = rendered
    action = "overwrite_render_markdown_from_structured_fields" if previous and previous != rendered else "synthesize_render_markdown_from_structured_fields"
    packet.setdefault("normalization_actions", []).append(
        {
            "action": action,
            "scope": "fullchain_orchestrator_merge",
        }
    )


def packet_markdown(packet: dict[str, Any]) -> str:
    return synthesize_render_markdown(packet)


def option_markdown_text(options: Any) -> str:
    if not isinstance(options, list):
        return ""
    return "\n".join(
        str(item.get("markdown") or item.get("md") or "")
        for item in options
        if isinstance(item, dict)
    )


def subquestion_markdown_text(subquestions: Any) -> str:
    if not isinstance(subquestions, list):
        return ""
    chunks: list[str] = []
    for item in subquestions:
        if not isinstance(item, dict):
            continue
        chunks.append(subquestion_markdown(item))
    return "\n".join(chunk for chunk in chunks if chunk)


def packet_output_field_text(packet: dict[str, Any], output_key: str) -> str:
    q = packet.get("standard_question") or {}
    if output_key == "subquestions":
        return "\n".join(
            part
            for part in [
                subquestion_markdown_text(q.get("subquestions")),
                subquestion_markdown_text(q.get("nested_subquestions")),
            ]
            if part.strip()
        )
    if output_key == "options":
        return "\n".join(
            part
            for part in [
                option_markdown_text(q.get("options")),
                str(q.get("options_md") or ""),
            ]
            if part.strip()
        )
    return str(q.get(output_key) or "")


def packet_text_chunks(packet: dict[str, Any]) -> list[str]:
    q = packet.get("standard_question") or {}
    chunks = [
        str(q.get("title") or ""),
        str(q.get("stem_md") or ""),
        str(q.get("answer_md") or ""),
        str(q.get("explanation_md") or ""),
        str(q.get("teaching_note_md") or ""),
        str(q.get("context_md") or ""),
        str(q.get("render_markdown") or ""),
        str(q.get("options_md") or ""),
        str(q.get("asset_fallback_md") or ""),
    ]
    chunks.extend(subquestion_markdown_text(q.get("subquestions")).splitlines())
    chunks.extend(subquestion_markdown_text(q.get("nested_subquestions")).splitlines())
    chunks.extend(option_markdown_text(q.get("options")).splitlines())
    return chunks


def asset_tokens(text: str) -> set[str]:
    return set(re.findall(r"asset://([A-Za-z0-9_\\-]+)", str(text or "")))


def draft_required_asset_ids(draft: dict[str, Any]) -> set[str]:
    fields = draft.get("fields") or {}
    assets: set[str] = set()
    for field in fields.values():
        if isinstance(field, dict):
            assets.update(str(item) for item in field.get("asset_ids") or [] if item)
    for asset in draft.get("asset_refs") or []:
        if isinstance(asset, dict) and asset.get("asset_id"):
            assets.add(str(asset["asset_id"]))
    return assets


def source_field_coverage(packet: dict[str, Any], draft: dict[str, Any] | None) -> dict[str, Any]:
    if not draft:
        return {"status": "unknown", "issues": [{"code": "missing_source_draft", "field": ""}]}
    fields = draft.get("fields") or {}
    issues: list[dict[str, Any]] = []
    for source_key, output_key in [
        ("stem", "stem_md"),
        ("subquestions", "subquestions"),
        ("options", "options"),
        ("answer", "answer_md"),
        ("explanation", "explanation_md"),
        ("teaching_note", "teaching_note_md"),
    ]:
        source_markdown = str((fields.get(source_key) or {}).get("markdown") or "").strip()
        if not source_markdown:
            continue
        output_markdown = packet_output_field_text(packet, output_key).strip()
        if not output_markdown:
            issues.append({"code": "source_field_missing", "field": source_key})
            continue
        if len(source_markdown) >= 80 and len(output_markdown) < max(24, int(len(source_markdown) * 0.35)):
            issues.append(
                {
                    "code": "source_field_shrunk",
                    "field": source_key,
                    "source_chars": len(source_markdown),
                    "output_chars": len(output_markdown),
                }
            )
    output_text = "\n".join(packet_text_chunks(packet))
    for asset_id in sorted(draft_required_asset_ids(draft) - asset_tokens(output_text)):
        issues.append({"code": "source_asset_missing", "field": "asset", "asset_id": asset_id})
    return {"status": "ok" if not issues else "risk", "issues": issues}


def projection_coverage(packet: dict[str, Any]) -> dict[str, Any]:
    q = packet.get("standard_question") or {}
    render = str(q.get("render_markdown") or "")
    issues: list[dict[str, Any]] = []
    for key in ["answer_md", "explanation_md", "teaching_note_md"]:
        value = str(q.get(key) or "").strip()
        if value and value[: min(40, len(value))] not in render:
            issues.append({"code": "render_missing_field", "field": key})
    all_assets = asset_tokens("\n".join(packet_text_chunks(packet)))
    render_assets = asset_tokens(render)
    for asset_id in sorted(all_assets - render_assets):
        issues.append({"code": "render_missing_asset", "field": "asset", "asset_id": asset_id})
    return {"status": "ok" if not issues else "risk", "issues": issues}


def markdown_issues(text: str) -> list[str]:
    issues: list[str] = []
    if text.count("$") % 2:
        issues.append("unbalanced_dollar")
    if "$^" in text:
        issues.append("math_closed_before_superscript")
    if "$_" in text:
        issues.append("math_closed_before_subscript")
    if "$$" in text:
        issues.append("inline_double_dollar")
    for marker in ["Math input error", "Missing open brace", "Missing close brace", "Double exponent", "Extra close brace"]:
        if marker in text:
            issues.append(marker)
    if re.search(r"\\left(?![A-Za-z])\s*\{", text):
        issues.append("bad_left_brace_delimiter")
    if re.search(r"\\right(?![A-Za-z])(?=\s*(?:\$|$|[，,。；;]))", text):
        issues.append("bad_right_missing_delimiter")
    if re.search(r"\\left(?![A-Za-z])\s*\{[^$]{0,160}=[^$]{1,160}=", text):
        issues.append("possible_equation_group_flattened")
    # A literal "\n" is suspicious only when it is not starting a TeX command such as \ne or \neq.
    if re.search(r"\\n(?![A-Za-z])", text):
        issues.append("literal_backslash_n")
    return issues


def find_doc_asset_manifest() -> dict[str, Any]:
    manifests = []
    for path in Path("outputs/docx_native_formula_token_stream_v0_1").rglob("asset_manifest_native.json"):
        manifests.append(path)
    return {"manifest_paths": [str(path) for path in manifests]}


def build_asset_map(doc_id: str, packets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    asset_map: dict[str, dict[str, Any]] = {}
    for path in Path("outputs/docx_native_formula_token_stream_v0_1").rglob("asset_manifest_native.json"):
        if doc_id not in str(path):
            continue
        try:
            manifest = read_json(path)
        except Exception:
            continue
        for asset in manifest.get("assets") or []:
            asset_id = asset.get("asset_id")
            if asset_id:
                asset_map[str(asset_id)] = asset
    for packet in packets:
        for asset in ((packet.get("asset_refs") or {}).get("visual_refs") or []):
            if isinstance(asset, dict) and asset.get("asset_id"):
                asset_id = str(asset["asset_id"])
                asset_map[asset_id] = {**asset_map.get(asset_id, {}), **asset}
    return asset_map


def convert_metafile_preview(source: Path, dest: Path) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "metafile preview conversion currently requires Windows System.Drawing"
    source_literal = str(source.resolve()).replace("'", "''")
    dest_literal = str(dest.resolve()).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$src = '{source_literal}'
$dst = '{dest_literal}'
$mf = [System.Drawing.Imaging.Metafile]::new($src)
$unit = [System.Drawing.GraphicsUnit]::Pixel
$bounds = $mf.GetBounds([ref]$unit)
$width = [Math]::Max(24, [int][Math]::Ceiling($bounds.Width))
$height = [Math]::Max(24, [int][Math]::Ceiling($bounds.Height))
if ($width -lt 80 -or $height -lt 80) {{
  $width = [Math]::Max($width * 4, 160)
  $height = [Math]::Max($height * 4, 80)
}}
$bmp = [System.Drawing.Bitmap]::new($width, $height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::White)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.DrawImage($mf, 0, 0, $width, $height)
$bmp.Save($dst, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
$mf.Dispose()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "metafile conversion failed").strip()
    return dest.exists() and dest.stat().st_size > 0, ""


def materialize_preview_assets(out_dir: Path, doc_id: str, packets: list[dict[str, Any]]) -> dict[str, Any]:
    asset_map = build_asset_map(doc_id, packets)
    asset_dir = out_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    used_assets = sorted(set(re.findall(r"asset://(docx_media_\d+)", json.dumps(packets, ensure_ascii=False))))
    browser_assets: dict[str, str] = {}
    unsupported: list[dict[str, Any]] = []
    for asset_id in used_assets:
        asset = asset_map.get(asset_id, {})
        storage_key = asset.get("storage_key")
        source = Path(storage_key) if storage_key else None
        if source and source.exists() and source.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            dest = asset_dir / f"{asset_id}{source.suffix.lower()}"
            shutil.copy2(source, dest)
            browser_assets[asset_id] = f"assets/{dest.name}"
        elif source and source.exists() and source.suffix.lower() in {".wmf", ".emf"}:
            dest = asset_dir / f"{asset_id}.png"
            converted, error = convert_metafile_preview(source, dest)
            if converted:
                browser_assets[asset_id] = f"assets/{dest.name}"
            else:
                unsupported.append(
                    {
                        "asset_id": asset_id,
                        "storage_key": storage_key,
                        "format": asset.get("format") or source.suffix[1:],
                        "exists": True,
                        "preview_error": error,
                    }
                )
        else:
            unsupported.append(
                {
                    "asset_id": asset_id,
                    "storage_key": storage_key,
                    "format": asset.get("format") or (source.suffix[1:] if source else None),
                    "exists": bool(source and source.exists()),
                }
            )
    return {
        "asset_local": browser_assets,
        "unsupported_or_missing": unsupported,
        "asset_token_count": len(used_assets),
        "browser_supported_asset_count": len(browser_assets),
    }


def render_review_html(out_dir: Path, summary: dict[str, Any], packets: list[dict[str, Any]], asset_local: dict[str, str]) -> None:
    cards: list[str] = []
    for packet in packets:
        gid = str(packet.get("source_group_id") or "")
        q = packet.get("standard_question") or {}
        text = str(q.get("render_markdown") or q.get("stem_md") or "")
        text = re.sub(
            r"asset://(docx_media_\d+)",
            lambda match: f"./{asset_local[match.group(1)]}" if match.group(1) in asset_local else f"asset://{match.group(1)}",
            text,
        )
        issues = next((item.get("issues") or [] for item in summary["packet_summaries"] if item["source_group_id"] == gid), [])
        issue_html = "".join(f'<span class="issue">{html.escape(str(issue))}</span> ' for issue in issues) or "none"
        # 中文说明：script 数据不解析 HTML 实体；保留合法 JSON，并转义可结束标签的字符。
        embedded_json = json.dumps(text, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        cards.append(
            f"""
<article class="card">
  <h2>{html.escape(gid)}</h2>
  <div class="meta">
    draft=<code>{html.escape(str(packet.get('source_draft_id')))}</code>
    status=<code>{html.escape(str(packet.get('refine_status')))}</code>
    projection=<code>{html.escape(str((packet.get('status_breakdown') or {}).get('projection_status')))}</code>
    type=<code>{html.escape(str(packet.get('question_type')))}</code>
    issues={issue_html}
  </div>
  <div class="render" id="r_{html.escape(gid)}"></div>
  <script type="application/json" id="m_{html.escape(gid)}">{embedded_json}</script>
</article>
"""
        )
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(summary['run_id'])}</title>
<script>
window.MathJax={{tex:{{inlineMath:[["$","$"],["\\\\(","\\\\)"]],displayMath:[["$$","$$"],["\\\\[","\\\\]"]]}},svg:{{fontCache:"global"}}}};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
body{{margin:0;background:#eef2f7;color:#111827;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px}}
.header{{background:white;border-bottom:1px solid #d7dee9;position:sticky;top:0;z-index:1;padding:14px 24px}}
.card{{background:white;border:1px solid #d7dee9;border-radius:8px;margin:18px 0;padding:20px}}
.meta{{color:#52627a;font-size:14px;margin:4px 0 14px}}
.issue{{color:#b91c1c;background:#fff1f2;padding:2px 6px;border-radius:4px}}
.render{{font-size:18px;line-height:1.85}}
.render img{{max-width:760px;height:auto;border:1px solid #cbd5e1;display:block;margin:10px 0}}
code{{background:#f1f5f9;padding:2px 5px;border-radius:4px}}
</style>
</head>
<body>
<div class="header"><b>{html.escape(summary['run_id'])}</b> packets={summary['packet_count']} ready={summary['refined_ready_count']} blocked={summary['blocked_count']}</div>
<main>
{''.join(cards)}
</main>
<script>
for (const script of document.querySelectorAll('script[type="application/json"]')) {{
  const gid = script.id.slice(2);
  document.getElementById('r_' + gid).innerHTML = marked.parse(JSON.parse(script.textContent));
}}
// 中文说明：defer 加载完成前只有配置对象；此时由 MathJax 启动流程自动排版。
if (window.MathJax && typeof MathJax.typesetPromise === "function") MathJax.typesetPromise();
</script>
</body>
</html>
"""
    (out_dir / "review.html").write_text(doc, encoding="utf-8")


def merge_runs(
    *,
    out_dir: Path,
    run_id: str,
    payload: dict[str, Any],
    ordered_group_ids: list[str],
    normal_run_id: str | None,
    retry_run_ids: list[str],
    retry_groups_by_run: dict[str, list[str]],
    unresolved_after_retry_groups: list[str],
    max_retry_rounds: int,
    long_run_ids: dict[str, str],
    gate_repair_run_id: str | None,
    auto_long_composite_enabled: bool,
    auto_long_composite_group_ids: set[str],
    child_summaries: dict[str, Any],
) -> dict[str, Any]:
    packets_by_group = collect_packets_by_group(
        normal_run_id=normal_run_id,
        retry_run_ids=retry_run_ids,
        retry_groups_by_run=retry_groups_by_run,
        long_run_ids=long_run_ids,
    )
    if gate_repair_run_id:
        gate_packets = load_gate_repair_packets(gate_repair_run_id)
        for group_id, packet in gate_packets.items():
            packets_by_group[group_id] = packet

    missing = [group_id for group_id in ordered_group_ids if group_id not in packets_by_group]
    if missing:
        raise RuntimeError(f"missing packets after merge: {missing}")
    packets = [packets_by_group[group_id] for group_id in ordered_group_ids]
    for packet in packets:
        ensure_render_markdown(packet)
    doc_id = str(payload.get("doc_id") or "")
    asset_resolution = materialize_preview_assets(out_dir, doc_id, packets)

    draft_by_group = {
        str(item.get("source_group_id")): item
        for item in payload.get("draft_items") or []
        if item.get("source_group_id")
    }
    packet_summaries = []
    for packet in packets:
        text = packet_markdown(packet)
        source_coverage = source_field_coverage(packet, draft_by_group.get(str(packet.get("source_group_id") or "")))
        render_coverage = projection_coverage(packet)
        packet["source_field_coverage"] = source_coverage
        packet["projection_coverage"] = render_coverage
        issues = markdown_issues(text)
        coverage_issues = list(source_coverage.get("issues") or []) + list(render_coverage.get("issues") or [])
        if coverage_issues:
            packet.setdefault("warnings", []).extend(
                {
                    "code": str(issue.get("code") or ""),
                    "message": str(issue),
                    "refs": [str(packet.get("source_group_id") or "")],
                }
                for issue in coverage_issues
            )
            status = packet.setdefault("status_breakdown", {})
            status["projection_status"] = "READY_WITH_COVERAGE_WARNINGS"
            risk_codes = set(status.get("risk_codes") or [])
            risk_codes.update(str(issue.get("code") or "") for issue in coverage_issues)
            status["risk_codes"] = sorted(risk_codes)
            if packet.get("refine_status") == "REFINED_READY":
                packet["refine_status"] = "REFINED_NEEDS_REVIEW"
                packet.setdefault("normalization_actions", []).append(
                    {
                        "action": "downgrade_ready_packet_after_source_or_projection_coverage_risk",
                        "scope": "fullchain_orchestrator_merge",
                    }
                )
        elif not issues and packet.get("refine_status") != "REFINED_READY":
            packet["refine_status"] = "REFINED_READY"
            status = packet.setdefault("status_breakdown", {})
            status["projection_status"] = "READY"
            packet.setdefault("normalization_actions", []).append(
                {
                    "action": "post_merge_reconcile_ready_after_clean_gate",
                    "scope": "fullchain_orchestrator_merge",
                }
            )
        packet_summaries.append(
            {
                "source_group_id": packet.get("source_group_id"),
                "source_draft_id": packet.get("source_draft_id"),
                "refine_status": packet.get("refine_status"),
                "question_type": packet.get("question_type") or (packet.get("standard_question") or {}).get("question_type"),
                "projection_status": (packet.get("status_breakdown") or {}).get("projection_status"),
                "markdown_chars": len(text),
                "asset_tokens": sorted(set(re.findall(r"asset://(docx_media_\d+)", text))),
                "issues": issues,
                "source_field_coverage": source_coverage,
                "projection_coverage": render_coverage,
            }
        )

    total_tokens = 0
    for summary in child_summaries.values():
        value = summary.get("total_tokens")
        if isinstance(value, int):
            total_tokens += value

    summary = {
        "schema": "docx_math_fullchain_orchestrator.run_summary_v0.1",
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": doc_id,
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "input_draft_payload": payload.get("_draft_payload_path"),
        "normal_refiner_run_id": normal_run_id,
        "retry_refiner_run_id": retry_run_ids[-1] if retry_run_ids else None,
        "retry_groups": sorted({group_id for groups in retry_groups_by_run.values() for group_id in groups}),
        "retry_run_ids": retry_run_ids,
        "retry_groups_by_run": retry_groups_by_run,
        "retry_round_count": len(retry_run_ids),
        "max_retry_rounds": max_retry_rounds,
        "unresolved_after_retry_groups": unresolved_after_retry_groups,
        "long_composite_run_ids": long_run_ids,
        "gate_repair_run_id": gate_repair_run_id,
        "auto_long_composite_enabled": auto_long_composite_enabled,
        "auto_long_composite_group_ids": sorted(auto_long_composite_group_ids),
        "packet_count": len(packets),
        "refined_ready_count": sum(1 for packet in packets if packet.get("refine_status") == "REFINED_READY"),
        "blocked_count": sum(1 for packet in packets if (packet.get("status_breakdown") or {}).get("projection_status") == "BLOCKED"),
        "packet_summaries": packet_summaries,
        "remaining_issue_count": sum(1 for item in packet_summaries if item["issues"]),
        "coverage_issue_count": sum(
            1
            for item in packet_summaries
            if item["source_field_coverage"]["status"] != "ok" or item["projection_coverage"]["status"] != "ok"
        ),
        "total_tokens": total_tokens,
        "asset_token_count": asset_resolution["asset_token_count"],
        "browser_supported_asset_count": asset_resolution["browser_supported_asset_count"],
        "browser_unsupported_or_missing_assets": asset_resolution["unsupported_or_missing"],
        "child_summaries": child_summaries,
    }
    write_json(out_dir / "run_summary.json", summary)
    write_json(out_dir / "final_packets.json", {"schema": "docx_math_fullchain_packets_v0.1", "summary": summary, "packets": packets})
    write_json(out_dir / "asset_resolution.json", asset_resolution)
    render_review_html(out_dir, summary, packets, asset_resolution["asset_local"])
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path.cwd()
    out_dir = Path(args.out_root) / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "subprocess_logs"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if args.api_key:
        env["ARK_API_KEY"] = args.api_key
    if not env.get("ARK_API_KEY"):
        raise RuntimeError("ARK_API_KEY is required via environment or --api-key")

    input_draft_root = Path(args.input_draft_root)
    payload = load_draft_payload(Path(args.draft_payload_path)) if args.draft_payload_path else find_draft_payload(input_draft_root, args.doc_id_contains)
    effective_doc_id_contains = str(payload.get("doc_id") or args.doc_id_contains)
    all_group_ids = group_ids_from_payload(payload)
    selected_group_ids = args.group_ids or all_group_ids
    auto_long_group_ids = auto_long_composite_group_ids(
        payload,
        selected_group_ids,
        enabled=bool(args.auto_long_composite),
        min_chars=args.auto_long_min_chars,
        min_blocks=args.auto_long_min_blocks,
        min_explanation_chars=args.auto_long_min_explanation_chars,
    )
    long_group_ids = set(args.long_group_ids or []) | auto_long_group_ids
    unknown_long = sorted(long_group_ids - set(selected_group_ids))
    if unknown_long:
        raise RuntimeError(f"long_group_ids are not in selected groups: {unknown_long}")

    normal_group_ids = [group_id for group_id in selected_group_ids if group_id not in long_group_ids]
    child_summaries: dict[str, Any] = {}

    normal_run_id: str | None = None
    normal_summary: dict[str, Any] = {
        "schema": "docx_math_question_refiner.skipped_summary",
        "run_id": None,
        "skipped": True,
        "reason": "no normal groups after long composite routing",
        "group_count": 0,
        "total_tokens": 0,
    }
    if normal_group_ids:
        normal_run_id = f"{args.run_id}__normal"
        normal_summary = run_question_refiner(
            repo_root=repo_root,
            env=env,
            input_draft_root=input_draft_root,
            run_id=normal_run_id,
            doc_id_contains=effective_doc_id_contains,
            group_ids=normal_group_ids,
            max_workers=args.normal_workers,
            log_path=log_dir / "normal_refiner.json",
        )
    child_summaries["normal_refiner"] = normal_summary

    retry_groups = failed_groups(normal_summary)
    retry_run_ids: list[str] = []
    retry_groups_by_run: dict[str, list[str]] = {}
    if args.max_retry_rounds < 0:
        raise RuntimeError("--max-retry-rounds must be >= 0")
    retry_round = 0
    while retry_groups and args.retry_failed and retry_round < args.max_retry_rounds:
        retry_round += 1
        retry_run_id = f"{args.run_id}__normal_retry_r{retry_round:02d}"
        retry_summary = run_question_refiner(
            repo_root=repo_root,
            env=env,
            input_draft_root=input_draft_root,
            run_id=retry_run_id,
            doc_id_contains=effective_doc_id_contains,
            group_ids=retry_groups,
            max_workers=args.normal_workers,
            log_path=log_dir / f"normal_retry_refiner_r{retry_round:02d}.json",
        )
        retry_run_ids.append(retry_run_id)
        retry_groups_by_run[retry_run_id] = retry_groups
        child_summaries[f"normal_retry_refiner_r{retry_round:02d}"] = retry_summary
        retry_groups = failed_groups(retry_summary)

    long_run_ids: dict[str, str] = {}
    for group_id in sorted(long_group_ids):
        long_run_id = f"{args.run_id}__long_{group_id}"
        long_summary = run_long_composite_refiner(
            repo_root=repo_root,
            env=env,
            input_draft_root=input_draft_root,
            run_id=long_run_id,
            doc_id_contains=effective_doc_id_contains,
            group_id=group_id,
            max_workers=args.long_workers,
            log_path=log_dir / f"long_{group_id}.json",
        )
        long_run_ids[group_id] = long_run_id
        child_summaries[f"long_composite_{group_id}"] = long_summary

    gate_repair_run_id: str | None = None
    if args.gate_repair:
        pre_gate_packets = collect_packets_by_group(
            normal_run_id=normal_run_id,
            retry_run_ids=retry_run_ids,
            retry_groups_by_run=retry_groups_by_run,
            long_run_ids=long_run_ids,
        )
        pre_gate_missing = [group_id for group_id in selected_group_ids if group_id not in pre_gate_packets]
        if pre_gate_missing:
            raise RuntimeError(f"missing packets before gate repair: {pre_gate_missing}")
        pre_gate_snapshot_run_id = f"{args.run_id}__pre_gate_repair_snapshot"
        snapshot_summary = write_refiner_snapshot(
            run_id=pre_gate_snapshot_run_id,
            payload=payload,
            ordered_group_ids=selected_group_ids,
            packets_by_group=pre_gate_packets,
            out_dir=out_dir,
        )
        child_summaries["pre_gate_repair_snapshot"] = snapshot_summary
        gate_repair_run_id = f"{args.run_id}__gate_repair"
        gate_repair_summary = run_refine_gate_repair(
            repo_root=repo_root,
            env=env,
            input_draft_root=input_draft_root,
            run_id=gate_repair_run_id,
            doc_id_contains=effective_doc_id_contains,
            refiner_run_id=pre_gate_snapshot_run_id,
            group_ids=selected_group_ids,
            max_workers=args.gate_repair_workers,
            log_path=log_dir / "gate_repair.json",
        )
        child_summaries["gate_repair"] = gate_repair_summary

    return merge_runs(
        out_dir=out_dir,
        run_id=args.run_id,
        payload=payload,
        ordered_group_ids=selected_group_ids,
        normal_run_id=normal_run_id,
        retry_run_ids=retry_run_ids,
        retry_groups_by_run=retry_groups_by_run,
        unresolved_after_retry_groups=retry_groups,
        max_retry_rounds=args.max_retry_rounds,
        long_run_ids=long_run_ids,
        gate_repair_run_id=gate_repair_run_id,
        auto_long_composite_enabled=bool(args.auto_long_composite),
        auto_long_composite_group_ids=auto_long_group_ids,
        child_summaries=child_summaries,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DOCX math draft -> refined packet fullchain orchestration.")
    parser.add_argument("--input-draft-root", required=True)
    parser.add_argument("--draft-payload-path", default="")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id-contains", required=True)
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--long-group-ids", nargs="*", default=[])
    parser.add_argument("--normal-workers", type=int, default=4)
    parser.add_argument("--long-workers", type=int, default=3)
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--retry-failed", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-retry-rounds", type=int, default=3)
    parser.add_argument("--auto-long-composite", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--auto-long-min-chars", type=int, default=2200)
    parser.add_argument("--auto-long-min-blocks", type=int, default=36)
    parser.add_argument("--auto-long-min-explanation-chars", type=int, default=1600)
    parser.add_argument("--gate-repair", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--gate-repair-workers", type=int, default=4)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
