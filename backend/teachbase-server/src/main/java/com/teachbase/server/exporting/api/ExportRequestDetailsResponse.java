package com.teachbase.server.exporting.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.exporting.application.ExportRequestDetails;
import java.time.OffsetDateTime;
import java.util.UUID;

/** Queue, attempt, failure, and generated-file status visible to API clients. */
public record ExportRequestDetailsResponse(
        UUID exportRequestId,
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
        ExportedFileResponse file) {

    static ExportRequestDetailsResponse from(ExportRequestDetails details) {
        ExportedFileResponse file = details.fileVersionId() == null ? null : new ExportedFileResponse(
                details.fileVersionId(), details.storageKey(), details.mediaType(), details.sizeBytes(), details.sha256());
        return new ExportRequestDetailsResponse(
                details.exportRequestId(), details.editorSnapshotId(), details.format(), details.status(),
                details.attemptCount(), details.maxAttempts(), details.rendererProfile(), details.rendererVersion(),
                details.error(), details.requestedAt(), details.completedAt(), file);
    }

    public record ExportedFileResponse(
            UUID fileVersionId,
            String storageKey,
            String mediaType,
            Long sizeBytes,
            String sha256) {
    }
}
