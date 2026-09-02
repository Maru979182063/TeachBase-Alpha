package com.teachbase.server.editor.api;

import com.teachbase.server.editor.application.EditorDocumentNotFoundException;
import com.teachbase.server.editor.application.EditorClientUpgradeRequiredException;
import com.teachbase.server.editor.application.EditorContentValidationException;
import com.teachbase.server.editor.application.EditorRevisionConflictException;
import com.teachbase.server.editor.application.EditorMutationConflictException;
import com.teachbase.server.editor.application.EditorWriterFencedException;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：RFC 9457 mapping for editor validation, lookup, and revision conflicts.
 */
class EditorExceptionHandler {

    @ExceptionHandler(EditorContentValidationException.class)
    ProblemDetail invalidEditorContent(EditorContentValidationException exception) {
        return problem(HttpStatus.BAD_REQUEST, "Invalid editor content", exception.getMessage());
    }

    @ExceptionHandler(EditorDocumentNotFoundException.class)
    ProblemDetail documentNotFound(EditorDocumentNotFoundException exception) {
        return problem(HttpStatus.NOT_FOUND, "Editor document not found", exception.getMessage());
    }

    @ExceptionHandler(EditorRevisionConflictException.class)
    ProblemDetail revisionConflict(EditorRevisionConflictException exception) {
        var problem = problem(HttpStatus.CONFLICT, "Editor revision conflict", exception.getMessage());
        problem.setProperty("currentDraftVersion", exception.currentDraftVersion());
        return problem;
    }

    @ExceptionHandler(EditorMutationConflictException.class)
    ProblemDetail mutationConflict(EditorMutationConflictException exception) {
        return problem(HttpStatus.CONFLICT, "Editor mutation conflict", exception.getMessage());
    }

    @ExceptionHandler(EditorWriterFencedException.class)
    ProblemDetail writerFenced(EditorWriterFencedException exception) {
        return problem(HttpStatus.SERVICE_UNAVAILABLE, "Editor writer fenced", exception.getMessage());
    }

    @ExceptionHandler(EditorClientUpgradeRequiredException.class)
    ProblemDetail clientUpgradeRequired(EditorClientUpgradeRequiredException exception) {
        var problem = problem(HttpStatus.UPGRADE_REQUIRED, "Editor client upgrade required", exception.getMessage());
        problem.setProperty("requiredContract", "editor-working-draft-v2");
        problem.setProperty("requiredFields", new String[] {"expectedDraftVersion", "clientMutationId"});
        return problem;
    }

    private ProblemDetail problem(HttpStatus status, String title, String detail) {
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setTitle(title);
        problem.setType(URI.create("urn:teachbase:problem:" + detail));
        return problem;
    }
}
