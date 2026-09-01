package com.teachbase.server.source.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Idempotent addressable-region registration within a source document. */
public record RegisterSourceRegionCommand(
        UUID workspaceId,
        UUID actorUserId,
        UUID sourceDocumentId,
        String externalRegionKey,
        String regionType,
        Integer pageNo,
        Integer orderIndex,
        JsonNode boundingBox,
        String extractedText,
        JsonNode sourceReference) {
}
