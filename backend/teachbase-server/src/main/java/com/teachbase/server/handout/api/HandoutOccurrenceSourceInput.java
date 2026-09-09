package com.teachbase.server.handout.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.UUID;

/** 中文维护说明：一次讲义落位的来源证据，独立于题目或模块的 canonical provenance。 */
public record HandoutOccurrenceSourceInput(
        @NotBlank @Size(max = 160) String sourceEvidenceKey,
        @NotNull UUID sourceDocumentId,
        UUID sourceRegionId,
        @NotBlank @Size(max = 40) String sourceRole,
        @NotNull JsonNode sourceReference) {
}
