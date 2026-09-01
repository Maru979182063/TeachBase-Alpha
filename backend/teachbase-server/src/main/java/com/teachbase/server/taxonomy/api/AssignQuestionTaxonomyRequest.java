package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Version-pinned knowledge assignment for one immutable question revision.
 */
public record AssignQuestionTaxonomyRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID questionRevisionId,
        @NotNull UUID taxonomyNodeId,
        @NotBlank String relationType,
        @NotBlank String assignmentSource,
        @DecimalMin("0.0") @DecimalMax("1.0") BigDecimal confidence) {
}
