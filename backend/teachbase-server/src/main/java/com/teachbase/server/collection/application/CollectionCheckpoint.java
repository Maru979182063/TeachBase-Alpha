package com.teachbase.server.collection.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** Stored recoverable draft checkpoint. */
public record CollectionCheckpoint(
        UUID checkpointId,
        long draftVersion,
        String checkpointKind,
        String contentHash,
        JsonNode content,
        OffsetDateTime createdAt,
        OffsetDateTime expiresAt) {
}
