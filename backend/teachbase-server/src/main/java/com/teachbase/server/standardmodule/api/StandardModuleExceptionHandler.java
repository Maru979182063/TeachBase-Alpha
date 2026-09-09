package com.teachbase.server.standardmodule.api;

import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.standardmodule.application.StandardModuleValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 中文维护说明：将标准模块业务错误映射为稳定 RFC 9457 响应。 */
@RestControllerAdvice
class StandardModuleExceptionHandler {

    @ExceptionHandler(StandardModuleValidationException.class)
    ProblemDetail invalid(StandardModuleValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid standard module", exception.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ProblemDetail request(MethodArgumentNotValidException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid request", "request_validation_failed");
    }

    @ExceptionHandler(WorkspaceNotFoundException.class)
    ProblemDetail workspace(WorkspaceNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Workspace not found", exception.getMessage());
    }

    @ExceptionHandler(ActorNotWorkspaceMemberException.class)
    ProblemDetail actor(ActorNotWorkspaceMemberException exception) {
        return problem(HttpStatus.FORBIDDEN, "Actor is not a workspace member", exception.getMessage());
    }

    private ProblemDetail problem(HttpStatus status, String title, String detail) {
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setTitle(title);
        problem.setType(URI.create("urn:teachbase:problem:" + detail.replace(':', '-')));
        return problem;
    }
}
