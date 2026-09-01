package com.teachbase.server.review.api;

import java.time.OffsetDateTime;
import java.util.UUID;

/** Stable HTTP representation of review workflow state. */
public record ReviewCaseResponse(
        UUID reviewCaseId,
        UUID questionId,
        UUID questionRevisionId,
        String expectedContentHash,
        String status,
        UUID assignedTo,
        OffsetDateTime openedAt,
        OffsetDateTime decidedAt) {
}
