package com.teachbase.server.tagfeedback.api;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：集中定义 01A 的稳定传输对象，避免把数据库记录或 jOOQ 类型泄漏到 HTTP 边界。
 */
public final class TagFeedbackContracts {

    private TagFeedbackContracts() {
    }

    public record RegisterTaggingRunRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotBlank @Size(max = 240) String externalRunKey,
            @NotNull UUID taxonomyVersionId,
            @NotBlank @Size(max = 120) String modelProvider,
            @NotBlank @Size(max = 160) String modelName,
            @NotBlank @Size(max = 160) String modelVersion,
            @NotBlank @Size(max = 160) String promptProfileVersion,
            @NotBlank @Size(max = 240) String candidatePackageKey,
            @NotBlank @Size(max = 160) String candidatePackageVersion,
            @NotBlank String candidatePackageHash,
            @NotBlank @Size(max = 160) String producerVersion,
            @NotBlank @Size(max = 160) String runtimeVersion,
            @NotNull JsonNode parameters,
            @NotBlank @Size(max = 24) String status,
            @NotNull OffsetDateTime startedAt,
            OffsetDateTime completedAt,
            UUID canonicalImportRequestId) {
    }

    public record TaggingRunResponse(
            UUID taggingRunId,
            boolean replayed,
            String runHash,
            String parametersHash,
            String status) {
    }

    public record TagItemInput(
            @NotNull UUID taxonomyNodeId,
            BigDecimal confidence,
            Integer candidateRank) {
    }

    public record RegisterSuggestionRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotNull UUID questionRevisionId,
            @NotBlank @Size(max = 120) String taxonomyKey,
            @NotNull @Valid TagItemInput primary,
            @NotNull @Valid List<@NotNull TagItemInput> secondary,
            @NotNull JsonNode modelOutputContext) {
    }

    public record RegisterSuggestionResponse(
            UUID snapshotId,
            UUID stateId,
            long stateVersion,
            String tagStatus,
            String labelSetHash,
            String snapshotHash,
            boolean replayed) {
    }

    public record TaxonomyGapInput(
            @NotBlank @Size(max = 1000) String expectedLabelText,
            @NotBlank @Size(max = 10000) String explanation) {
    }

    public record SubmitTagFeedbackRequest(
            @NotNull UUID workspaceId,
            @NotNull UUID actorUserId,
            @NotBlank @Size(max = 120) String taxonomyKey,
            @NotNull UUID taxonomyVersionId,
            @NotNull UUID beforeSnapshotId,
            long expectedStateVersion,
            @NotBlank @Size(max = 160) String clientMutationId,
            UUID finalPrimaryNodeId,
            @NotNull List<@NotNull UUID> finalSecondaryNodeIds,
            @NotNull List<@NotBlank @Size(max = 120) String> reasonCodes,
            @Size(max = 10000) String note,
            @Valid TaxonomyGapInput taxonomyGap) {
    }

    public record DerivedOperation(
            String code,
            UUID nodeId,
            UUID fromNodeId,
            UUID toNodeId) {
    }

    public record SubmitTagFeedbackResponse(
            UUID feedbackId,
            boolean replayed,
            long stateVersion,
            String tagStatus,
            UUID currentSnapshotId,
            List<DerivedOperation> derivedOperations,
            UUID taxonomyGapCaseId) {
    }

    public record TagItemView(
            UUID taxonomyNodeId,
            String relationType,
            int positionIndex,
            BigDecimal confidence,
            Integer candidateRank) {
    }

    public record SnapshotView(
            UUID snapshotId,
            String snapshotKind,
            UUID taxonomyVersionId,
            UUID taggingRunId,
            String labelSetHash,
            String snapshotHash,
            JsonNode modelOutputContext,
            UUID createdBy,
            OffsetDateTime createdAt,
            List<TagItemView> items) {
    }

    public record RunView(
            UUID taggingRunId,
            String externalRunKey,
            String modelProvider,
            String modelName,
            String modelVersion,
            String promptProfileVersion,
            String candidatePackageKey,
            String candidatePackageVersion,
            String candidatePackageHash,
            String producerVersion,
            String runtimeVersion,
            JsonNode parameters,
            String status,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt) {
    }

    public record QuestionSourceSummary(
            UUID questionId,
            UUID questionRevisionId,
            String subject,
            String stage,
            String title,
            String stemMarkdown,
            JsonNode provenance) {
    }

    public record TagReviewContextResponse(
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            long stateVersion,
            String tagStatus,
            SnapshotView systemSuggestion,
            SnapshotView currentSnapshot,
            RunView runContext,
            QuestionSourceSummary questionSourceSummary) {
    }

    public record FeedbackView(
            UUID feedbackId,
            UUID beforeSnapshotId,
            UUID afterSnapshotId,
            String outcome,
            List<String> reasonCodes,
            String note,
            UUID reviewerId,
            OffsetDateTime submittedAt,
            List<DerivedOperation> derivedOperations) {
    }

    public record TaxonomyGapView(
            UUID gapCaseId,
            UUID feedbackId,
            String expectedLabelText,
            String teacherExplanation,
            String status,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    public record TagFeedbackHistoryResponse(
            UUID questionRevisionId,
            String taxonomyKey,
            List<SnapshotView> snapshots,
            List<FeedbackView> feedback,
            List<TaxonomyGapView> taxonomyGaps) {
    }
}
