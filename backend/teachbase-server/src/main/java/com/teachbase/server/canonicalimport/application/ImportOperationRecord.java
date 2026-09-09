package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** 中文维护说明：内部 operation ledger 快照及其精确 target。 */
public record ImportOperationRecord(
        UUID importOperationId,
        UUID importRequestId,
        String operationKey,
        String operationType,
        int sequenceNo,
        JsonNode dependencies,
        JsonNode payload,
        String payloadHash,
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
