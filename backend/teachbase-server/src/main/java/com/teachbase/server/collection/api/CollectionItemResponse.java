package com.teachbase.server.collection.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** One current basket item in stable display order. */
public record CollectionItemResponse(
        UUID questionId,
        UUID questionRevisionId,
        int positionIndex,
        JsonNode settings) {
}
