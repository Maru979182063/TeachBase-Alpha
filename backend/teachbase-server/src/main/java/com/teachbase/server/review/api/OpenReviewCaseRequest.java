package com.teachbase.server.review.api;

import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** Request to freeze a question revision into an explicit review case. */
public record OpenReviewCaseRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID questionRevisionId,
        UUID assignedTo) {
}
