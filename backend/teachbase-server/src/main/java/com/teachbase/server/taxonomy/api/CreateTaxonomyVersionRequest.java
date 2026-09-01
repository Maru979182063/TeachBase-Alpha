package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** Command that starts a mutable draft of a stable taxonomy key. */
public record CreateTaxonomyVersionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 120) String taxonomyKey,
        @NotBlank @Size(max = 120) String versionKey,
        @NotBlank @Size(max = 80) String subject,
        @Size(max = 80) String stage,
        @Min(1) int schemaVersion) {
}
