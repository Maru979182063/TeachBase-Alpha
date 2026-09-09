package com.teachbase.server.handout.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.List;

/** 中文维护说明：teacher canonical 或 student projection 的不可变 composition 输入。 */
public record HandoutEditionInput(
        @NotBlank @Size(max = 80) String editionKey,
        @NotBlank @Size(max = 24) String editionRole,
        @Size(max = 80) String canonicalTeacherEditionKey,
        @Positive int schemaVersion,
        @NotNull JsonNode projectionRules,
        @NotNull JsonNode delta,
        @NotNull List<@Valid HandoutOccurrenceInput> occurrences) {
}
