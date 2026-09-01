package com.teachbase.server.taxonomy.api;

import java.util.UUID;

/** Identifier returned after an idempotent question-to-node assignment. */
public record QuestionTaxonomyLinkResponse(
        UUID questionTaxonomyLinkId,
        UUID questionRevisionId,
        UUID taxonomyNodeId,
        String relationType) {
}
