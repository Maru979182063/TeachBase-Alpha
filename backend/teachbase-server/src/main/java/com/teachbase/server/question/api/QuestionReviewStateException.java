package com.teachbase.server.question.api;

/** Review target changed, disappeared, or was already decided. */
public class QuestionReviewStateException extends RuntimeException {

    public QuestionReviewStateException(String code) {
        super(code);
    }
}
