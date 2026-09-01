package com.teachbase.server.exporting.application;

import java.util.UUID;

/** Minimal admission result used to build HTTP 200/201 semantics. */
public record ExportRequestState(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        String format,
        String status,
        String idempotencyKey,
        UUID retryOfExportRequestId,
        boolean created) {
}
