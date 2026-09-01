package com.teachbase.server.collection.api;

import java.util.List;
import java.util.UUID;

/** Current mutable basket projection and its optimistic-lock version. */
public record CollectionDraftResponse(
        UUID questionCollectionId,
        UUID workspaceId,
        String name,
        String status,
        long draftVersion,
        List<CollectionItemResponse> items) {
}
