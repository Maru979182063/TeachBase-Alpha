from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .control import FinalChainRegistry


def build_cleanroom_import_audit(
    registry: FinalChainRegistry,
    *,
    workspace_root: Path,
    source_roots: dict[str, Path] | None = None,
    handoff_inventories: dict[str, Path] | None = None,
) -> dict[str, Any]:
    source_roots = source_roots or {}
    expected_hashes = _load_handoff_hashes(handoff_inventories or {})
    rows = []
    for chain in registry.chains:
        for role, relative_path in _required_paths_for_chain(chain).items():
            workspace_path = workspace_root / relative_path
            cleanroom = _file_state(workspace_path)
            candidates = []
            for source_label, source_root in sorted(source_roots.items()):
                candidate_path = source_root / relative_path
                state = _file_state(candidate_path)
                candidates.append(
                    {
                        "source_label": source_label,
                        "relative_path": relative_path,
                        "exists": state["exists"],
                        "bytes": state["bytes"],
                        "sha256": state["sha256"],
                        "matches_handoff_inventory": _matches_expected_hash(
                            chain.chain_id, relative_path, state["sha256"], expected_hashes
                        ),
                    }
                )
            rows.append(
                {
                    "chain_id": chain.chain_id,
                    "role": role,
                    "relative_path": relative_path,
                    "cleanroom_exists": cleanroom["exists"],
                    "cleanroom_bytes": cleanroom["bytes"],
                    "cleanroom_sha256": cleanroom["sha256"],
                    "handoff_inventory_sha256": expected_hashes.get(chain.chain_id, {}).get(relative_path),
                    "source_candidates": candidates,
                    "import_action": _import_action(cleanroom, candidates),
                }
            )
    return {
        "schema_version": "final_chain_cleanroom_import_audit.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_count": len(registry.chains),
        "source_labels": sorted(source_roots),
        "handoff_inventory_labels": sorted(handoff_inventories or {}),
        "row_count": len(rows),
        "missing_in_cleanroom_count": sum(1 for row in rows if not row["cleanroom_exists"]),
        "importable_candidate_count": sum(
            1 for row in rows if any(candidate["exists"] for candidate in row["source_candidates"])
        ),
        "rows": rows,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _required_paths_for_chain(chain) -> dict[str, str]:
    paths = {"canonical_entrypoint": chain.canonical_entrypoint}
    for index, config_path in enumerate(chain.canonical_config_paths, start=1):
        paths[f"canonical_config_{index}"] = config_path
    return paths


def _file_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "bytes": 0, "sha256": ""}
    data = path.read_bytes()
    return {"exists": True, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _load_handoff_hashes(handoff_inventories: dict[str, Path]) -> dict[str, dict[str, str]]:
    loaded: dict[str, dict[str, str]] = {}
    for chain_id, path in handoff_inventories.items():
        if not path.is_file():
            loaded[chain_id] = {}
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        hashes = {}
        for item in payload.get("files", []):
            if isinstance(item, dict) and item.get("path") and item.get("sha256"):
                hashes[str(item["path"]).replace("\\", "/")] = str(item["sha256"])
        loaded[chain_id] = hashes
    return loaded


def _matches_expected_hash(
    chain_id: str,
    relative_path: str,
    sha256: str,
    expected_hashes: dict[str, dict[str, str]],
) -> bool | None:
    expected = expected_hashes.get(chain_id, {}).get(relative_path)
    if expected is None or not sha256:
        return None
    return expected == sha256


def _import_action(cleanroom: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    if cleanroom["exists"]:
        return "already_present_in_cleanroom"
    if any(candidate["exists"] for candidate in candidates):
        return "candidate_available_for_reviewed_import"
    return "source_missing_or_not_provided"
