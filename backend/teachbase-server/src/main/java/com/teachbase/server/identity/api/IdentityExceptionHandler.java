package com.teachbase.server.identity.api;

import com.teachbase.server.identity.application.TeachingScopeValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 把身份与教学范围错误转换成稳定的问题详情，供前端按错误码处理。
 */
@RestControllerAdvice
class IdentityExceptionHandler {

    @ExceptionHandler(TeachingScopeValidationException.class)
    ProblemDetail teachingScope(TeachingScopeValidationException exception) {
        var status = "teaching_scope_forbidden".equals(exception.getMessage())
                ? HttpStatus.FORBIDDEN
                : HttpStatus.CONFLICT;
        var problem = ProblemDetail.forStatusAndDetail(status, exception.getMessage());
        problem.setTitle("Teaching scope conflict");
        problem.setType(URI.create("urn:teachbase:problem:" + exception.getMessage()));
        return problem;
    }
}
