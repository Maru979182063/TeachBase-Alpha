package com.teachbase.server.question.api;

import java.util.Optional;
import java.util.UUID;

/** Public question port through which the review module applies terminal decisions. */
public interface QuestionReviewGateway {

    Optional<QuestionReviewTarget> findTarget(UUID workspaceId, UUID questionRevisionId);

    void applyDecision(
            UUID workspaceId,
            UUID actorUserId,
            UUID questionRevisionId,
            String expectedContentHash,
            String decision);
}
