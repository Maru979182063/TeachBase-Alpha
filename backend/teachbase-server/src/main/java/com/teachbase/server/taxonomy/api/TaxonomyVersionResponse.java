package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/** Stable identifier and lifecycle state returned for a taxonomy version. */
public record TaxonomyVersionResponse(
        UUID taxonomyVersionId,
        String taxonomyKey,
        String versionKey,
        String status) {
}
