package com.teachbase.server.standardmodule.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** 中文维护说明：创建稳定模块身份及首个不可变修订的 HTTP 合同。 */
public record CreateStandardModuleRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 240) String moduleKey,
        @NotBlank @Size(max = 120) String moduleType,
        @NotBlank @Size(max = 512) String title,
        @NotBlank @Size(max = 80) String subject,
        @Size(max = 80) String stage,
        @Size(max = 80) String grade,
        @Positive int schemaVersion,
        @NotNull JsonNode content) {
}
