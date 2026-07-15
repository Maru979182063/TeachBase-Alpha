from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import read_json, write_json
from teachbase.infrastructure.hashing import sha256_file


def safe_rel(path: Path, workspace_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def discover_candidate_manifest(candidate_roots: list[Path], workspace_root: Path) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for root in candidate_roots:
        root = root.resolve()
        if not root.exists():
            continue
        for semantic_nodes_path in sorted(root.rglob("semantic_nodes.json"), key=lambda path: safe_rel(path, workspace_root)):
            if "semantic_role_effectiveness_eval" in semantic_nodes_path.parts:
                continue
            try:
                payload = read_json(semantic_nodes_path)
            except Exception:
                continue
            for node in payload.get("nodes", []) or []:
                node_id = str(node.get("node_id") or "")
                if not node_id:
                    continue
                rel_path = safe_rel(semantic_nodes_path, workspace_root)
                key = (rel_path, node_id)
                if key in by_key:
                    continue
                fragments = node.get("fragments") or []
                pages = sorted({int(fragment.get("page")) for fragment in fragments if fragment.get("page") is not None})
                source_sha256 = sha256_file(semantic_nodes_path)
                stable_seed = f"{rel_path}\n{source_sha256}\n{node_id}"
                by_key[key] = {
                    "candidate_id": "candidate_" + hashlib.sha256(stable_seed.encode("utf-8")).hexdigest()[:16],
                    "source_artifact_path": rel_path,
                    "source_artifact_sha256": source_sha256,
                    "node_id": node_id,
                    "page_range": pages,
                    "discovery_reason": "semantic_nodes_json_node",
                    "discovered_at": "deterministic_manifest_v0.1",
                    "candidate_status": "REVIEW_REQUIRED",
                    "node_type": str(node.get("node_type") or ""),
                    "review_status": str(node.get("review_status") or ""),
                    "text_stub": str(node.get("text_stub") or "")[:200],
                }
    return [by_key[key] for key in sorted(by_key)]


def write_candidate_manifest(candidate_roots: list[Path], out_path: Path, workspace_root: Path) -> dict[str, Any]:
    candidates = discover_candidate_manifest(candidate_roots, workspace_root)
    manifest = {
        "schema_version": "semantic_role_candidate_manifest_v0.1",
        "created_at": "deterministic_manifest_v0.1",
        "candidate_roots": [safe_rel(path, workspace_root) for path in candidate_roots],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    write_json(out_path, manifest)
    return manifest


def candidate_manifest_to_cases(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("candidates"), list):
        raise ValueError(f"candidate_manifest_must_have_candidates:{manifest_path}")
    cases: list[dict[str, Any]] = []
    for row in manifest["candidates"]:
        cases.append(
            {
                "case_id": str(row.get("candidate_id") or ""),
                "subject": "unknown",
                "document_type": "unknown",
                "source_document_ref": str(row.get("source_artifact_path") or ""),
                "source_document_sha256": str(row.get("source_artifact_sha256") or ""),
                "page_range": row.get("page_range") or [],
                "node_id": str(row.get("node_id") or ""),
                "source_artifact_ref": str(row.get("source_artifact_path") or ""),
                "source_image_ref": "",
                "source_text_stub": str(row.get("text_stub") or ""),
                "current_node_type": str(row.get("node_type") or ""),
                "current_review_status": str(row.get("review_status") or ""),
                "current_review_reasons": [],
                "expected_semantic_role": "",
                "expected_presentation_kind": "",
                "expected_disposition": "",
                "expected_route_candidate": "",
                "expected_relations": [],
                "expected_needs_role_review": False,
                "evaluation_tier": "CANDIDATE_REVIEW",
                "gold_status": "REVIEW_REQUIRED",
                "gold_source": "candidate_discovery",
                "gold_evidence": [],
                "difficulty_tags": ["candidate_discovery"],
                "notes": "Manifest-discovered candidate. It is excluded from formal metrics until human Gold is verified.",
            }
        )
    return cases
