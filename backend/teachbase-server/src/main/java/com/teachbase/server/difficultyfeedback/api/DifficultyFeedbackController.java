package com.teachbase.server.difficultyfeedback.api;

import static com.teachbase.server.difficultyfeedback.api.DifficultyFeedbackContracts.*;

import com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 中文维护说明：只暴露难度标准、初判、教师反馈和单题历史的最小 HTTP 合同。 */
@RestController
@RequestMapping("/api/v1")
class DifficultyFeedbackController {

    private final DifficultyFeedbackService service;

    DifficultyFeedbackController(DifficultyFeedbackService service) {
        this.service = service;
    }

    @PostMapping("/difficulty-rubrics/versions")
    ResponseEntity<RegisterRubricResponse> registerRubric(
            @Valid @RequestBody RegisterRubricRequest request) {
        return ResponseEntity.ok(service.registerRubric(request));
    }

    @PostMapping("/difficulty-assessment-runs")
    ResponseEntity<RegisterAssessmentRunResponse> registerRun(
            @Valid @RequestBody RegisterAssessmentRunRequest request) {
        return ResponseEntity.ok(service.registerRun(request));
    }

    @PostMapping("/difficulty-assessment-runs/{runId}/question-suggestions")
    ResponseEntity<RegisterDifficultySuggestionResponse> registerSuggestion(
            @PathVariable UUID runId,
            @Valid @RequestBody RegisterDifficultySuggestionRequest request) {
        return ResponseEntity.ok(service.registerSuggestion(runId, request));
    }

    @GetMapping("/question-revisions/{questionRevisionId}/difficulty-review-context")
    ResponseEntity<DifficultyReviewContextResponse> reviewContext(
            @PathVariable UUID questionRevisionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam String rubricKey,
            @RequestParam String contextKey) {
        return ResponseEntity.ok(service.reviewContext(
                questionRevisionId, workspaceId, actorUserId, rubricKey, contextKey));
    }

    @PostMapping("/question-revisions/{questionRevisionId}/difficulty-feedback")
    ResponseEntity<SubmitDifficultyFeedbackResponse> submit(
            @PathVariable UUID questionRevisionId,
            @Valid @RequestBody SubmitDifficultyFeedbackRequest request) {
        return ResponseEntity.ok(service.submit(questionRevisionId, request));
    }

    @GetMapping("/question-revisions/{questionRevisionId}/difficulty-feedback-history")
    ResponseEntity<DifficultyFeedbackHistoryResponse> history(
            @PathVariable UUID questionRevisionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam String rubricKey,
            @RequestParam String contextKey) {
        return ResponseEntity.ok(service.history(
                questionRevisionId, workspaceId, actorUserId, rubricKey, contextKey));
    }
}
