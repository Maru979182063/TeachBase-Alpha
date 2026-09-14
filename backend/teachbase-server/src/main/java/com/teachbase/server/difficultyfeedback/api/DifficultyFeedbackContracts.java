package com.teachbase.server.difficultyfeedback.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：集中定义难度反馈稳定传输对象，避免向客户端暴露 jOOQ 或数据库记录。
 */
public final class DifficultyFeedbackContracts {

    private DifficultyFeedbackContracts() {
    }

    public record RegisterRubricRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotBlank @Size(max = 120) String rubricKey,
            @NotBlank @Size(max = 80) String versionCode,
            @NotBlank @Size(max = 80) String subject,
            @NotBlank @Size(max = 80) String stage,
            @Size(max = 80) String grade,
            @NotNull JsonNode definitions,
            @NotBlank @Size(max = 24) String status) {
    }

    public record RegisterRubricResponse(
            UUID rubricVersionId, boolean replayed, String rubricHash, String status) {
    }

    public record RegisterAssessmentRunRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotBlank @Size(max = 240) String externalRunKey,
            @NotNull UUID rubricVersionId,
            @NotBlank @Size(max = 120) String modelProvider,
            @NotBlank @Size(max = 160) String modelName,
            @NotBlank @Size(max = 160) String modelVersion,
            @NotBlank @Size(max = 160) String promptProfileVersion,
            @NotBlank @Size(max = 240) String evidencePackageKey,
            @NotBlank @Size(max = 160) String evidencePackageVersion,
            @NotBlank String evidencePackageHash,
            @NotBlank @Size(max = 160) String producerVersion,
            @NotBlank @Size(max = 160) String runtimeVersion,
            @NotNull JsonNode parameters,
            @NotBlank @Size(max = 24) String status,
            @NotNull OffsetDateTime startedAt,
            @NotNull OffsetDateTime completedAt) {
    }

    public record RegisterAssessmentRunResponse(
            UUID assessmentRunId, boolean replayed, String runHash, String parametersHash) {
    }

    public record RegisterDifficultySuggestionRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotNull UUID questionRevisionId,
            @NotBlank @Size(max = 160) String contextKey,
            @NotNull JsonNode context,
            @Min(1) @Max(5) int difficultyValue,
            @NotNull BigDecimal confidence,
            @NotNull JsonNode modelOutputContext) {
    }

    public record RegisterDifficultySuggestionResponse(
            UUID snapshotId,
            UUID stateId,
            long stateVersion,
            String status,
            String snapshotHash,
            boolean replayed) {
    }

    public record DifficultyRubricGapInput(
            @NotBlank @Size(max = 1000) String expectedDifficultyText,
            @NotBlank @Size(max = 10000) String explanation) {
    }

    public record SubmitDifficultyFeedbackRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotBlank @Size(max = 120) String rubricKey,
            @NotNull UUID rubricVersionId,
            @NotBlank @Size(max = 160) String contextKey,
            @NotNull UUID beforeSnapshotId,
            long expectedStateVersion,
            @NotBlank @Size(max = 160) String clientMutationId,
            @Min(1) @Max(5) Integer finalDifficultyValue,
            @NotNull List<@NotBlank @Size(max = 120) String> reasonCodes,
            @Size(max = 10000) String note,
            @Valid DifficultyRubricGapInput rubricGap) {
    }

    public record DifficultyOperation(String code, Integer fromValue, Integer toValue) {
    }

    public record SubmitDifficultyFeedbackResponse(
            UUID feedbackId,
            boolean replayed,
            long stateVersion,
            String status,
            UUID currentSnapshotId,
            List<DifficultyOperation> derivedOperations,
            UUID rubricGapCaseId) {
    }

    public record DifficultySnapshotView(
            UUID snapshotId,
            String snapshotKind,
            UUID rubricVersionId,
            String contextKey,
            JsonNode context,
            Integer difficultyValue,
            BigDecimal confidence,
            UUID assessmentRunId,
            JsonNode modelOutputContext,
            String snapshotHash,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    public record AssessmentRunView(
            UUID assessmentRunId,
            String externalRunKey,
            String modelProvider,
            String modelName,
            String modelVersion,
            String promptProfileVersion,
            String evidencePackageKey,
            String evidencePackageVersion,
            String evidencePackageHash,
            JsonNode parameters,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt) {
    }

    public record DifficultyQuestionSummary(
            UUID questionId,
            UUID questionRevisionId,
            String subject,
            String stage,
            String grade,
            String title,
            String stemMarkdown,
            JsonNode provenance) {
    }

    public record DifficultyReviewContextResponse(
            UUID questionRevisionId,
            String rubricKey,
            UUID rubricVersionId,
            String contextKey,
            long stateVersion,
            String status,
            DifficultySnapshotView systemSuggestion,
            DifficultySnapshotView currentSnapshot,
            AssessmentRunView runContext,
            DifficultyQuestionSummary questionSummary) {
    }

    public record DifficultyFeedbackView(
            UUID feedbackId,
            UUID beforeSnapshotId,
            UUID afterSnapshotId,
            String outcome,
            List<String> reasonCodes,
            String note,
            UUID reviewerId,
            OffsetDateTime submittedAt,
            List<DifficultyOperation> derivedOperations) {
    }

    public record DifficultyGapView(
            UUID gapCaseId,
            UUID feedbackId,
            String expectedDifficultyText,
            String teacherExplanation,
            String status,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    public record DifficultyFeedbackHistoryResponse(
            UUID questionRevisionId,
            String rubricKey,
            String contextKey,
            List<DifficultySnapshotView> snapshots,
            List<DifficultyFeedbackView> feedback,
            List<DifficultyGapView> rubricGaps) {
    }
}
