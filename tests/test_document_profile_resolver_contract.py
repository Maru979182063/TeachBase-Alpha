from __future__ import annotations

from tools.document_profile_resolver import resolve_document_profile


def test_profile_resolver_mock_contract_math() -> None:
    profile, metrics = resolve_document_profile(provider="mock", pdf_path="高中数学/函数讲义-教师版.pdf", doc_key="math")
    assert profile["profile_version"] == "document_profile_v0.2"
    assert profile["document_profile_id"]
    assert profile["effective_profile"]["subject"] == "math"
    assert metrics["calls"] == 0


def test_profile_manual_override_wins_and_marks_conflict() -> None:
    profile, _ = resolve_document_profile(
        provider="mock",
        pdf_path="高中数学/函数讲义-教师版.pdf",
        doc_key="math",
        manual_override={"subject": "english", "document_type": "teacher_handout"},
    )
    assert profile["effective_profile"]["subject"] == "english"
    assert profile["profile_conflict"] is True
    assert profile["needs_profile_review"] is True

