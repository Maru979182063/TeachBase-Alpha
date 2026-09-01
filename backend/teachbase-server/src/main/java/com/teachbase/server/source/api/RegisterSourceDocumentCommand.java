package com.teachbase.server.source.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Idempotent source-document registration keyed by a durable external source key. */
public record RegisterSourceDocumentCommand(
        UUID workspaceId,
        UUID actorUserId,
        UUID fileVersionId,
        String externalSourceKey,
        String sourceType,
        String subject,
        String stage,
        String grade,
        String title,
        JsonNode metadata) {
}
