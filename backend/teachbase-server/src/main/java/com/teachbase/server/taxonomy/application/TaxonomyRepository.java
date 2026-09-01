package com.teachbase.server.taxonomy.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.taxonomy.api.QuestionTaxonomyLinkResponse;
import com.teachbase.server.taxonomy.api.TaxonomyNodeResponse;
import com.teachbase.server.taxonomy.api.TaxonomyVersionResponse;
import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** Persistence port for taxonomy lifecycle and immutable revision assignments. */
public interface TaxonomyRepository {

    TaxonomyVersionResponse createVersion(
            UUID workspaceId, UUID actorUserId, String taxonomyKey, String versionKey,
            String subject, String stage, int schemaVersion);

    TaxonomyNodeResponse createNode(
            UUID workspaceId, UUID actorUserId, UUID taxonomyVersionId, String knowledgeCode,
            String displayName, UUID parentNodeId, int sortOrder, JsonNode metadata, List<String> aliases);

    TaxonomyVersionResponse activate(UUID workspaceId, UUID actorUserId, UUID taxonomyVersionId);

    Optional<TaxonomyNodeResponse> resolve(UUID workspaceId, UUID taxonomyVersionId, String codeOrAlias);

    QuestionTaxonomyLinkResponse assign(
            UUID workspaceId, UUID actorUserId, UUID questionId, UUID questionRevisionId,
            UUID taxonomyNodeId, String relationType, String assignmentSource, BigDecimal confidence);
}
