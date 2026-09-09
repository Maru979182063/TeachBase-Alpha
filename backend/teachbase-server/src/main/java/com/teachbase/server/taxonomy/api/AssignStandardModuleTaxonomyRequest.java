package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.util.UUID;

/** 中文维护说明：将精确标准模块修订关联到精确 taxonomy node/version。 */
public record AssignStandardModuleTaxonomyRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID standardModuleRevisionId,
        @NotNull UUID taxonomyNodeId,
        @NotBlank String relationType,
        @NotBlank String assignmentSource,
        @DecimalMin("0.0") @DecimalMax("1.0") BigDecimal confidence) {
}
