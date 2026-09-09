package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** 中文维护说明：内部 request ledger 快照，package identity 字段不可修改。 */
public record ImportRequestRecord(
        UUID importRequestId,
        UUID workspaceId,
        UUID actorUserId,
        String producer,
        String contractVersion,
        String packageKey,
        String packageHash,
        JsonNode canonicalPackage,
        String status,
        int operationCount,
        int completedOperationCount,
        UUID workerToken,
        int attemptNo,
        JsonNode failureSummary,
        String resultFingerprint,
        OffsetDateTime createdAt,
        OffsetDateTime startedAt,
        OffsetDateTime completedAt) {
}
