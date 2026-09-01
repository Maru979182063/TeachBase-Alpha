package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** Recoverable checkpoint metadata and self-contained draft content. */
public record CollectionCheckpointResponse(
        UUID questionCollectionCheckpointId,
        long draftVersion,
        String checkpointKind,
        String contentHash,
        JsonNode content,
        OffsetDateTime createdAt,
        OffsetDateTime expiresAt) {
}
