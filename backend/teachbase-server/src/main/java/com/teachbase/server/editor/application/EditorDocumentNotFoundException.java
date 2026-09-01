package com.teachbase.server.editor.application;

/** Workspace-scoped editor aggregate was not found or is no longer active. */
public class EditorDocumentNotFoundException extends RuntimeException {

    public EditorDocumentNotFoundException() {
        super("editor_document_not_found");
    }
}
