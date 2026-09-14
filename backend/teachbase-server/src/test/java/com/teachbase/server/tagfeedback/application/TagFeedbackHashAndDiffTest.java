package com.teachbase.server.tagfeedback.application;

import static com.teachbase.server.tagfeedback.application.TagFeedbackHasher.SnapshotItemValue;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/**
 * 双 hash 与自动 diff 的纯函数回归，失败时不需要数据库即可定位 canonicalization 问题。
 */
class TagFeedbackHashAndDiffTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private final TagFeedbackHasher hasher = new TagFeedbackHasher(mapper);

    @Test
    void labelSetHashIgnoresSecondaryOrderAndJsonFormatting() throws Exception {
        UUID version = UUID.fromString("10000000-0000-0000-0000-000000000001");
        UUID primary = UUID.fromString("20000000-0000-0000-0000-000000000001");
        UUID b = UUID.fromString("30000000-0000-0000-0000-000000000001");
        UUID c = UUID.fromString("40000000-0000-0000-0000-000000000001");

        assertThat(hasher.labelSetHash(version, primary, List.of(b, c)))
                .isEqualTo(hasher.labelSetHash(version, primary, List.of(c, b)));
        assertThat(hasher.canonical(mapper.readTree("{\"score\":0.820,\"a\":1}")))
                .isEqualTo(hasher.canonical(mapper.readTree("{ \"a\":1.0, \"score\":0.82 }")));
    }

    @Test
    void snapshotHashFreezesRunConfidenceAndRank() throws Exception {
        UUID actor = UUID.fromString("50000000-0000-0000-0000-000000000001");
        UUID node = UUID.fromString("60000000-0000-0000-0000-000000000001");
        UUID runA = UUID.fromString("70000000-0000-0000-0000-000000000001");
        UUID runB = UUID.fromString("70000000-0000-0000-0000-000000000002");
        String labels = "a".repeat(64);
        var context = mapper.readTree("{\"schema\":\"real-model-v1\"}");
        String first = hasher.snapshotHash("SYSTEM_SUGGESTION", labels, runA, actor, context,
                List.of(new SnapshotItemValue(node, "primary", 0, new BigDecimal("0.62"), 1)));
        String confidenceChanged = hasher.snapshotHash("SYSTEM_SUGGESTION", labels, runA, actor, context,
                List.of(new SnapshotItemValue(node, "primary", 0, new BigDecimal("0.91"), 1)));
        String runChanged = hasher.snapshotHash("SYSTEM_SUGGESTION", labels, runB, actor, context,
                List.of(new SnapshotItemValue(node, "primary", 0, new BigDecimal("0.62"), 1)));

        assertThat(first).isNotEqualTo(confidenceChanged).isNotEqualTo(runChanged);
    }

    @Test
    void goldenDiffIsDeterministicAndConfirmationIsExplicit() {
        UUID a = UUID.fromString("80000000-0000-0000-0000-000000000001");
        UUID b = UUID.fromString("80000000-0000-0000-0000-000000000002");
        UUID c = UUID.fromString("80000000-0000-0000-0000-000000000003");
        UUID d = UUID.fromString("80000000-0000-0000-0000-000000000004");
        var calculator = new TagFeedbackDiff();
        var before = new TagFeedbackDiff.LabelSet(a, Set.of(b, c));
        var after = new TagFeedbackDiff.LabelSet(b, Set.of(c, d));

        assertThat(calculator.derive(before, after).stream().map(value -> value.code()).toList())
                .containsExactly("PRIMARY_CHANGED", "PRIMARY_SECONDARY_SWAP", "SECONDARY_ADDED");
        assertThat(calculator.derive(after, after).getFirst().code())
                .isEqualTo("UNCHANGED_CONFIRMED");
    }
}
