package com.teachbase.server.taxonomy.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于知识体系版本模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Command that adds one coded node and its lookup aliases to a draft version.
 */
public record CreateTaxonomyNodeRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 240) String knowledgeCode,
        @NotBlank @Size(max = 512) String displayName,
        UUID parentNodeId,
        @Min(0) int sortOrder,
        @NotNull JsonNode metadata,
        @NotNull List<@NotBlank @Size(max = 512) String> aliases) {
}
