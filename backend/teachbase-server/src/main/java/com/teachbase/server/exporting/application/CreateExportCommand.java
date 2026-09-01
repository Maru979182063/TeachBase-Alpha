package com.teachbase.server.exporting.application;

import java.util.UUID;

/** Application command for workspace-scoped export admission. */
public record CreateExportCommand(
        UUID workspaceId,
        UUID actorUserId,
        UUID editorSnapshotId,
        String format,
        String idempotencyKey,
        UUID retryOfExportRequestId) {
}
