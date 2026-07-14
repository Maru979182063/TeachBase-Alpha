from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def resolve_document_profile(*, doc_root: Path, semantic_nodes: dict[str, Any], audit_report: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic sidecar profile without reading models or mutating pipeline artifacts."""
    nodes = list(semantic_nodes.get("nodes") or [])
    audit_records = list(audit_report.get("records") or [])
    status_counts = Counter(str(node.get("review_status") or "") for node in nodes)
    node_type_counts = Counter(str(node.get("node_type") or "") for node in nodes)
    pages = sorted(
        {
            int(fragment.get("page"))
            for node in nodes
            for fragment in (node.get("fragments") or [])
            if fragment.get("page") is not None
        }
    )
    review_reasons = sorted(
        {
            str(reason)
            for record in audit_records
            for reason in (record.get("reasons") or [])
        }
    )
    return {
        "schema_version": "document_profile_shadow.v0.1",
        "doc_root": str(doc_root),
        "resolver_mode": "deterministic_sidecar",
        "model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
        "node_count": len(nodes),
        "node_type_counts": dict(sorted(node_type_counts.items())),
        "review_status_counts": dict(sorted(status_counts.items())),
        "pages": pages,
        "review_reasons": review_reasons,
    }
