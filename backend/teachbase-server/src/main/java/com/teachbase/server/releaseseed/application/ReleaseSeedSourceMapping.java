package com.teachbase.server.releaseseed.application;

import java.util.UUID;

/** Durable package source key mapping used across interrupted loader attempts. */
public record ReleaseSeedSourceMapping(
        String sourceKey,
        UUID sourceDocumentId,
        UUID sourceRegionId,
        UUID fileVersionId) {
}
