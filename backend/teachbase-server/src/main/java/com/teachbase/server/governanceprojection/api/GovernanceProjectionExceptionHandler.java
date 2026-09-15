package com.teachbase.server.governanceprojection.api;

import com.teachbase.server.governanceprojection.application.GovernanceProjectionAccessException;
import com.teachbase.server.governanceprojection.application.GovernanceProjectionValidationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 中文维护说明：HTTP 错误只返回稳定代码，内部 SQL 和租约细节留在服务日志。 */
@RestControllerAdvice(assignableTypes = GovernanceProjectionController.class)
public class GovernanceProjectionExceptionHandler {

    @ExceptionHandler(GovernanceProjectionAccessException.class)
    ProblemDetail forbidden(GovernanceProjectionAccessException exception) {
        return problem(HttpStatus.FORBIDDEN, exception.getMessage());
    }

    @ExceptionHandler(GovernanceProjectionValidationException.class)
    ProblemDetail invalid(GovernanceProjectionValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, exception.getMessage());
    }

    private ProblemDetail problem(HttpStatus status, String code) {
        ProblemDetail detail = ProblemDetail.forStatus(status);
        detail.setTitle(code);
        detail.setDetail(code);
        return detail;
    }
}
