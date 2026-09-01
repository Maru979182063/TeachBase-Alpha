package com.teachbase.server.exporting.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** Idempotent request to render one immutable editor snapshot into a supported format. */
public record CreateExportRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID editorSnapshotId,
        @NotBlank String format,
        @NotBlank @Size(max = 128) String idempotencyKey,
        UUID retryOfExportRequestId) {
}
