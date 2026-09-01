package com.teachbase.server.question.application;

/** Stable machine-readable validation failure returned by the question API. */
public class QuestionValidationException extends RuntimeException {

    public QuestionValidationException(String code) {
        super(code);
    }
}
