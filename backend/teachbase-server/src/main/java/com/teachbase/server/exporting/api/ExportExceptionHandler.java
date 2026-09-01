package com.teachbase.server.exporting.api;

import com.teachbase.server.exporting.application.EditorSnapshotNotFoundException;
import com.teachbase.server.exporting.application.ExportValidationException;
import com.teachbase.server.exporting.application.ExportRequestNotFoundException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：RFC 9457 mapping for export admission, lookup, and snapshot errors.
 */
class ExportExceptionHandler {

    @ExceptionHandler(ExportValidationException.class)
    ProblemDetail invalidExport(ExportValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid export request", exception.getMessage());
    }

    @ExceptionHandler(EditorSnapshotNotFoundException.class)
    ProblemDetail snapshotNotFound(EditorSnapshotNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Editor snapshot not found", exception.getMessage());
    }

    @ExceptionHandler(ExportRequestNotFoundException.class)
    ProblemDetail exportNotFound(ExportRequestNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Export request not found", exception.getMessage());
    }

    private ProblemDetail problem(HttpStatus status, String title, String detail) {
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setTitle(title);
        problem.setType(URI.create("urn:teachbase:problem:" + detail));
        return problem;
    }
}
