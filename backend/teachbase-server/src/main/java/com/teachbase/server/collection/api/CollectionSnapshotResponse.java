package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Immutable basket snapshot descriptor suitable for publication or downstream export. */
public record CollectionSnapshotResponse(
        UUID questionCollectionSnapshotId,
        UUID questionCollectionId,
        long sourceDraftVersion,
        String contentHash,
        JsonNode frozenContent) {
}
