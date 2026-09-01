package com.teachbase.server.fileasset.api;

import java.util.UUID;

/** Internal registration command for finalized bytes produced by a backend worker. */
public record GeneratedFileCommand(
        UUID workspaceId,
        UUID actorUserId,
        String originalFilename,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256) {
}
