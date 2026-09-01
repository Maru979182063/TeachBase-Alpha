package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/** Stable node identifier pinned to one taxonomy version. */
public record TaxonomyNodeResponse(
        UUID taxonomyNodeId,
        UUID taxonomyVersionId,
        String knowledgeCode,
        String displayName) {
}
