package com.teachbase.server.standardmodule.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** 中文维护说明：为既有模块追加不可变内容修订；相同内容哈希会复用已有修订。 */
public record CreateStandardModuleRevisionRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 512) String title,
        @NotBlank @Size(max = 80) String subject,
        @Size(max = 80) String stage,
        @Size(max = 80) String grade,
        @Positive int schemaVersion,
        @NotNull JsonNode content) {
}
