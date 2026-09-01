package com.teachbase.server.editor.application;

/** Lost-update protection carrying the current revision that the client must reload. */
public class EditorRevisionConflictException extends RuntimeException {

    private final long currentRevisionNo;

    public EditorRevisionConflictException(long currentRevisionNo) {
        super("editor_revision_conflict");
        this.currentRevisionNo = currentRevisionNo;
    }

    public long currentRevisionNo() {
        return currentRevisionNo;
    }
}
