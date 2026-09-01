package com.teachbase.server.editor.application;

/** Stable editor contract violation suitable for a client-visible problem detail. */
public class EditorContentValidationException extends IllegalArgumentException {

    public EditorContentValidationException(String message) {
        super(message);
    }
}
