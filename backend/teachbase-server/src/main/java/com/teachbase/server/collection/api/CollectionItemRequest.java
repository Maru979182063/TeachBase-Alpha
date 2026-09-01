package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;

/** Ordered reference to one immutable question revision plus display settings. */
public record CollectionItemRequest(@NotNull UUID questionRevisionId, @NotNull JsonNode settings) {
}
