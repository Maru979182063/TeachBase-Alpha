package com.teachbase.server.collection.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Frozen collection result returned from persistence. */
public record CollectionSnapshot(
        UUID snapshotId,
        UUID collectionId,
        long sourceDraftVersion,
        String contentHash,
        JsonNode frozenContent) {
}
