package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.util.UUID;

/** Version-pinned knowledge assignment for one immutable question revision. */
public record AssignQuestionTaxonomyRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID questionRevisionId,
        @NotNull UUID taxonomyNodeId,
        @NotBlank String relationType,
        @NotBlank String assignmentSource,
        @DecimalMin("0.0") @DecimalMax("1.0") BigDecimal confidence) {
}
