package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Cross-module read model containing one self-contained frozen editor projection. */
public record EditorSnapshotDescriptor(
        UUID editorSnapshotId,
        UUID workspaceId,
        String audience,
        int schemaVersion,
        JsonNode frozenContent,
        String contentHash) {
}
