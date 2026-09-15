from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "backend/teachbase-server/src/main/resources/db/migration/V013__governance_current_projection.sql"
MODULE = ROOT / "backend/teachbase-server/src/main/java/com/teachbase/server/governanceprojection"


def test_v013_is_additive_and_keeps_authority_separate():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table teachbase_app.question_tag_current_projection" in sql
    assert "create table teachbase_app.question_difficulty_current_projection" in sql
    assert "create table teachbase_app.governance_projection_outbox" in sql
    assert "trg_question_tag_state_projection_outbox" in sql
    assert "trg_question_difficulty_state_projection_outbox" in sql
    assert "alter table teachbase_app.question_tag_state" not in sql
    assert "alter table teachbase_app.question_difficulty_state" not in sql
    assert "alter table teachbase_app.question_revision" not in sql
    assert "drop table" not in sql


def test_projection_code_does_not_write_fact_or_legacy_tables():
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in MODULE.rglob("*.java")
    ).lower()
    forbidden_writes = (
        "insertinto(question_tag_state",
        "update(question_tag_state",
        "insertinto(question_difficulty_state",
        "update(question_difficulty_state",
        "insertinto(question_revision",
        "update(question_revision",
        "insertinto(question_tag_feedback",
        "insertinto(question_difficulty_feedback",
    )
    compact = "".join(source.split())
    assert all(pattern not in compact for pattern in forbidden_writes)
    assert "difficulty_stars" not in source
    assert "primary_knowledge_tag" not in source
    assert "question_taxonomy_link" not in source


def test_scope_keeps_unified_search_and_tag_rule_open():
    audit = (ROOT / "docs/audits/governance_projection_design_audit.md").read_text(encoding="utf-8")
    contract = (ROOT / "docs/backend/governance-projection-01-domain-contract.md").read_text(encoding="utf-8")
    combined = audit + contract
    assert "BLOCKS_TAG_SCHEMA_AND_SEARCH" in combined
    assert "保持 OPEN" in combined
    assert "unified" in combined.lower()
    assert "Projection 是" in contract
