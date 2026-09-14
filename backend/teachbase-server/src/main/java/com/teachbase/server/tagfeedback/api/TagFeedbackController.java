package com.teachbase.server.tagfeedback.api;

import static com.teachbase.server.tagfeedback.api.TagFeedbackContracts.*;

import com.teachbase.server.tagfeedback.application.TagFeedbackService;
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

/**
 * 中文维护说明：只负责 01A 的运行登记、原判登记、上下文读取、反馈提交和单题历史协议转换。
 */
@RestController
@RequestMapping("/api/v1")
class TagFeedbackController {

    private final TagFeedbackService service;

    TagFeedbackController(TagFeedbackService service) {
        this.service = service;
    }

    @PostMapping("/tagging-runs")
    ResponseEntity<TaggingRunResponse> registerRun(
            @Valid @RequestBody RegisterTaggingRunRequest request) {
        return ResponseEntity.ok(service.registerRun(request));
    }

    @PostMapping("/tagging-runs/{taggingRunId}/question-suggestions")
    ResponseEntity<RegisterSuggestionResponse> registerSuggestion(
            @PathVariable UUID taggingRunId,
            @Valid @RequestBody RegisterSuggestionRequest request) {
        return ResponseEntity.ok(service.registerSuggestion(taggingRunId, request));
    }

    @GetMapping("/question-revisions/{questionRevisionId}/tag-review-context")
    ResponseEntity<TagReviewContextResponse> reviewContext(
            @PathVariable UUID questionRevisionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam String taxonomyKey) {
        return ResponseEntity.ok(service.reviewContext(
                questionRevisionId, workspaceId, actorUserId, taxonomyKey));
    }

    @PostMapping("/question-revisions/{questionRevisionId}/tag-feedback")
    ResponseEntity<SubmitTagFeedbackResponse> submit(
            @PathVariable UUID questionRevisionId,
            @Valid @RequestBody SubmitTagFeedbackRequest request) {
        return ResponseEntity.ok(service.submit(questionRevisionId, request));
    }

    @GetMapping("/question-revisions/{questionRevisionId}/tag-feedback-history")
    ResponseEntity<TagFeedbackHistoryResponse> history(
            @PathVariable UUID questionRevisionId,
            @RequestParam UUID workspaceId,
            @RequestParam UUID actorUserId,
            @RequestParam String taxonomyKey) {
        return ResponseEntity.ok(service.history(
                questionRevisionId, workspaceId, actorUserId, taxonomyKey));
    }
}
