package com.teachbase.server.standardmodule.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.standardmodule.api.StandardModuleLinkResponse;
import com.teachbase.server.standardmodule.api.StandardModuleResponse;
import java.util.UUID;

/** 中文维护说明：模块身份、不可变修订和证据关系的持久化端口。 */
public interface StandardModuleRepository {
    StandardModuleResponse create(StandardModuleRevisionInput input);

    StandardModuleResponse revise(UUID standardModuleId, StandardModuleRevisionInput input);

    StandardModuleLinkResponse linkSource(
            UUID workspaceId, UUID standardModuleRevisionId, String evidenceKey,
            UUID sourceDocumentId, UUID sourceRegionId, String sourceRole, JsonNode sourceReference);

    StandardModuleLinkResponse linkFile(
            UUID workspaceId, UUID standardModuleRevisionId, UUID fileVersionId,
            String referenceKey, String referenceRole, JsonNode metadata);

    long usageCount(UUID workspaceId, UUID standardModuleRevisionId);
}
