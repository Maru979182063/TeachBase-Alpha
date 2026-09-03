package com.teachbase.server.taxonomy.api;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于知识体系版本模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Command that starts a mutable draft of a stable taxonomy key.
 */
public record CreateTaxonomyVersionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 120) String taxonomyKey,
        @NotBlank @Size(max = 120) String versionKey,
        @NotBlank @Size(max = 80) String subject,
        @Size(max = 80) String stage,
        @Min(1) int schemaVersion) {
}
