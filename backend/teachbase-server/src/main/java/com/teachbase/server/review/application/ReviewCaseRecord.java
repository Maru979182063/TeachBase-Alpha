package com.teachbase.server.review.application;

import java.time.OffsetDateTime;
import java.util.UUID;

/** Persistence-neutral view of one review case. */
public record ReviewCaseRecord(
        UUID reviewCaseId,
        UUID workspaceId,
        UUID questionId,
        UUID questionRevisionId,
        String expectedContentHash,
        String status,
        UUID assignedTo,
        OffsetDateTime openedAt,
        OffsetDateTime decidedAt) {
}
