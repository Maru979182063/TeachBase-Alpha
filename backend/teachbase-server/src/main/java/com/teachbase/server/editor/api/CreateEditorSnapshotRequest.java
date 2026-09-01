package com.teachbase.server.editor.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.util.UUID;

/** Confirms and freezes one current revision, variant, and audience projection. */
public record CreateEditorSnapshotRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @Positive long expectedRevisionNo,
        @NotBlank String variantKey,
        @NotBlank String audience,
        int schemaVersion) {
}
