package com.teachbase.server.review.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;

/** Persistence port for idempotent case opening and serialized decisions. */
public interface ReviewRepository {

    ReviewCaseRecord open(
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String expectedContentHash,
            UUID assignedTo,
            UUID openedBy);

    Optional<ReviewCaseRecord> lockOpen(UUID workspaceId, UUID reviewCaseId);

    ReviewCaseRecord complete(
            ReviewCaseRecord reviewCase,
            UUID actorUserId,
            String decision,
            String note,
            String policyVersion,
            String decisionSource,
            JsonNode evidence,
            OffsetDateTime evidenceOccurredAt);
}
