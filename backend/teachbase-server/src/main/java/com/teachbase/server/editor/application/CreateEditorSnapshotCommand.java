package com.teachbase.server.editor.application;

import java.util.UUID;

/** Application command pinning the revision and projection that must be frozen. */
public record CreateEditorSnapshotCommand(
        UUID editorDocumentId,
        UUID workspaceId,
        UUID actorUserId,
        long expectedRevisionNo,
        String variantKey,
        String audience,
        int schemaVersion) {
}
