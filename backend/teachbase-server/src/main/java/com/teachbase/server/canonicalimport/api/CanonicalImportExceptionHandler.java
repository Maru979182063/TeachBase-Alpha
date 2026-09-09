package com.teachbase.server.canonicalimport.api;

import com.teachbase.server.canonicalimport.application.CanonicalImportConflictException;
import com.teachbase.server.canonicalimport.application.CanonicalImportValidationException;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 中文维护说明：G5 错误使用 RFC 9457 和稳定 detail code，不回显跨 workspace 数据。 */
@RestControllerAdvice
class CanonicalImportExceptionHandler {

    @ExceptionHandler(CanonicalImportConflictException.class)
    ProblemDetail conflict(CanonicalImportConflictException exception) {
        return problem(HttpStatus.CONFLICT, "Canonical import conflict", exception.getMessage());
    }

    @ExceptionHandler(CanonicalImportValidationException.class)
    ProblemDetail invalid(CanonicalImportValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid canonical import", exception.getMessage());
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
        var result = ProblemDetail.forStatusAndDetail(status, detail);
        result.setTitle(title);
        result.setType(URI.create("urn:teachbase:problem:" + detail.replace(':', '-')));
        return result;
    }
}
