package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Canonical current editor state backed by one immutable revision row. */
public record EditorDraft(
        UUID editorDocumentId,
        UUID workspaceId,
        String documentKind,
        String title,
        UUID editorRevisionId,
        long revisionNo,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides,
        String contentHash) {
}
