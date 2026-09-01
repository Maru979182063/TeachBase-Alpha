package com.teachbase.server.fileasset.application;

import java.util.UUID;

/** Application result describing the winning or previously existing file version. */
public record FileRegistration(
        UUID fileAssetId,
        UUID fileVersionId,
        UUID workspaceId,
        String originalFilename,
        String storageProvider,
        String storageKey,
        String mediaType,
        long sizeBytes,
        String sha256,
        boolean created) {
}
