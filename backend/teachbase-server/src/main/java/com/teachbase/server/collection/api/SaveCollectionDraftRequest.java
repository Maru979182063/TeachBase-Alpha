package com.teachbase.server.collection.api;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/** Replaces the ordered draft atomically and records an autosave or manual checkpoint. */
public record SaveCollectionDraftRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        long expectedDraftVersion,
        @NotNull String checkpointKind,
        @NotNull @Size(max = 1000) List<@Valid CollectionItemRequest> items) {
}
