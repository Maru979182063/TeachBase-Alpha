from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

REF_FIELDS = [
    "anchor_block_refs",
    "member_block_refs",
    "context_block_refs",
    "solution_block_refs",
    "analysis_block_refs",
    "translation_block_refs",
    "visual_block_refs",
    "carryover_block_refs",
]

OPEN_STATUS_RANK = {
    "closed": 5,
    "open_from_previous": 4,
    "open_to_next": 4,
    "open_both": 3,
    "fragment": 2,
    "unknown": 1,
}

CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def unique_refs(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for ref in refs:
        if ref and ref not in seen:
            seen.add(ref)
            result.append(ref)
    return result


def group_ref_set(group: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for field in REF_FIELDS:
        refs.update(group.get(field) or [])
    return refs


def member_set(group: dict[str, Any]) -> set[str]:
    return set(group.get("member_block_refs") or [])


def anchor_set(group: dict[str, Any]) -> set[str]:
    return set(group.get("anchor_block_refs") or [])


def is_carryover_only(group: dict[str, Any]) -> bool:
    return not group.get("anchor_block_refs") and bool(group.get("carryover_block_refs"))


def is_anchorless_residual(group: dict[str, Any]) -> bool:
    return not group.get("anchor_block_refs")


def overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def should_cluster(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
    a_members = member_set(a)
    b_members = member_set(b)
    a_refs = group_ref_set(a)
    b_refs = group_ref_set(b)
    a_anchors = anchor_set(a)
    b_anchors = anchor_set(b)

    if is_carryover_only(a) or is_carryover_only(b):
        if overlap_ratio(a_refs, b_refs) >= 0.95:
            return True, "carryover refs are covered by another observation"
        return False, ""

    if is_anchorless_residual(a) or is_anchorless_residual(b):
        if a_refs <= b_refs or b_refs <= a_refs:
            return True, "anchorless residual refs are covered by another observation"
        if overlap_ratio(a_refs, b_refs) >= 0.85:
            return True, "anchorless residual has strong evidence overlap"
        return False, ""

    if a_members and b_members:
        if a_members <= b_members or b_members <= a_members:
            return True, "member refs have subset containment"

    if a_anchors and b_anchors and a_anchors & b_anchors:
        if jaccard(a_refs, b_refs) >= 0.45 or overlap_ratio(a_members, b_members) >= 0.60:
            return True, "shared anchor refs with strong evidence overlap"

    if overlap_ratio(a_members, b_members) >= 0.85 and jaccard(a_refs, b_refs) >= 0.55:
        return True, "strong member-ref overlap"

    return False, ""


def observation_score(obs: dict[str, Any]) -> tuple[int, int, int, int, int]:
    group = obs["group"]
    return (
        len(member_set(group)),
        OPEN_STATUS_RANK.get(group.get("open_status"), 0),
        len(group_ref_set(group)),
        CONFIDENCE_RANK.get(group.get("confidence"), 0),
        obs.get("page_number", 0),
    )


def merge_cluster(cluster_id: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    primary = max(observations, key=observation_score)
    primary_group = primary["group"]
    merged: dict[str, Any] = {
        "document_group_id": cluster_id,
        "group_kind": primary_group.get("group_kind", ""),
        "open_status": primary_group.get("open_status", "unknown"),
        "confidence": primary_group.get("confidence", "low"),
        "primary_observation_id": primary["observation_id"],
        "observation_ids": [obs["observation_id"] for obs in observations],
        "source_pages": sorted({obs["page_number"] for obs in observations}),
        "dedupe_strategy": "ref_set_containment_and_overlap_v0.1",
        "dedupe_notes": [],
    }
    for field in REF_FIELDS:
        refs: list[str] = []
        for obs in observations:
            refs.extend(obs["group"].get(field) or [])
        merged[field] = unique_refs(refs)

    statuses = sorted({obs["group"].get("open_status", "unknown") for obs in observations})
    if len(statuses) > 1:
        merged["dedupe_notes"].append(
            {
                "code": "mixed_open_status",
                "message": "Multiple window observations disagreed on open_status; primary observation status was kept.",
                "observed_statuses": statuses,
            }
        )

    if not merged["member_block_refs"]:
        merged["dedupe_notes"].append(
            {
                "code": "empty_member_refs",
                "message": "Merged group has no member_block_refs; keep for audit only.",
            }
        )

    return merged


def load_observations(run_dir: Path, doc_id: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    doc_dir = run_dir / doc_id
    observations: list[dict[str, Any]] = []
    block_text_by_ref: dict[str, str] = {}
    for page_dir in sorted(doc_dir.glob("page_*")):
        composition_path = page_dir / "sliding_window_composition.json"
        window_path = page_dir / "window_input.json"
        if not composition_path.exists():
            continue
        composition = read_json(composition_path)
        page_number = int(composition.get("current_page") or page_dir.name.split("_")[-1])
        if window_path.exists():
            window = read_json(window_path)
            for key in ["previous_tail_blocks", "current_page_blocks", "next_head_blocks"]:
                for block in window.get(key, []):
                    block_text_by_ref[block["block_ref"]] = block.get("text", "")
        for index, group in enumerate(composition.get("groups") or [], start=1):
            observation_id = f"{doc_id}_p{page_number:03d}_{group.get('group_id', f'g_{index:03d}')}"
            observations.append(
                {
                    "observation_id": observation_id,
                    "doc_id": doc_id,
                    "page_number": page_number,
                    "window_id": composition.get("window_id", ""),
                    "group": group,
                }
            )
    return observations, block_text_by_ref


def cluster_observations(observations: list[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    decisions: list[dict[str, Any]] = []
    for obs in observations:
        placed = False
        for cluster in clusters:
            matched_reasons: list[str] = []
            for existing in cluster:
                matched, reason = should_cluster(obs["group"], existing["group"])
                if matched:
                    matched_reasons.append(reason)
            if matched_reasons:
                cluster.append(obs)
                placed = True
                decisions.append(
                    {
                        "observation_id": obs["observation_id"],
                        "cluster_index": clusters.index(cluster) + 1,
                        "decision": "merged",
                        "reasons": unique_refs(matched_reasons),
                    }
                )
                break
        if not placed:
            clusters.append([obs])
            decisions.append(
                {
                    "observation_id": obs["observation_id"],
                    "cluster_index": len(clusters),
                    "decision": "new_cluster",
                    "reasons": [],
                }
            )
    return clusters, decisions


def render_review(result: dict[str, Any], block_text_by_ref: dict[str, str]) -> str:
    rows: list[str] = []
    for group in result["document_groups"]:
        ref_parts: list[str] = []
        for field, label in [
            ("anchor_block_refs", "anchor（锚点）"),
            ("context_block_refs", "context（上下文）"),
            ("solution_block_refs", "solution（答案）"),
            ("analysis_block_refs", "analysis（解析）"),
            ("translation_block_refs", "translation（翻译）"),
            ("visual_block_refs", "visual（视觉/表格/图示）"),
            ("carryover_block_refs", "carryover（跨页承接）"),
        ]:
            refs = group.get(field) or []
            if refs:
                ref_parts.append(f"<div><b>{label}</b>: {html.escape(', '.join(refs))}</div>")
        samples = []
        for ref in (group.get("anchor_block_refs") or group.get("member_block_refs") or [])[:3]:
            text = block_text_by_ref.get(ref, "").replace("\n", " ")
            samples.append(f"<li><code>{html.escape(ref)}</code>: {html.escape(text[:180])}</li>")
        notes = "".join(
            f"<li>{html.escape(note.get('code', ''))}: {html.escape(note.get('message', ''))}</li>"
            for note in group.get("dedupe_notes", [])
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(group['document_group_id'])}</td>"
            f"<td>{html.escape(group.get('group_kind', ''))}</td>"
            f"<td>{html.escape(group.get('open_status', ''))}</td>"
            f"<td>{html.escape(str(group.get('source_pages', [])))}</td>"
            f"<td>{html.escape(group.get('primary_observation_id', ''))}<br>{html.escape(', '.join(group.get('observation_ids', [])))}</td>"
            f"<td>{''.join(ref_parts)}<ul>{''.join(samples)}</ul><ul>{notes}</ul></td>"
            "</tr>"
        )
    return (
        "<!doctype html><meta charset=\"utf-8\">"
        "<title>Document Group Dedupe Review</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.5}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;vertical-align:top}"
        "th{background:#f4f4f4}code{background:#eee;padding:1px 4px;border-radius:3px}</style>"
        "<h1>Document Group Dedupe Review</h1>"
        f"<p>observations（窗口观察组）={result['summary']['observations']}, "
        f"document_groups（文档级去重组）={result['summary']['document_groups']}, "
        f"merged_observations（被合并观察）={result['summary']['merged_observations']}</p>"
        "<p>去重只使用 block_ref 引用集合关系，不读取题型关键词，不做 family 特例。</p>"
        "<table><thead><tr><th>id</th><th>group_kind（开放类型）</th><th>open_status（开闭）</th>"
        "<th>pages（来源页）</th><th>observations（来源观察）</th><th>refs（引用）</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = workspace_path(args.node2_run)
    out_dir = workspace_path(args.out_dir) if args.out_dir else run_dir / "document_group_dedupe_v01"
    observations, block_text_by_ref = load_observations(run_dir, args.doc_id)
    clusters, decisions = cluster_observations(observations)
    document_groups = [
        merge_cluster(f"dg_{index:03d}", cluster)
        for index, cluster in enumerate(clusters, start=1)
    ]
    merged_observations = sum(max(0, len(cluster) - 1) for cluster in clusters)
    result = {
        "schema": "english_text_first_document_group_dedupe_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_node2_run": str(run_dir),
        "doc_id": args.doc_id,
        "summary": {
            "observations": len(observations),
            "document_groups": len(document_groups),
            "merged_observations": merged_observations,
            "strategy": "ref_set_containment_and_overlap_v0.1",
            "content_regex_rules": 0,
            "family_specific_rules": 0,
        },
        "document_groups": document_groups,
        "dedupe_decisions": decisions,
    }
    write_json(out_dir / "document_groups.json", result)
    write_json(out_dir / "dedupe_decisions.json", decisions)
    (out_dir / "document_group_dedupe_review.html").write_text(render_review(result, block_text_by_ref), encoding="utf-8")
    return result | {"out_dir": str(out_dir), "review_html": str(out_dir / "document_group_dedupe_review.html")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node2-run", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
