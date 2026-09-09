package com.teachbase.server.handout.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** 中文维护说明：原件、manifest、保真包和 roundtrip 输出的精确 file version 引用。 */
public record EditorRevisionArtifactInput(
        @NotBlank @Size(max = 160) String artifactKey,
        @NotBlank @Size(max = 40) String artifactRole,
        @NotNull UUID fileVersionId,
        UUID sourceDocumentId,
        @NotNull JsonNode metadata) {
}
