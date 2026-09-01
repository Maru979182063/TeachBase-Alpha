package com.teachbase.server.collection.api;

import com.teachbase.server.collection.application.CollectionNotFoundException;
import com.teachbase.server.collection.application.CollectionValidationException;
import com.teachbase.server.collection.application.CollectionVersionConflictException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：RFC 9457 mapping for collection validation, lookup, and optimistic-lock errors.
 */
@RestControllerAdvice
class CollectionExceptionHandler {

    @ExceptionHandler(CollectionValidationException.class)
    ProblemDetail invalid(CollectionValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid question collection", exception.getMessage());
    }

    @ExceptionHandler(CollectionNotFoundException.class)
    ProblemDetail missing(CollectionNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Question collection not found", exception.getMessage());
    }

    @ExceptionHandler(CollectionVersionConflictException.class)
    ProblemDetail conflict(CollectionVersionConflictException exception) {
        var problem = problem(HttpStatus.CONFLICT, "Question collection version conflict", exception.getMessage());
        problem.setProperty("currentDraftVersion", exception.currentDraftVersion());
        return problem;
    }

    private ProblemDetail problem(HttpStatus status, String title, String detail) {
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setTitle(title);
        problem.setType(URI.create("urn:teachbase:problem:" + detail));
        return problem;
    }
}
