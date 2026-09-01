package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Validated controller-to-application command for editor aggregate creation. */
public record CreateEditorDocumentCommand(
        UUID workspaceId,
        UUID actorUserId,
        String documentKind,
        String title,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides) {
}
