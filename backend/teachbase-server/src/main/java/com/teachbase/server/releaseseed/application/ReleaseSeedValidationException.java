package com.teachbase.server.releaseseed.application;

/** Stable fail-closed package, mapping, or checkpoint validation error. */
public class ReleaseSeedValidationException extends RuntimeException {

    public ReleaseSeedValidationException(String code) {
        super(code);
    }

    public ReleaseSeedValidationException(String code, Throwable cause) {
        super(code, cause);
    }
}
