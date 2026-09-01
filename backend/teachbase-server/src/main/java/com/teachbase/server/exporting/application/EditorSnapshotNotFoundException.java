package com.teachbase.server.exporting.application;

/** Requested immutable editor snapshot is absent from the caller's workspace. */
public class EditorSnapshotNotFoundException extends RuntimeException {

    public EditorSnapshotNotFoundException() {
        super("editor_snapshot_not_found");
    }
}
