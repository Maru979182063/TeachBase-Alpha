package com.teachbase.server.editor.api;

import java.util.Optional;
import java.util.UUID;

/** Read port for immutable, export-ready editor snapshots. */
public interface EditorSnapshotDirectory {

    Optional<EditorSnapshotDescriptor> find(UUID editorSnapshotId, UUID workspaceId);
}
