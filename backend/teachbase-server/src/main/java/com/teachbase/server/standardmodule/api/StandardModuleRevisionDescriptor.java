package com.teachbase.server.standardmodule.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** 中文维护说明：供 Review、taxonomy 和 handout 使用的最小精确修订视图。 */
public record StandardModuleRevisionDescriptor(
        UUID standardModuleId,
        UUID standardModuleRevisionId,
        UUID workspaceId,
        String moduleKey,
        String moduleType,
        long revisionNo,
        String reviewStatus,
        JsonNode content,
        String contentHash) {
}
