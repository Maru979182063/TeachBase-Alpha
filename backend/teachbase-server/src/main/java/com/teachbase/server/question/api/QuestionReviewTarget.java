package com.teachbase.server.question.api;

import java.util.UUID;

/** Immutable question revision facts exposed to the review module. */
public record QuestionReviewTarget(
        UUID questionId,
        UUID questionRevisionId,
        String reviewStatus,
        String contentHash) {
}
