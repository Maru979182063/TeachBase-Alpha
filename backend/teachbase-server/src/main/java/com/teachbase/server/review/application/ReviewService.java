package com.teachbase.server.review.application;

import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.ActorNotWorkspaceMemberException;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.identity.api.WorkspaceNotFoundException;
import com.teachbase.server.question.api.QuestionReviewGateway;
import com.teachbase.server.question.api.QuestionReviewStateException;
import com.teachbase.server.review.api.DecideReviewCaseRequest;
import com.teachbase.server.review.api.OpenReviewCaseRequest;
import com.teachbase.server.review.api.ReviewCaseResponse;
import com.teachbase.server.review.api.ReviewWorkflow;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于人工审核模块的业务规则与事务编排层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 *
 * 英文术语对照：Coordinates tenant authorization, frozen hashes, decisions, and audit evidence.
 */
@Service
public class ReviewService implements ReviewWorkflow {

    private final WorkspaceDirectory workspaces;
    private final QuestionReviewGateway questions;
    private final ReviewRepository reviews;
    private final AuditTrail auditTrail;

    public ReviewService(
            WorkspaceDirectory workspaces,
            QuestionReviewGateway questions,
            ReviewRepository reviews,
            AuditTrail auditTrail) {
        this.workspaces = workspaces;
        this.questions = questions;
        this.reviews = reviews;
        this.auditTrail = auditTrail;
    }

    @Transactional
    @Override
    public ReviewCaseResponse open(OpenReviewCaseRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        if (request.assignedTo() != null && !workspaces.isActiveMember(request.workspaceId(), request.assignedTo())) {
            throw new ActorNotWorkspaceMemberException();
        }
        var target = questions.findTarget(request.workspaceId(), request.questionRevisionId())
                .orElseThrow(() -> new ReviewValidationException("review_question_revision_not_found"));
        if (!Set.of("unreviewed", "pending_review").contains(target.reviewStatus())) {
            throw new ReviewValidationException("review_question_not_reviewable");
        }
        var reviewCase = reviews.open(
                request.workspaceId(), target.questionId(), target.questionRevisionId(), target.contentHash(),
                request.assignedTo(), request.actorUserId());
        auditTrail.record(new AuditCommand(
                request.workspaceId(), request.actorUserId(), "review_case.opened", "review_case",
                reviewCase.reviewCaseId(), Map.of(
                        "questionId", target.questionId().toString(),
                        "questionRevisionId", target.questionRevisionId().toString(),
                        "expectedContentHash", target.contentHash())));
        return response(reviewCase);
    }

    @Transactional
    @Override
    public ReviewCaseResponse decide(UUID reviewCaseId, DecideReviewCaseRequest request) {
        validateActor(request.workspaceId(), request.actorUserId());
        String decision = clean(request.decision());
        if (!Set.of("approved", "rejected").contains(decision)) {
            throw new ReviewValidationException("review_decision_invalid");
        }
        String expectedHash = clean(request.expectedContentHash()).toLowerCase(java.util.Locale.ROOT);
        if (!expectedHash.matches("[0-9a-f]{64}")) {
            throw new ReviewValidationException("review_expected_hash_invalid");
        }
        String decisionSource = clean(request.decisionSource());
        if (!Set.of("human_ui", "release_seed", "api").contains(decisionSource)) {
            throw new ReviewValidationException("review_decision_source_invalid");
        }
        if (!request.evidence().isObject()) throw new ReviewValidationException("review_evidence_invalid");
        var reviewCase = reviews.lockOpen(request.workspaceId(), reviewCaseId)
                .orElseThrow(() -> new ReviewValidationException("review_case_not_open"));
        if (!reviewCase.expectedContentHash().equals(expectedHash)) {
            throw new ReviewValidationException("review_case_content_changed");
        }
        try {
            questions.applyDecision(
                    request.workspaceId(), request.actorUserId(), reviewCase.questionRevisionId(),
                    expectedHash, decision);
        } catch (QuestionReviewStateException exception) {
            throw new ReviewValidationException(exception.getMessage());
        }
        var completed = reviews.complete(
                reviewCase, request.actorUserId(), decision, request.note() == null ? "" : request.note().strip(),
                clean(request.policyVersion()), decisionSource, request.evidence(), request.evidenceOccurredAt());
        auditTrail.record(new AuditCommand(
                request.workspaceId(), request.actorUserId(), "review_case." + decision, "review_case",
                reviewCaseId, Map.of(
                        "questionId", reviewCase.questionId().toString(),
                        "questionRevisionId", reviewCase.questionRevisionId().toString(),
                        "expectedContentHash", expectedHash,
                        "policyVersion", clean(request.policyVersion()),
                        "decisionSource", decisionSource)));
        return response(completed);
    }

    private void validateActor(UUID workspaceId, UUID actorUserId) {
        if (!workspaces.exists(workspaceId)) throw new WorkspaceNotFoundException();
        if (!workspaces.isActiveMember(workspaceId, actorUserId)) throw new ActorNotWorkspaceMemberException();
    }

    private ReviewCaseResponse response(ReviewCaseRecord value) {
        return new ReviewCaseResponse(
                value.reviewCaseId(), value.questionId(), value.questionRevisionId(), value.expectedContentHash(),
                value.status(), value.assignedTo(), value.openedAt(), value.decidedAt());
    }

    private String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
