package com.teachbase.server.canonicalimport.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** 中文维护说明：Validate 保存不可变 package 与执行计划，但不得创建任何正式业务 revision。 */
public record ValidateCanonicalImportRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        String packageHash,
        @NotNull JsonNode contentPackage) {
}
