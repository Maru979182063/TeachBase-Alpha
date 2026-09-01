package com.teachbase.server.exporting.application;

import java.util.UUID;

/** Leased queue item containing the worker ownership and attempt identity. */
public record ExportWorkItem(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        UUID requestedBy,
        String format,
        int attemptNo,
        int maxAttempts,
        String workerId) {
}
