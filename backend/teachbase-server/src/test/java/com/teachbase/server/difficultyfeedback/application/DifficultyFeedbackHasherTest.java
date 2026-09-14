package com.teachbase.server.difficultyfeedback.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/** 中文维护说明：难度上下文、模型运行和置信度必须进入冻结快照 hash。 */
class DifficultyFeedbackHasherTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private final DifficultyFeedbackHasher hasher = new DifficultyFeedbackHasher(mapper);

    @Test
    void canonicalContextIgnoresObjectOrderAndNumericFormatting() throws Exception {
        assertThat(hasher.contextHash(mapper.readTree("{\"grade\":10,\"weight\":1.0}")))
                .isEqualTo(hasher.contextHash(mapper.readTree("{\"weight\":1.00,\"grade\":10}")));
    }

    @Test
    void snapshotHashFreezesRunScoreAndConfidence() throws Exception {
        UUID rubric = UUID.fromString("10000000-0000-0000-0000-000000000001");
        UUID actor = UUID.fromString("20000000-0000-0000-0000-000000000001");
        UUID runA = UUID.fromString("30000000-0000-0000-0000-000000000001");
        UUID runB = UUID.fromString("30000000-0000-0000-0000-000000000002");
        String contextHash = "a".repeat(64);
        var modelContext = mapper.readTree("{\"schemaVersion\":1}");
        String first = hasher.snapshotHash("SYSTEM_SUGGESTION", rubric, "grade-10", contextHash,
                3, new BigDecimal("0.72"), runA, actor, modelContext);
        String runChanged = hasher.snapshotHash("SYSTEM_SUGGESTION", rubric, "grade-10", contextHash,
                3, new BigDecimal("0.72"), runB, actor, modelContext);
        String scoreChanged = hasher.snapshotHash("SYSTEM_SUGGESTION", rubric, "grade-10", contextHash,
                4, new BigDecimal("0.72"), runA, actor, modelContext);
        String confidenceChanged = hasher.snapshotHash("SYSTEM_SUGGESTION", rubric, "grade-10", contextHash,
                3, new BigDecimal("0.91"), runA, actor, modelContext);

        assertThat(first).isNotEqualTo(runChanged).isNotEqualTo(scoreChanged).isNotEqualTo(confidenceChanged);
    }
}
