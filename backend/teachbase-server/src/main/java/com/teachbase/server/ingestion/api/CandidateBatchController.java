package com.teachbase.server.ingestion.api;

import com.teachbase.server.ingestion.application.CandidateBatchService;
import com.teachbase.server.ingestion.application.CandidateValidationException;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：对外仅开放候选保存；审核决定仍由已有审核模块负责。 */
@RestController
@RequestMapping("/api/v1/ingestion/candidate-batches")
class CandidateBatchController {
    private final CandidateBatchService service;

    CandidateBatchController(CandidateBatchService service) {
        this.service = service;
    }

    @PostMapping
    CandidateBatchResponse ingest(@Valid @RequestBody CandidateBatchRequest request) {
        return service.ingest(request);
    }

    @ExceptionHandler(CandidateValidationException.class)
    ProblemDetail invalid(CandidateValidationException exception) {
        return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, exception.getMessage());
    }
}
