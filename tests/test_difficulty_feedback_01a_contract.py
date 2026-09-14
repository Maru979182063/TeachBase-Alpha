from __future__ import annotations

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
    / "V012__teacher_difficulty_feedback_capture_core.sql"
)


def test_v012_is_additive_and_has_six_difficulty_tables() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    expected = {
        "difficulty_rubric_version",
        "difficulty_assessment_run",
        "question_difficulty_snapshot",
        "question_difficulty_feedback",
        "question_difficulty_state",
        "difficulty_rubric_gap_case",
    }
    assert all(f"create table teachbase_app.{table}" in sql for table in expected)
    assert "alter table teachbase_app.question_revision" not in sql
    assert "alter table teachbase_app.review_" not in sql
    assert "alter table teachbase_app.question_taxonomy_link" not in sql
    assert "reject_difficulty_feedback_fact_mutation" in sql


def test_module_has_no_question_review_or_legacy_difficulty_writer() -> None:
    module = JAVA_ROOT / "com" / "teachbase" / "server" / "difficultyfeedback"
    source = "\n".join(path.read_text(encoding="utf-8") for path in module.rglob("*.java"))
    assert "QuestionRevisionDirectory" in source
    assert "difficulty_stars" not in source.lower()
    assert "QuestionImporter" not in source
    assert "ReviewWorkflow" not in source
    assert "ReviewService" not in source


def test_current_authority_and_context_dimension_are_explicit() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "current_snapshot_id uuid not null" in sql
    assert "state_version bigint not null" in sql
    assert "workspace_id, question_revision_id, rubric_key, context_key" in sql
    assert "client_mutation_id" in sql
    assert "rubric_gap" in sql
