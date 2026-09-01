package com.teachbase.server.collection.api;

import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** Freezes the exact draft version and all referenced question packets. */
public record CreateCollectionSnapshotRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        long expectedDraftVersion) {
}
