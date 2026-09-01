package com.teachbase.server.question.api;

import com.teachbase.server.question.application.QuestionService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** HTTP boundary for bounded ingestion batches and approved-question retrieval. */
@RestController
@RequestMapping("/api/v1/questions")
class QuestionController {

    private final QuestionService service;

    QuestionController(QuestionService service) {
        this.service = service;
    }

    @PostMapping("/import-batch")
    ResponseEntity<BulkQuestionImportResponse> importBatch(@Valid @RequestBody BulkQuestionImportRequest request) {
        return ResponseEntity.ok(service.importBatch(request));
    }

    @GetMapping("/search")
    QuestionSearchResponse search(
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam(defaultValue = "approved") String reviewStatus,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "") String subject,
            @RequestParam(defaultValue = "") String stage,
            @RequestParam(defaultValue = "") String grade,
            @RequestParam(defaultValue = "") String questionType,
            @RequestParam(required = false) Integer difficultyStars,
            @RequestParam(defaultValue = "") String cursor,
            @RequestParam(defaultValue = "30") int limit) {
        return service.search(
                workspaceId, actorUserId, reviewStatus, query, subject, stage, grade, questionType,
                difficultyStars, cursor, limit);
    }
}
