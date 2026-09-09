package com.teachbase.server.handout.api;

import com.teachbase.server.handout.application.HandoutValidationException;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 中文维护说明：将 composition 校验和权限错误映射为稳定 RFC 9457 响应。 */
@RestControllerAdvice
class HandoutExceptionHandler {

    @ExceptionHandler(HandoutValidationException.class)
    ProblemDetail invalid(HandoutValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid handout composition", exception.getMessage());
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
