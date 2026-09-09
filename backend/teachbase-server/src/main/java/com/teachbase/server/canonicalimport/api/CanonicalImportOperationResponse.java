package com.teachbase.server.canonicalimport.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** 中文维护说明：operation 状态保留稳定 key、目标 ID/hash、attempt 和结构化错误。 */
public record CanonicalImportOperationResponse(
        String operationKey,
        String operationType,
        int sequenceNo,
        JsonNode dependencies,
        String status,
        int attemptNo,
        UUID targetId,
        UUID targetRevisionId,
        String targetHash,
        JsonNode result,
        JsonNode error,
        OffsetDateTime startedAt,
        OffsetDateTime completedAt) {
}
