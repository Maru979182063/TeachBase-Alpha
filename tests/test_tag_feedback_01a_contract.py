from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JAVA_ROOT = ROOT / "backend" / "teachbase-server" / "src" / "main" / "java"
MIGRATION = (
    ROOT
    / "backend"
    / "teachbase-server"
    / "src"
    / "main"
    / "resources"
    / "db"
    / "migration"
    / "V011__teacher_tag_feedback_capture_core.sql"
)


def test_v011_is_additive_and_has_six_feedback_tables() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    expected = {
        "tagging_run",
        "question_tag_snapshot",
        "question_tag_snapshot_item",
        "question_tag_feedback",
        "question_tag_state",
        "taxonomy_gap_case",
    }
    assert all(f"create table teachbase_app.{table}" in sql for table in expected)
    assert "alter table teachbase_app.question_revision" not in sql
    assert "alter table teachbase_app.review_" not in sql
    assert "alter table teachbase_app.question_taxonomy_link" not in sql
    assert "uq_question_tag_snapshot_one_primary" in sql
    assert "tag_feedback_fact_immutable" in sql


def test_tag_feedback_module_has_no_question_review_or_legacy_link_writer() -> None:
    module = JAVA_ROOT / "com" / "teachbase" / "server" / "tagfeedback"
    source = "\n".join(path.read_text(encoding="utf-8") for path in module.rglob("*.java"))
    assert "QuestionRevisionDirectory" in source
    assert "question_taxonomy_link" not in source.lower()
    assert "QuestionImporter" not in source
    assert "ReviewWorkflow" not in source
    assert "ReviewService" not in source
    assert ".assign(" not in source


def test_real_model_excerpt_is_traceable_and_path_portable() -> None:
    fixture_path = ROOT / "tests" / "fixtures" / "tag_feedback" / "real_math_case054_model_excerpt.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["fixtureKind"] == "REAL_MODEL_RESULT_EXCERPT"
    assert len(fixture["sourceEvidence"]["sourceArtifactSha256"]) == 64
    assert fixture["suggestion"]["primary"]["confidence"] == 0.82
    assert fixture["suggestion"]["primary"]["candidateRank"] == 9
    serialized = json.dumps(fixture, ensure_ascii=False)
    assert "C:/Users/" not in serialized
    assert "C:\\\\Users\\\\" not in serialized
    assert "D:/Projects/" not in serialized
    assert "D:\\\\Projects\\\\" not in serialized


def test_g5_contract_and_historical_migrations_are_untouched_by_01a() -> None:
    migrations = sorted(MIGRATION.parent.glob("V*.sql"))
    assert migrations[-1].name == MIGRATION.name
    assert (ROOT / "config" / "canonical_import" / "canonical_content_import_v1.schema.json").exists()
    assert "canonical_import" not in MIGRATION.read_text(encoding="utf-8").lower().replace(
        "canonical_import_request", ""
    )
