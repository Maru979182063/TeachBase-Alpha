package com.teachbase.server.canonicalimport.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：返回 request ledger 与 operation 细节，供恢复、审计和 UI 状态展示。 */
public record CanonicalImportStatusResponse(
        UUID importRequestId,
        UUID workspaceId,
        String producer,
        String contractVersion,
        String packageKey,
        String packageHash,
        String status,
        int operationCount,
        int completedOperationCount,
        int attemptNo,
        String resultFingerprint,
        JsonNode failureSummary,
        OffsetDateTime createdAt,
        OffsetDateTime startedAt,
        OffsetDateTime completedAt,
        boolean replayed,
        List<CanonicalImportOperationResponse> operations) {
}
