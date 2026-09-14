package com.teachbase.server.difficultyfeedback.api;

import com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackAccessException;
import com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackConflictException;
import com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackNotFoundException;
import com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 中文维护说明：异常映射只作用于难度反馈 API，避免改动其他模块的错误合同。 */
@RestControllerAdvice(basePackageClasses = DifficultyFeedbackController.class)
class DifficultyFeedbackExceptionHandler {

    @ExceptionHandler({DifficultyFeedbackValidationException.class, MethodArgumentNotValidException.class})
    ProblemDetail invalid(Exception exception) {
        String code = exception instanceof DifficultyFeedbackValidationException
                ? exception.getMessage() : "DIFFICULTY_FEEDBACK_REQUEST_INVALID";
        return problem(HttpStatus.BAD_REQUEST, "Invalid difficulty feedback", code);
    }

    @ExceptionHandler(DifficultyFeedbackAccessException.class)
    ProblemDetail forbidden(DifficultyFeedbackAccessException exception) {
        return problem(HttpStatus.FORBIDDEN, "Difficulty feedback access denied", exception.getMessage());
    }

    @ExceptionHandler(DifficultyFeedbackNotFoundException.class)
    ProblemDetail missing(DifficultyFeedbackNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Difficulty feedback resource not found", exception.getMessage());
    }

    @ExceptionHandler(DifficultyFeedbackConflictException.class)
    ProblemDetail conflict(DifficultyFeedbackConflictException exception) {
        ProblemDetail detail = problem(HttpStatus.CONFLICT, "Difficulty feedback conflict", exception.getMessage());
        if (exception.currentStateVersion() != null) {
            detail.setProperty("currentStateVersion", exception.currentStateVersion());
            detail.setProperty("currentSnapshotId", exception.currentSnapshotId());
            detail.setProperty("status", exception.status());
        }
        return detail;
    }

    private ProblemDetail problem(HttpStatus status, String title, String code) {
        ProblemDetail detail = ProblemDetail.forStatusAndDetail(status, code);
        detail.setTitle(title);
        detail.setType(URI.create("urn:teachbase:problem:" + code));
        detail.setProperty("code", code);
        return detail;
    }
}
