package com.teachbase.server.taxonomy.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/** Command that adds one coded node and its lookup aliases to a draft version. */
public record CreateTaxonomyNodeRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 240) String knowledgeCode,
        @NotBlank @Size(max = 512) String displayName,
        UUID parentNodeId,
        @Min(0) int sortOrder,
        @NotNull JsonNode metadata,
        @NotNull List<@NotBlank @Size(max = 512) String> aliases) {
}
