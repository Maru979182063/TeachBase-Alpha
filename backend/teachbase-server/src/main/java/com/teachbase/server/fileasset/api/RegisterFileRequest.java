package com.teachbase.server.fileasset.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** Client-supplied metadata for bytes already written through an approved storage adapter. */
public record RegisterFileRequest(
        @NotNull UUID workspaceId,
        UUID actorUserId,
        @NotBlank @Size(max = 512) String originalFilename,
        @NotBlank String storageProvider,
        @NotBlank @Size(max = 1024) String storageKey,
        @NotBlank @Size(max = 255) String mediaType,
        @PositiveOrZero long sizeBytes,
        @NotBlank String sha256) {
}
