package com.teachbase.server.standardmodule.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** 中文维护说明：将模块富内容引用绑定到精确 file version，而不是本机路径。 */
public record LinkStandardModuleFileRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotNull UUID fileVersionId,
        @NotBlank @Size(max = 160) String referenceKey,
        @NotBlank @Size(max = 40) String referenceRole,
        @NotNull JsonNode metadata) {
}
