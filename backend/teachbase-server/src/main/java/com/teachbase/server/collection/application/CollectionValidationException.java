package com.teachbase.server.collection.application;

/** Stable machine-readable collection request failure. */
public class CollectionValidationException extends RuntimeException {

    public CollectionValidationException(String code) {
        super(code);
    }
}
