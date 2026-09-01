package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** Tenant-scoped command that atomically promotes one draft taxonomy version. */
public record ActivateTaxonomyVersionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId) {
}
