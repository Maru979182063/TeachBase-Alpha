package com.teachbase.server.collection.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** Creates an empty question basket at draft version zero. */
public record CreateCollectionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 512) String name) {
}
