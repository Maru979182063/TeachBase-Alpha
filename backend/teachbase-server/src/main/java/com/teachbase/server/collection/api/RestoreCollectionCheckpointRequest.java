package com.teachbase.server.collection.api;

import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** Restores checkpoint content as a new draft version; history is never rewound in place. */
public record RestoreCollectionCheckpointRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        long expectedDraftVersion) {
}
