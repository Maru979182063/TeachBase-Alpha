package com.teachbase.server.review.api;

import com.teachbase.server.review.application.ReviewValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Converts review validation and optimistic-state failures to stable conflicts. */
@RestControllerAdvice
class ReviewExceptionHandler {

    @ExceptionHandler(ReviewValidationException.class)
    ProblemDetail invalid(ReviewValidationException exception) {
        var problem = ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, exception.getMessage());
        problem.setTitle("Review state conflict");
        problem.setType(URI.create("urn:teachbase:problem:" + exception.getMessage()));
        return problem;
    }
}
