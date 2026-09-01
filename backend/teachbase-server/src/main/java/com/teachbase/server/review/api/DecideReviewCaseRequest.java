package com.teachbase.server.review.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.OffsetDateTime;
import java.util.UUID;

/** Optimistic command for one terminal human review decision. */
public record DecideReviewCaseRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank String expectedContentHash,
        @NotBlank String decision,
        @Size(max = 10000) String note,
        @NotBlank @Size(max = 120) String policyVersion,
        @NotBlank @Size(max = 40) String decisionSource,
        @NotNull JsonNode evidence,
        OffsetDateTime evidenceOccurredAt) {
}
