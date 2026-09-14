package com.teachbase.server.difficultyfeedback.application;

import static com.teachbase.server.difficultyfeedback.api.DifficultyFeedbackContracts.DifficultyOperation;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** 中文维护说明：持久化端口只提供完整事实写入、显式 current pointer 和 CAS。 */
public interface DifficultyFeedbackRepository {

    StoredRubric insertOrReplayRubric(NewRubric rubric);

    Optional<RubricRecord> findRubric(UUID workspaceId, UUID rubricVersionId);

    StoredRun insertOrReplayRun(NewRun run);

    Optional<RunRecord> findRun(UUID workspaceId, UUID runId);

    StoredSnapshot insertOrReplaySnapshot(NewSnapshot snapshot);

    Optional<SnapshotRecord> findSnapshot(UUID workspaceId, UUID snapshotId);

    List<SnapshotRecord> findSnapshots(UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey);

    StateRecord insertOrFindPendingState(NewState state);

    Optional<StateRecord> findState(UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey);

    void lockMutation(UUID workspaceId, String clientMutationId);

    Optional<FeedbackRecord> findFeedbackByMutation(UUID workspaceId, String clientMutationId);

    void insertFeedback(NewFeedback feedback);

    boolean compareAndSetState(NewStateUpdate update);

    UUID insertGap(NewGap gap);

    Optional<GapRecord> findGapByFeedback(UUID feedbackId);

    List<FeedbackRecord> findFeedback(UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey);

    List<GapRecord> findGaps(UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey);

    record NewRubric(UUID rubricVersionId, UUID workspaceId, String rubricKey, String versionCode,
                     String subject, String stage, String grade, JsonNode definitions, String rubricHash,
                     String status, UUID createdBy, OffsetDateTime createdAt) {}

    record RubricRecord(UUID rubricVersionId, UUID workspaceId, String rubricKey, String versionCode,
                        String subject, String stage, String grade, JsonNode definitions, String rubricHash,
                        String status, UUID createdBy, OffsetDateTime createdAt) {}

    record StoredRubric(RubricRecord rubric, boolean replayed) {}

    record NewRun(UUID runId, UUID workspaceId, String externalRunKey, String rubricKey,
                  UUID rubricVersionId, String modelProvider, String modelName, String modelVersion,
                  String promptProfileVersion, String evidencePackageKey, String evidencePackageVersion,
                  String evidencePackageHash, String producerVersion, String runtimeVersion,
                  JsonNode parameters, String parametersHash, String runHash, String status,
                  OffsetDateTime startedAt, OffsetDateTime completedAt, UUID createdBy, OffsetDateTime createdAt) {}

    record RunRecord(UUID runId, UUID workspaceId, String externalRunKey, String rubricKey,
                     UUID rubricVersionId, String modelProvider, String modelName, String modelVersion,
                     String promptProfileVersion, String evidencePackageKey, String evidencePackageVersion,
                     String evidencePackageHash, String producerVersion, String runtimeVersion,
                     JsonNode parameters, String parametersHash, String runHash, String status,
                     OffsetDateTime startedAt, OffsetDateTime completedAt) {}

    record StoredRun(RunRecord run, boolean replayed) {}

    record NewSnapshot(UUID snapshotId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                       String rubricKey, UUID rubricVersionId, String contextKey, JsonNode context,
                       String contextHash, String snapshotKind, Integer difficultyValue,
                       BigDecimal confidence, UUID runId, JsonNode modelContext, String snapshotHash,
                       UUID createdBy, OffsetDateTime createdAt) {}

    record SnapshotRecord(UUID snapshotId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                          String rubricKey, UUID rubricVersionId, String contextKey, JsonNode context,
                          String contextHash, String snapshotKind, Integer difficultyValue,
                          BigDecimal confidence, UUID runId, JsonNode modelContext, String snapshotHash,
                          UUID createdBy, OffsetDateTime createdAt) {}

    record StoredSnapshot(SnapshotRecord snapshot, boolean replayed) {}

    record NewState(UUID stateId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                    String rubricKey, UUID rubricVersionId, String contextKey, UUID currentSnapshotId,
                    UUID updatedBy, OffsetDateTime updatedAt) {}

    record StateRecord(UUID stateId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                       String rubricKey, UUID rubricVersionId, String contextKey, UUID currentSnapshotId,
                       UUID currentFeedbackId, long stateVersion, String status,
                       UUID updatedBy, OffsetDateTime updatedAt) {}

    record NewStateUpdate(UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey,
                          long expectedVersion, UUID rubricVersionId, UUID currentSnapshotId,
                          UUID currentFeedbackId, String status, UUID updatedBy, OffsetDateTime updatedAt) {}

    record NewFeedback(UUID feedbackId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                       String rubricKey, UUID rubricVersionId, String contextKey, UUID beforeSnapshotId,
                       UUID afterSnapshotId, String outcome, List<String> reasonCodes, String note,
                       UUID reviewerId, OffsetDateTime submittedAt, String clientMutationId,
                       String requestHash, long expectedStateVersion, List<DifficultyOperation> operations) {}

    record FeedbackRecord(UUID feedbackId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                          String rubricKey, UUID rubricVersionId, String contextKey, UUID beforeSnapshotId,
                          UUID afterSnapshotId, String outcome, List<String> reasonCodes, String note,
                          UUID reviewerId, OffsetDateTime submittedAt, String clientMutationId,
                          String requestHash, long expectedStateVersion, List<DifficultyOperation> operations) {}

    record NewGap(UUID gapCaseId, UUID workspaceId, UUID questionId, UUID questionRevisionId,
                  UUID feedbackId, String rubricKey, UUID rubricVersionId, String contextKey,
                  UUID beforeSnapshotId, String expectedDifficultyText, String explanation,
                  UUID createdBy, OffsetDateTime createdAt) {}

    record GapRecord(UUID gapCaseId, UUID feedbackId, String expectedDifficultyText,
                     String explanation, String status, UUID createdBy, OffsetDateTime createdAt) {}
}
