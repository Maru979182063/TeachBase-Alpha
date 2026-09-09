package com.teachbase.server.standardmodule.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.UUID;

/** 中文维护说明：标准模块精确修订的稳定响应，不提供 latest 隐式解析。 */
public record StandardModuleResponse(
        UUID standardModuleId,
        UUID standardModuleRevisionId,
        UUID workspaceId,
        String moduleKey,
        String moduleType,
        long revisionNo,
        String reviewStatus,
        String title,
        String subject,
        String stage,
        String grade,
        int schemaVersion,
        JsonNode content,
        String contentHash,
        OffsetDateTime createdAt,
        boolean createdModule,
        boolean createdRevision) {
}
