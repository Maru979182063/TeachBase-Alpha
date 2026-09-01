package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** Application result for a self-contained, hash-addressed editor snapshot. */
public record EditorSnapshot(
        UUID editorSnapshotId,
        UUID editorDocumentId,
        UUID editorRevisionId,
        long revisionNo,
        String variantKey,
        String audience,
        int schemaVersion,
        JsonNode frozenContent,
        String contentHash) {
}
