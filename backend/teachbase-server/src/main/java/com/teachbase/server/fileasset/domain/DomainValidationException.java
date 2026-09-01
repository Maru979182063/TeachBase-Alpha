package com.teachbase.server.fileasset.domain;

/** Stable file-domain validation failure for client-visible problem details. */
public class DomainValidationException extends IllegalArgumentException {

    public DomainValidationException(String message) {
        super(message);
    }
}
