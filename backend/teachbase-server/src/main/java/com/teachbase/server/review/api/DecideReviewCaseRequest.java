package com.teachbase.server.review.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Optimistic command for one terminal human review decision.
 */
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
