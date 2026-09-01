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
/** RFC 9457 mapping for export admission, lookup, and snapshot errors. */
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
