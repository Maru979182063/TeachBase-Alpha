package com.teachbase.server.review.api;

import com.teachbase.server.review.application.ReviewValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Converts review validation and optimistic-state failures to stable conflicts.
 */
@RestControllerAdvice
class ReviewExceptionHandler {

    @ExceptionHandler(ReviewValidationException.class)
    ProblemDetail invalid(ReviewValidationException exception) {
        var problem = ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, exception.getMessage());
        problem.setTitle("Review state conflict");
        problem.setType(URI.create("urn:teachbase:problem:" + exception.getMessage()));
        return problem;
    }
}
