package com.teachbase.server.collection.application;

import com.teachbase.server.collection.api.CollectionItemResponse;
import java.util.List;
import java.util.UUID;

/** Application representation of the current ordered collection draft. */
public record CollectionDraft(
        UUID questionCollectionId,
        UUID workspaceId,
        String name,
        String status,
        long draftVersion,
        List<CollectionItemResponse> items) {
}
