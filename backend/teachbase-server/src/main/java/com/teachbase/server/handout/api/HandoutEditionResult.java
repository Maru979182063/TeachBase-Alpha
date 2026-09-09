package com.teachbase.server.handout.api;

import java.util.UUID;

/** 中文维护说明：一次 edition composition 的精确持久化结果。 */
public record HandoutEditionResult(
        UUID handoutEditionId,
        UUID handoutEditionRevisionId,
        String editionKey,
        String editionRole,
        UUID canonicalTeacherRevisionId,
        String contentHash,
        int occurrenceCount,
        int sourceEvidenceCount,
        boolean replayed) {
}
