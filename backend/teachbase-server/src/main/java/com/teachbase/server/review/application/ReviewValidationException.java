package com.teachbase.server.review.application;

/** Stable validation or optimistic-state error returned by Review HTTP APIs. */
public class ReviewValidationException extends RuntimeException {

    public ReviewValidationException(String code) {
        super(code);
    }
}
