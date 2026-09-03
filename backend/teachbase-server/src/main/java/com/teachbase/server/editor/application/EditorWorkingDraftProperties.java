package com.teachbase.server.editor.application;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 中文维护说明：WP-01 的切换和保留参数集中在此，便于灰度、回滚与环境审计；默认值对应 ADR-01 的冻结策略。
 *
 * 英文术语对照：Feature switch and retention policy for working drafts.
 */
@ConfigurationProperties("teachbase.editor.working-draft")
public record EditorWorkingDraftProperties(
        boolean enabled,
        boolean lazyMigrationEnabled,
        Duration checkpointInterval,
        Duration checkpointTtl,
        Integer checkpointMaxPerDocument,
        Duration mutationTtl,
        Integer cleanupBatchSize) {

    public Duration effectiveCheckpointInterval() {
        return checkpointInterval == null ? Duration.ofMinutes(2) : checkpointInterval;
    }

    public Duration effectiveCheckpointTtl() {
        return checkpointTtl == null ? Duration.ofHours(72) : checkpointTtl;
    }

    public int effectiveCheckpointMaxPerDocument() {
        return checkpointMaxPerDocument == null ? 100 : checkpointMaxPerDocument;
    }

    public Duration effectiveMutationTtl() {
        return mutationTtl == null ? Duration.ofDays(7) : mutationTtl;
    }

    public int effectiveCleanupBatchSize() {
        return cleanupBatchSize == null ? 5000 : cleanupBatchSize;
    }
}
