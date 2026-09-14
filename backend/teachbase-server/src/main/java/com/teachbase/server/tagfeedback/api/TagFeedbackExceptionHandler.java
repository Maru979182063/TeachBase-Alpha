package com.teachbase.server.tagfeedback.api;

import com.teachbase.server.tagfeedback.application.TagFeedbackAccessException;
import com.teachbase.server.tagfeedback.application.TagFeedbackConflictException;
import com.teachbase.server.tagfeedback.application.TagFeedbackNotFoundException;
import com.teachbase.server.tagfeedback.application.TagFeedbackValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 中文维护说明：把标签反馈失败映射为稳定 problem code；409 会返回最新 state 供客户端显式处理。
 */
@RestControllerAdvice(basePackageClasses = TagFeedbackController.class)
class TagFeedbackExceptionHandler {

    @ExceptionHandler(TagFeedbackValidationException.class)
    ProblemDetail invalid(TagFeedbackValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid tag feedback", exception.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ProblemDetail invalidBody(MethodArgumentNotValidException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid tag feedback", "TAG_FEEDBACK_REQUEST_INVALID");
    }

    @ExceptionHandler(TagFeedbackAccessException.class)
    ProblemDetail forbidden(TagFeedbackAccessException exception) {
        return problem(HttpStatus.FORBIDDEN, "Tag feedback access denied", exception.getMessage());
    }

    @ExceptionHandler(TagFeedbackNotFoundException.class)
    ProblemDetail missing(TagFeedbackNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Tag feedback resource not found", exception.getMessage());
    }

    @ExceptionHandler(TagFeedbackConflictException.class)
    ProblemDetail conflict(TagFeedbackConflictException exception) {
        var result = problem(HttpStatus.CONFLICT, "Tag feedback state conflict", exception.getMessage());
        if (exception.currentStateVersion() != null) {
            result.setProperty("currentStateVersion", exception.currentStateVersion());
            result.setProperty("currentSnapshotId", exception.currentSnapshotId());
            result.setProperty("tagStatus", exception.tagStatus());
        }
        return result;
    }

    private ProblemDetail problem(HttpStatus status, String title, String code) {
        var result = ProblemDetail.forStatusAndDetail(status, code);
        result.setTitle(title);
        result.setType(URI.create("urn:teachbase:problem:" + code));
        result.setProperty("code", code);
        return result;
    }
}
