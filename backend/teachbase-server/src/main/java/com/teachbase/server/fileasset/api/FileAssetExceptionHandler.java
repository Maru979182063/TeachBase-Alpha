package com.teachbase.server.fileasset.api;

import com.teachbase.server.fileasset.domain.DomainValidationException;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Shared RFC 9457 mapping for request validation and workspace authorization.
 */
class FileAssetExceptionHandler {

    @ExceptionHandler(DomainValidationException.class)
    ProblemDetail invalidDomainValue(DomainValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid file registration", exception.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ProblemDetail invalidRequest(MethodArgumentNotValidException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid request", "request_validation_failed");
    }

    @ExceptionHandler(WorkspaceNotFoundException.class)
    ProblemDetail workspaceNotFound(WorkspaceNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Workspace not found", exception.getMessage());
    }

    @ExceptionHandler(ActorNotWorkspaceMemberException.class)
    ProblemDetail actorNotWorkspaceMember(ActorNotWorkspaceMemberException exception) {
        return problem(HttpStatus.FORBIDDEN, "Actor is not a workspace member", exception.getMessage());
    }

    private ProblemDetail problem(HttpStatus status, String title, String detail) {
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setTitle(title);
        problem.setType(URI.create("urn:teachbase:problem:" + detail.replace(':', '-')));
        return problem;
    }
}
