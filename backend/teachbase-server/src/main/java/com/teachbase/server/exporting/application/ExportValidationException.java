package com.teachbase.server.exporting.application;

/** Stable export contract violation that is not retryable worker failure. */
public class ExportValidationException extends IllegalArgumentException {

    public ExportValidationException(String message) {
        super(message);
    }
}
