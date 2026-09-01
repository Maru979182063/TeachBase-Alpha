package com.teachbase.server.question.api;

import com.teachbase.server.question.application.QuestionValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Converts stable question error codes into RFC 9457 problem responses. */
@RestControllerAdvice
class QuestionExceptionHandler {

    @ExceptionHandler(QuestionValidationException.class)
    ProblemDetail invalid(QuestionValidationException exception) {
        var problem = ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, exception.getMessage());
        problem.setTitle("Invalid question request");
        problem.setType(URI.create("urn:teachbase:problem:" + exception.getMessage()));
        return problem;
    }
}
