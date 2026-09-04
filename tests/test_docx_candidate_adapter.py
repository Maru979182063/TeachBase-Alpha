"""中文说明：验证候选映射不丢公式、审核警告及原始证据，存储冲突不能静默覆盖。"""
import importlib.util
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("candidate_adapter", ROOT / "tools/import_docx_math_candidates.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def packet():
    return {"source_group_id": "dq_0042", "question_type": "multiple_choice",
            "refine_status": "REFINED_NEEDS_REVIEW", "warnings": ["unresolved_context"],
            "standard_question": {"title": "", "stem_md": r"$\textcircled{1}$",
                "subquestions": [], "options": [], "answer_md": "AD",
                "explanation_md": r"$\textcircled{1} + \textcircled{4}$",
                "context_md": "待审核上下文", "teaching_note_md": "保留教学说明",
                "render_markdown": r"$\textcircled{1}$"}}


def test_latex_and_review_evidence_survive_mapping():
    original = packet()
    result = adapter.map_packet(original, "a" * 64, "b" * 64, "数学", {}, {})
    assert result["content"] == original["standard_question"]
    assert result["provenance"]["upstreamPacket"] == original
    assert result["analysisMarkdown"] == original["standard_question"]["explanation_md"]
    assert result["reviewStatus"] == "pending_review"
    original["refine_status"] = "REFINED_READY"
    assert adapter.map_packet(original, "a" * 64, "b" * 64, "数学", {}, {})["reviewStatus"] == "pending_review"


def test_failed_refinement_and_missing_stem_are_blocked():
    original = packet()
    original["refine_status"] = "REFINE_FAILED"
    with pytest.raises(ValueError, match="candidate_refinement_failed"):
        adapter.map_packet(original, "a" * 64, "b" * 64, "数学", {}, {})
    original = packet()
    original["standard_question"]["stem_md"] = " "
    with pytest.raises(ValueError, match="candidate_stem_missing"):
        adapter.map_packet(original, "a" * 64, "b" * 64, "数学", {}, {})


def test_same_ordinal_in_changed_bundle_cannot_overwrite_old_identity():
    first = adapter.map_packet(packet(), "a" * 64, "b" * 64, "数学", {}, {})
    changed = adapter.map_packet(packet(), "a" * 64, "c" * 64, "数学", {}, {})
    assert first["sourceKey"] != changed["sourceKey"]


def test_storage_collision_fails_without_overwriting(tmp_path):
    source = tmp_path / "source.docx"
    source.write_bytes(b"original bytes")
    storage = tmp_path / "storage"
    registered = adapter.store_file(source, storage)
    target = storage / registered["storageKey"]
    target.write_bytes(b"unexpected bytes")
    with pytest.raises(ValueError, match="storage_hash_conflict"):
        adapter.store_file(source, storage)
    assert target.read_bytes() == b"unexpected bytes"


def test_final_contract_only_extends_documented_operational_fields():
    schema = adapter.final_packet_schema()
    assert schema["additionalProperties"] is False
    actions = schema["properties"]["normalization_actions"]["items"]
    jsonschema.validate({"action": "source_preserve_fallback", "reason": "validation_failed"}, actions)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"unidentified": "operation"}, actions)
    status = schema["properties"]["status_breakdown"]["properties"]["projection_status"]
    jsonschema.validate("READY_WITH_COVERAGE_WARNINGS", status)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("APPROVED", status)
