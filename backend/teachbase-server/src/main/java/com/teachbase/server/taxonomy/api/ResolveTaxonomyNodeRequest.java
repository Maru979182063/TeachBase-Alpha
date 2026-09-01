package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** Explicit-version code or alias lookup used by deterministic ingestion adapters. */
public record ResolveTaxonomyNodeRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID taxonomyVersionId,
        @NotBlank @Size(max = 512) String codeOrAlias) {
}
