package com.teachbase.server.handout.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：统一 occurrence 输入；kind 决定精确资产引用或 ordinary local content。 */
public record HandoutOccurrenceInput(
        @NotBlank @Size(max = 240) String occurrenceKey,
        @Size(max = 240) String parentOccurrenceKey,
        @PositiveOrZero int positionIndex,
        @NotBlank @Size(max = 32) String kind,
        UUID questionRevisionId,
        UUID standardModuleRevisionId,
        JsonNode localContent,
        @NotNull JsonNode attributes,
        @NotNull List<@Valid HandoutOccurrenceSourceInput> sources) {
}
