package com.teachbase.server.standardmodule.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** 中文维护说明：为模块修订追加规范来源证据；evidence key 是修订内的幂等键。 */
public record LinkStandardModuleSourceRequest(
        @NotNull UUID workspaceId,
        @NotNull UUID actorUserId,
        @NotBlank @Size(max = 160) String sourceEvidenceKey,
        UUID sourceDocumentId,
        UUID sourceRegionId,
        @NotBlank @Size(max = 40) String sourceRole,
        @NotNull JsonNode sourceReference) {
}
