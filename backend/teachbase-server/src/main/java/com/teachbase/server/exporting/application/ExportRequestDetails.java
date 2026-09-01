package com.teachbase.server.exporting.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** Complete application read model for export status and output metadata. */
public record ExportRequestDetails(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        String format,
        String status,
        int attemptCount,
        int maxAttempts,
        String rendererProfile,
        String rendererVersion,
        JsonNode error,
        OffsetDateTime requestedAt,
        OffsetDateTime completedAt,
        UUID fileVersionId,
        String storageKey,
        String mediaType,
        Long sizeBytes,
        String sha256) {
}
