package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.editor.application.EditorSnapshot;
import java.util.UUID;

/** Created immutable editor snapshot returned to an API client. */
public record EditorSnapshotResponse(
        UUID editorSnapshotId,
        UUID editorDocumentId,
        UUID editorRevisionId,
        long revisionNo,
        String variantKey,
        String audience,
        int schemaVersion,
        JsonNode frozenContent,
        String contentHash) {

    static EditorSnapshotResponse from(EditorSnapshot snapshot) {
        return new EditorSnapshotResponse(
                snapshot.editorSnapshotId(), snapshot.editorDocumentId(), snapshot.editorRevisionId(),
                snapshot.revisionNo(), snapshot.variantKey(), snapshot.audience(), snapshot.schemaVersion(),
                snapshot.frozenContent(), snapshot.contentHash());
    }
}
