package com.teachbase.server.source.application;

/** Stable source evidence validation failure. */
public class SourceValidationException extends RuntimeException {

    public SourceValidationException(String code) {
        super(code);
    }
}
