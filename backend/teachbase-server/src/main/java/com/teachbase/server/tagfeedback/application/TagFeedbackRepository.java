package com.teachbase.server.tagfeedback.application;

import static com.teachbase.server.tagfeedback.api.TagFeedbackContracts.DerivedOperation;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：标签反馈持久化端口以完整 snapshot 和 CAS 为边界，不暴露可绕过不变量的零散更新方法。
 */
public interface TagFeedbackRepository {

    StoredRun insertOrReplayRun(NewRun run);

    Optional<RunRecord> findRun(UUID workspaceId, UUID taggingRunId);

    StoredSnapshot insertOrReplaySnapshot(NewSnapshot snapshot, List<SnapshotItemRecord> items);

    Optional<SnapshotRecord> findSnapshot(UUID workspaceId, UUID snapshotId);

    List<SnapshotItemRecord> findSnapshotItems(UUID snapshotId);

    StateRecord insertOrFindPendingState(NewState state);

    Optional<StateRecord> findState(UUID workspaceId, UUID questionRevisionId, String taxonomyKey);

    void lockMutation(UUID workspaceId, String clientMutationId);

    Optional<FeedbackRecord> findFeedbackByMutation(UUID workspaceId, String clientMutationId);

    void insertFeedback(NewFeedback feedback);

    boolean compareAndSetState(
            UUID workspaceId,
            UUID questionRevisionId,
            String taxonomyKey,
            long expectedVersion,
            UUID taxonomyVersionId,
            UUID currentSnapshotId,
            UUID currentFeedbackId,
            String status,
            UUID updatedBy,
            OffsetDateTime updatedAt);

    UUID insertGap(NewGap gap);

    Optional<GapRecord> findGapByFeedback(UUID feedbackId);

    List<SnapshotRecord> findSnapshots(UUID workspaceId, UUID questionRevisionId, String taxonomyKey);

    List<FeedbackRecord> findFeedback(UUID workspaceId, UUID questionRevisionId, String taxonomyKey);

    List<GapRecord> findGaps(UUID workspaceId, UUID questionRevisionId);

    record NewRun(
            UUID taggingRunId,
            UUID workspaceId,
            String externalRunKey,
            UUID taxonomyVersionId,
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
            String parametersHash,
            String runHash,
            String status,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt,
            UUID canonicalImportRequestId,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    record RunRecord(
            UUID taggingRunId,
            UUID workspaceId,
            String externalRunKey,
            UUID taxonomyVersionId,
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
            String parametersHash,
            String runHash,
            String status,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt) {
    }

    record StoredRun(RunRecord run, boolean replayed) {
    }

    record NewSnapshot(
            UUID snapshotId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            String snapshotKind,
            String labelSetHash,
            String snapshotHash,
            UUID taggingRunId,
            JsonNode modelOutputContext,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    record SnapshotRecord(
            UUID snapshotId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            String snapshotKind,
            String labelSetHash,
            String snapshotHash,
            UUID taggingRunId,
            JsonNode modelOutputContext,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    record SnapshotItemRecord(
            UUID snapshotItemId,
            UUID snapshotId,
            UUID workspaceId,
            UUID taxonomyVersionId,
            UUID taxonomyNodeId,
            String relationType,
            int positionIndex,
            BigDecimal confidence,
            Integer candidateRank) {
    }

    record StoredSnapshot(SnapshotRecord snapshot, boolean replayed) {
    }

    record NewState(
            UUID stateId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            UUID currentSnapshotId,
            UUID updatedBy,
            OffsetDateTime updatedAt) {
    }

    record StateRecord(
            UUID stateId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            UUID currentSnapshotId,
            UUID currentFeedbackId,
            long stateVersion,
            String status,
            UUID updatedBy,
            OffsetDateTime updatedAt) {
    }

    record NewFeedback(
            UUID feedbackId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            UUID beforeSnapshotId,
            UUID afterSnapshotId,
            String outcome,
            List<String> reasonCodes,
            String note,
            UUID reviewerId,
            OffsetDateTime submittedAt,
            String clientMutationId,
            String requestHash,
            long expectedStateVersion,
            List<DerivedOperation> derivedOperations) {
    }

    record FeedbackRecord(
            UUID feedbackId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String taxonomyKey,
            UUID taxonomyVersionId,
            UUID beforeSnapshotId,
            UUID afterSnapshotId,
            String outcome,
            List<String> reasonCodes,
            String note,
            UUID reviewerId,
            OffsetDateTime submittedAt,
            String clientMutationId,
            String requestHash,
            long expectedStateVersion,
            List<DerivedOperation> derivedOperations) {
    }

    record NewGap(
            UUID gapCaseId,
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            UUID feedbackId,
            UUID reportedTaxonomyVersionId,
            UUID beforeSnapshotId,
            String expectedLabelText,
            String teacherExplanation,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }

    record GapRecord(
            UUID gapCaseId,
            UUID feedbackId,
            String expectedLabelText,
            String teacherExplanation,
            String status,
            UUID createdBy,
            OffsetDateTime createdAt) {
    }
}
