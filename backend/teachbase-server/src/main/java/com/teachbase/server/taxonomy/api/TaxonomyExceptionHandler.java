package com.teachbase.server.taxonomy.api;

import com.teachbase.server.taxonomy.application.TaxonomyValidationException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 中文维护说明：本文件属于知识体系版本模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Converts taxonomy lifecycle errors to stable RFC 9457 responses.
 */
@RestControllerAdvice
class TaxonomyExceptionHandler {

    @ExceptionHandler(TaxonomyValidationException.class)
    ProblemDetail invalid(TaxonomyValidationException exception) {
        var problem = ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, exception.getMessage());
        problem.setTitle("Taxonomy state conflict");
        problem.setType(URI.create("urn:teachbase:problem:" + exception.getMessage()));
        return problem;
    }
}
