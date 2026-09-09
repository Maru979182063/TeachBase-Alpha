package com.teachbase.server.review.api;

import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** 中文维护说明：为精确标准模块修订开启审核，不能用模块稳定 ID 替代 revision ID。 */
public record OpenStandardModuleReviewCaseRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID standardModuleRevisionId,
        UUID assignedTo) {
}
