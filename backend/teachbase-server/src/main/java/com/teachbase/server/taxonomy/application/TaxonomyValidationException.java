package com.teachbase.server.taxonomy.application;

/** Stable taxonomy validation or lifecycle error. */
public class TaxonomyValidationException extends RuntimeException {

    public TaxonomyValidationException(String code) {
        super(code);
    }
}
