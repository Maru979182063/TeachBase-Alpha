package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Validated application command for creating the next immutable editor revision. */
public record UpdateEditorDraftCommand(
        UUID editorDocumentId,
        UUID workspaceId,
        UUID actorUserId,
        long expectedRevisionNo,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides) {
}
