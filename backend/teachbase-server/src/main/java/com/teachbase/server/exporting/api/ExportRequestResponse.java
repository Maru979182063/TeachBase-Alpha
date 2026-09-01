package com.teachbase.server.exporting.api;

import com.teachbase.server.exporting.application.ExportRequestState;
import java.util.UUID;

/** Admission response distinguishing a new request from an idempotent replay. */
public record ExportRequestResponse(
        UUID exportRequestId,
        UUID workspaceId,
        UUID editorSnapshotId,
        String format,
        String status,
        String idempotencyKey,
        UUID retryOfExportRequestId,
        boolean created) {

    static ExportRequestResponse from(ExportRequestState state) {
        return new ExportRequestResponse(
                state.exportRequestId(), state.workspaceId(), state.editorSnapshotId(), state.format(),
                state.status(), state.idempotencyKey(), state.retryOfExportRequestId(), state.created());
    }
}
