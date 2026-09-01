package com.teachbase.server.fileasset.application;

import java.util.UUID;

/** Normalized application command after filename, key, and checksum validation. */
public record RegisterFileCommand(
        UUID workspaceId,
        UUID actorUserId,
        String originalFilename,
        String storageProvider,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256) {
}
