from __future__ import annotations

import json
from pathlib import Path


def test_golden_fixture_has_required_fields() -> None:
    fixture = json.loads(Path("tests/fixtures/semantic_role_adapter_golden.yml").read_text(encoding="utf-8"))
    required = {
        "case_id",
        "source_document_id",
        "page_range",
        "node_id",
        "expected_semantic_role",
        "expected_presentation_kind",
        "expected_disposition",
        "expected_route",
        "expected_relations",
        "expected_review_required",
        "boundary_quality",
        "error_scope",
    }
    assert fixture["cases"]
    for case in fixture["cases"]:
        assert required <= set(case)

