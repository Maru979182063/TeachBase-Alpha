package com.teachbase.server.governanceprojection.application;

import static com.teachbase.server.governanceprojection.application.GovernanceProjectionHasher.*;
import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/** 中文维护说明：semantic hash 必须稳定覆盖 authority 内容，同时排除投影时间。 */
class GovernanceProjectionHasherTest {

    @Test
    void tagHashChangesWithAuthorityVersionOrSecondaryOrder() {
        UUID state = UUID.randomUUID();
        UUID workspace = UUID.randomUUID();
        UUID question = UUID.randomUUID();
        UUID revision = UUID.randomUUID();
        UUID taxonomy = UUID.randomUUID();
        UUID snapshot = UUID.randomUUID();
        UUID primary = UUID.randomUUID();
        UUID secondaryA = UUID.randomUUID();
        UUID secondaryB = UUID.randomUUID();
        TagAuthority base = new TagAuthority(
                state, workspace, question, revision, "knowledge", taxonomy, snapshot, primary,
                List.of(secondaryA, secondaryB), "HUMAN_FINAL", "reviewed", 6, "a".repeat(64));
        TagAuthority reordered = new TagAuthority(
                state, workspace, question, revision, "knowledge", taxonomy, snapshot, primary,
                List.of(secondaryB, secondaryA), "HUMAN_FINAL", "reviewed", 6, "a".repeat(64));
        TagAuthority newer = new TagAuthority(
                state, workspace, question, revision, "knowledge", taxonomy, snapshot, primary,
                List.of(secondaryA, secondaryB), "HUMAN_FINAL", "reviewed", 7, "a".repeat(64));

        assertThat(tagHash(base)).hasSize(64).isNotEqualTo(tagHash(reordered)).isNotEqualTo(tagHash(newer));
        assertThat(stableProjectionId("TAG", workspace, revision, "knowledge"))
                .isEqualTo(stableProjectionId("TAG", workspace, revision, "knowledge"));
    }

    @Test
    void difficultyHashPreservesContextAndNullableGap() {
        UUID state = UUID.randomUUID();
        UUID workspace = UUID.randomUUID();
        UUID question = UUID.randomUUID();
        UUID revision = UUID.randomUUID();
        UUID rubric = UUID.randomUUID();
        UUID snapshot = UUID.randomUUID();
        DifficultyAuthority score = new DifficultyAuthority(
                state, workspace, question, revision, "five-star", rubric, "default", "b".repeat(64),
                snapshot, 4, "HUMAN_FINAL", "reviewed", 3);
        DifficultyAuthority gap = new DifficultyAuthority(
                state, workspace, question, revision, "five-star", rubric, "default", "b".repeat(64),
                snapshot, null, "HUMAN_FINAL", "rubric_gap", 4);

        assertThat(difficultyHash(score)).hasSize(64).isNotEqualTo(difficultyHash(gap));
    }
}
