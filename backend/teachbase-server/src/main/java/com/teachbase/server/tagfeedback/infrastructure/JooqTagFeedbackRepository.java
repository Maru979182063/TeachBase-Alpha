package com.teachbase.server.tagfeedback.infrastructure;

import static com.teachbase.jooq.tables.QuestionTagFeedback.QUESTION_TAG_FEEDBACK;
import static com.teachbase.jooq.tables.QuestionTagSnapshot.QUESTION_TAG_SNAPSHOT;
import static com.teachbase.jooq.tables.QuestionTagSnapshotItem.QUESTION_TAG_SNAPSHOT_ITEM;
import static com.teachbase.jooq.tables.QuestionTagState.QUESTION_TAG_STATE;
import static com.teachbase.jooq.tables.TaggingRun.TAGGING_RUN;
import static com.teachbase.jooq.tables.TaxonomyGapCase.TAXONOMY_GAP_CASE;
import static com.teachbase.server.tagfeedback.api.TagFeedbackContracts.DerivedOperation;
import static com.teachbase.server.tagfeedback.application.TagFeedbackRepository.*;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.tagfeedback.application.TagFeedbackRepository;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：PostgreSQL 唯一键裁决幂等，CAS 裁决并发；失败事务由 Spring 统一回滚全部历史行。
 */
@Repository
class JooqTagFeedbackRepository implements TagFeedbackRepository {

    private final DSLContext database;
    private final ObjectMapper mapper;

    JooqTagFeedbackRepository(DSLContext database, ObjectMapper mapper) {
        this.database = database;
        this.mapper = mapper;
    }

    @Override
    public StoredRun insertOrReplayRun(NewRun run) {
        int inserted = database.insertInto(TAGGING_RUN)
                .set(TAGGING_RUN.TAGGING_RUN_ID, run.taggingRunId())
                .set(TAGGING_RUN.WORKSPACE_ID, run.workspaceId())
                .set(TAGGING_RUN.EXTERNAL_RUN_KEY, run.externalRunKey())
                .set(TAGGING_RUN.TAXONOMY_VERSION_ID, run.taxonomyVersionId())
                .set(TAGGING_RUN.MODEL_PROVIDER, run.modelProvider())
                .set(TAGGING_RUN.MODEL_NAME, run.modelName())
                .set(TAGGING_RUN.MODEL_VERSION, run.modelVersion())
                .set(TAGGING_RUN.PROMPT_PROFILE_VERSION, run.promptProfileVersion())
                .set(TAGGING_RUN.CANDIDATE_PACKAGE_KEY, run.candidatePackageKey())
                .set(TAGGING_RUN.CANDIDATE_PACKAGE_VERSION, run.candidatePackageVersion())
                .set(TAGGING_RUN.CANDIDATE_PACKAGE_HASH, run.candidatePackageHash())
                .set(TAGGING_RUN.PRODUCER_VERSION, run.producerVersion())
                .set(TAGGING_RUN.RUNTIME_VERSION, run.runtimeVersion())
                .set(TAGGING_RUN.PARAMETERS_JSON, json(run.parameters()))
                .set(TAGGING_RUN.PARAMETERS_HASH, run.parametersHash())
                .set(TAGGING_RUN.RUN_HASH, run.runHash())
                .set(TAGGING_RUN.STATUS, run.status())
                .set(TAGGING_RUN.STARTED_AT, run.startedAt())
                .set(TAGGING_RUN.COMPLETED_AT, run.completedAt())
                .set(TAGGING_RUN.CANONICAL_IMPORT_REQUEST_ID, run.canonicalImportRequestId())
                .set(TAGGING_RUN.CREATED_BY, run.createdBy())
                .set(TAGGING_RUN.CREATED_AT, run.createdAt())
                .onConflict(TAGGING_RUN.WORKSPACE_ID, TAGGING_RUN.EXTERNAL_RUN_KEY)
                .doNothing()
                .execute();
        RunRecord stored = database.selectFrom(TAGGING_RUN)
                .where(TAGGING_RUN.WORKSPACE_ID.eq(run.workspaceId()))
                .and(TAGGING_RUN.EXTERNAL_RUN_KEY.eq(run.externalRunKey()))
                .fetchOne(this::run);
        return new StoredRun(stored, inserted == 0);
    }

    @Override
    public Optional<RunRecord> findRun(UUID workspaceId, UUID taggingRunId) {
        return database.selectFrom(TAGGING_RUN)
                .where(TAGGING_RUN.WORKSPACE_ID.eq(workspaceId))
                .and(TAGGING_RUN.TAGGING_RUN_ID.eq(taggingRunId))
                .fetchOptional(this::run);
    }

    @Override
    public StoredSnapshot insertOrReplaySnapshot(
            NewSnapshot snapshot, List<SnapshotItemRecord> items) {
        int inserted = database.insertInto(QUESTION_TAG_SNAPSHOT)
                .set(QUESTION_TAG_SNAPSHOT.SNAPSHOT_ID, snapshot.snapshotId())
                .set(QUESTION_TAG_SNAPSHOT.WORKSPACE_ID, snapshot.workspaceId())
                .set(QUESTION_TAG_SNAPSHOT.QUESTION_ID, snapshot.questionId())
                .set(QUESTION_TAG_SNAPSHOT.QUESTION_REVISION_ID, snapshot.questionRevisionId())
                .set(QUESTION_TAG_SNAPSHOT.TAXONOMY_KEY, snapshot.taxonomyKey())
                .set(QUESTION_TAG_SNAPSHOT.TAXONOMY_VERSION_ID, snapshot.taxonomyVersionId())
                .set(QUESTION_TAG_SNAPSHOT.SNAPSHOT_KIND, snapshot.snapshotKind())
                .set(QUESTION_TAG_SNAPSHOT.LABEL_SET_HASH, snapshot.labelSetHash())
                .set(QUESTION_TAG_SNAPSHOT.SNAPSHOT_HASH, snapshot.snapshotHash())
                .set(QUESTION_TAG_SNAPSHOT.ITEM_COUNT, items.size())
                .set(QUESTION_TAG_SNAPSHOT.TAGGING_RUN_ID, snapshot.taggingRunId())
                .set(QUESTION_TAG_SNAPSHOT.MODEL_OUTPUT_CONTEXT_JSON, json(snapshot.modelOutputContext()))
                .set(QUESTION_TAG_SNAPSHOT.CREATED_BY, snapshot.createdBy())
                .set(QUESTION_TAG_SNAPSHOT.CREATED_AT, snapshot.createdAt())
                .onConflict(
                        QUESTION_TAG_SNAPSHOT.WORKSPACE_ID,
                        QUESTION_TAG_SNAPSHOT.QUESTION_REVISION_ID,
                        QUESTION_TAG_SNAPSHOT.TAXONOMY_VERSION_ID,
                        QUESTION_TAG_SNAPSHOT.SNAPSHOT_KIND,
                        QUESTION_TAG_SNAPSHOT.SNAPSHOT_HASH)
                .doNothing()
                .execute();
        SnapshotRecord stored;
        if (inserted == 1) {
            for (SnapshotItemRecord item : items) {
                database.insertInto(QUESTION_TAG_SNAPSHOT_ITEM)
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.SNAPSHOT_ITEM_ID, item.snapshotItemId())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.SNAPSHOT_ID, snapshot.snapshotId())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.WORKSPACE_ID, snapshot.workspaceId())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_VERSION_ID, snapshot.taxonomyVersionId())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.TAXONOMY_NODE_ID, item.taxonomyNodeId())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.RELATION_TYPE, item.relationType())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.POSITION_INDEX, item.positionIndex())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.CONFIDENCE, item.confidence())
                        .set(QUESTION_TAG_SNAPSHOT_ITEM.CANDIDATE_RANK, item.candidateRank())
                        .execute();
            }
            stored = findSnapshot(snapshot.workspaceId(), snapshot.snapshotId()).orElseThrow();
        } else {
            stored = database.selectFrom(QUESTION_TAG_SNAPSHOT)
                    .where(QUESTION_TAG_SNAPSHOT.WORKSPACE_ID.eq(snapshot.workspaceId()))
                    .and(QUESTION_TAG_SNAPSHOT.QUESTION_REVISION_ID.eq(snapshot.questionRevisionId()))
                    .and(QUESTION_TAG_SNAPSHOT.TAXONOMY_VERSION_ID.eq(snapshot.taxonomyVersionId()))
                    .and(QUESTION_TAG_SNAPSHOT.SNAPSHOT_KIND.eq(snapshot.snapshotKind()))
                    .and(QUESTION_TAG_SNAPSHOT.SNAPSHOT_HASH.eq(snapshot.snapshotHash()))
                    .fetchOne(this::snapshot);
        }
        return new StoredSnapshot(stored, inserted == 0);
    }

    @Override
    public Optional<SnapshotRecord> findSnapshot(UUID workspaceId, UUID snapshotId) {
        return database.selectFrom(QUESTION_TAG_SNAPSHOT)
                .where(QUESTION_TAG_SNAPSHOT.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_SNAPSHOT.SNAPSHOT_ID.eq(snapshotId))
                .fetchOptional(this::snapshot);
    }

    @Override
    public List<SnapshotItemRecord> findSnapshotItems(UUID snapshotId) {
        return database.selectFrom(QUESTION_TAG_SNAPSHOT_ITEM)
                .where(QUESTION_TAG_SNAPSHOT_ITEM.SNAPSHOT_ID.eq(snapshotId))
                .orderBy(
                        QUESTION_TAG_SNAPSHOT_ITEM.RELATION_TYPE,
                        QUESTION_TAG_SNAPSHOT_ITEM.POSITION_INDEX,
                        QUESTION_TAG_SNAPSHOT_ITEM.SNAPSHOT_ITEM_ID)
                .fetch(record -> new SnapshotItemRecord(
                        record.getSnapshotItemId(), record.getSnapshotId(), record.getWorkspaceId(),
                        record.getTaxonomyVersionId(), record.getTaxonomyNodeId(), record.getRelationType(),
                        record.getPositionIndex(), record.getConfidence(), record.getCandidateRank()));
    }

    @Override
    public StateRecord insertOrFindPendingState(NewState state) {
        database.insertInto(QUESTION_TAG_STATE)
                .set(QUESTION_TAG_STATE.STATE_ID, state.stateId())
                .set(QUESTION_TAG_STATE.WORKSPACE_ID, state.workspaceId())
                .set(QUESTION_TAG_STATE.QUESTION_ID, state.questionId())
                .set(QUESTION_TAG_STATE.QUESTION_REVISION_ID, state.questionRevisionId())
                .set(QUESTION_TAG_STATE.TAXONOMY_KEY, state.taxonomyKey())
                .set(QUESTION_TAG_STATE.TAXONOMY_VERSION_ID, state.taxonomyVersionId())
                .set(QUESTION_TAG_STATE.CURRENT_SNAPSHOT_ID, state.currentSnapshotId())
                .set(QUESTION_TAG_STATE.STATE_VERSION, 0L)
                .set(QUESTION_TAG_STATE.STATUS, "pending")
                .set(QUESTION_TAG_STATE.UPDATED_BY, state.updatedBy())
                .set(QUESTION_TAG_STATE.UPDATED_AT, state.updatedAt())
                .onConflict(
                        QUESTION_TAG_STATE.WORKSPACE_ID,
                        QUESTION_TAG_STATE.QUESTION_REVISION_ID,
                        QUESTION_TAG_STATE.TAXONOMY_KEY)
                .doNothing()
                .execute();
        return findState(state.workspaceId(), state.questionRevisionId(), state.taxonomyKey()).orElseThrow();
    }

    @Override
    public Optional<StateRecord> findState(
            UUID workspaceId, UUID questionRevisionId, String taxonomyKey) {
        return database.selectFrom(QUESTION_TAG_STATE)
                .where(QUESTION_TAG_STATE.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_STATE.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_TAG_STATE.TAXONOMY_KEY.eq(taxonomyKey))
                .fetchOptional(record -> new StateRecord(
                        record.getStateId(), record.getWorkspaceId(), record.getQuestionId(),
                        record.getQuestionRevisionId(), record.getTaxonomyKey(), record.getTaxonomyVersionId(),
                        record.getCurrentSnapshotId(), record.getCurrentFeedbackId(), record.getStateVersion(),
                        record.getStatus(), record.getUpdatedBy(), record.getUpdatedAt()));
    }

    @Override
    public void lockMutation(UUID workspaceId, String clientMutationId) {
        database.execute(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                workspaceId + ":" + clientMutationId);
    }

    @Override
    public Optional<FeedbackRecord> findFeedbackByMutation(
            UUID workspaceId, String clientMutationId) {
        return database.selectFrom(QUESTION_TAG_FEEDBACK)
                .where(QUESTION_TAG_FEEDBACK.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_FEEDBACK.CLIENT_MUTATION_ID.eq(clientMutationId))
                .fetchOptional(this::feedback);
    }

    @Override
    public void insertFeedback(NewFeedback feedback) {
        database.insertInto(QUESTION_TAG_FEEDBACK)
                .set(QUESTION_TAG_FEEDBACK.FEEDBACK_ID, feedback.feedbackId())
                .set(QUESTION_TAG_FEEDBACK.WORKSPACE_ID, feedback.workspaceId())
                .set(QUESTION_TAG_FEEDBACK.QUESTION_ID, feedback.questionId())
                .set(QUESTION_TAG_FEEDBACK.QUESTION_REVISION_ID, feedback.questionRevisionId())
                .set(QUESTION_TAG_FEEDBACK.TAXONOMY_KEY, feedback.taxonomyKey())
                .set(QUESTION_TAG_FEEDBACK.TAXONOMY_VERSION_ID, feedback.taxonomyVersionId())
                .set(QUESTION_TAG_FEEDBACK.BEFORE_SNAPSHOT_ID, feedback.beforeSnapshotId())
                .set(QUESTION_TAG_FEEDBACK.AFTER_SNAPSHOT_ID, feedback.afterSnapshotId())
                .set(QUESTION_TAG_FEEDBACK.OUTCOME, feedback.outcome())
                .set(QUESTION_TAG_FEEDBACK.REASON_CODES_JSON, json(feedback.reasonCodes()))
                .set(QUESTION_TAG_FEEDBACK.NOTE, feedback.note())
                .set(QUESTION_TAG_FEEDBACK.REVIEWER_ID, feedback.reviewerId())
                .set(QUESTION_TAG_FEEDBACK.SUBMITTED_AT, feedback.submittedAt())
                .set(QUESTION_TAG_FEEDBACK.CLIENT_MUTATION_ID, feedback.clientMutationId())
                .set(QUESTION_TAG_FEEDBACK.REQUEST_HASH, feedback.requestHash())
                .set(QUESTION_TAG_FEEDBACK.EXPECTED_STATE_VERSION, feedback.expectedStateVersion())
                .set(QUESTION_TAG_FEEDBACK.DERIVED_OPERATIONS_JSON, json(feedback.derivedOperations()))
                .execute();
    }

    @Override
    public boolean compareAndSetState(
            UUID workspaceId,
            UUID questionRevisionId,
            String taxonomyKey,
            long expectedVersion,
            UUID taxonomyVersionId,
            UUID currentSnapshotId,
            UUID currentFeedbackId,
            String status,
            UUID updatedBy,
            OffsetDateTime updatedAt) {
        return database.update(QUESTION_TAG_STATE)
                .set(QUESTION_TAG_STATE.TAXONOMY_VERSION_ID, taxonomyVersionId)
                .set(QUESTION_TAG_STATE.CURRENT_SNAPSHOT_ID, currentSnapshotId)
                .set(QUESTION_TAG_STATE.CURRENT_FEEDBACK_ID, currentFeedbackId)
                .set(QUESTION_TAG_STATE.STATE_VERSION, expectedVersion + 1)
                .set(QUESTION_TAG_STATE.STATUS, status)
                .set(QUESTION_TAG_STATE.UPDATED_BY, updatedBy)
                .set(QUESTION_TAG_STATE.UPDATED_AT, updatedAt)
                .where(QUESTION_TAG_STATE.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_STATE.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_TAG_STATE.TAXONOMY_KEY.eq(taxonomyKey))
                .and(QUESTION_TAG_STATE.STATE_VERSION.eq(expectedVersion))
                .execute() == 1;
    }

    @Override
    public UUID insertGap(NewGap gap) {
        database.insertInto(TAXONOMY_GAP_CASE)
                .set(TAXONOMY_GAP_CASE.GAP_CASE_ID, gap.gapCaseId())
                .set(TAXONOMY_GAP_CASE.WORKSPACE_ID, gap.workspaceId())
                .set(TAXONOMY_GAP_CASE.QUESTION_ID, gap.questionId())
                .set(TAXONOMY_GAP_CASE.QUESTION_REVISION_ID, gap.questionRevisionId())
                .set(TAXONOMY_GAP_CASE.FEEDBACK_ID, gap.feedbackId())
                .set(TAXONOMY_GAP_CASE.REPORTED_TAXONOMY_VERSION_ID, gap.reportedTaxonomyVersionId())
                .set(TAXONOMY_GAP_CASE.BEFORE_SNAPSHOT_ID, gap.beforeSnapshotId())
                .set(TAXONOMY_GAP_CASE.EXPECTED_LABEL_TEXT, gap.expectedLabelText())
                .set(TAXONOMY_GAP_CASE.TEACHER_EXPLANATION, gap.teacherExplanation())
                .set(TAXONOMY_GAP_CASE.STATUS, "open")
                .set(TAXONOMY_GAP_CASE.CREATED_BY, gap.createdBy())
                .set(TAXONOMY_GAP_CASE.CREATED_AT, gap.createdAt())
                .execute();
        return gap.gapCaseId();
    }

    @Override
    public Optional<GapRecord> findGapByFeedback(UUID feedbackId) {
        return database.selectFrom(TAXONOMY_GAP_CASE)
                .where(TAXONOMY_GAP_CASE.FEEDBACK_ID.eq(feedbackId))
                .fetchOptional(this::gap);
    }

    @Override
    public List<SnapshotRecord> findSnapshots(
            UUID workspaceId, UUID questionRevisionId, String taxonomyKey) {
        return database.selectFrom(QUESTION_TAG_SNAPSHOT)
                .where(QUESTION_TAG_SNAPSHOT.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_SNAPSHOT.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_TAG_SNAPSHOT.TAXONOMY_KEY.eq(taxonomyKey))
                .orderBy(QUESTION_TAG_SNAPSHOT.CREATED_AT, QUESTION_TAG_SNAPSHOT.SNAPSHOT_ID)
                .fetch(this::snapshot);
    }

    @Override
    public List<FeedbackRecord> findFeedback(
            UUID workspaceId, UUID questionRevisionId, String taxonomyKey) {
        return database.selectFrom(QUESTION_TAG_FEEDBACK)
                .where(QUESTION_TAG_FEEDBACK.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_TAG_FEEDBACK.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_TAG_FEEDBACK.TAXONOMY_KEY.eq(taxonomyKey))
                .orderBy(QUESTION_TAG_FEEDBACK.SUBMITTED_AT, QUESTION_TAG_FEEDBACK.FEEDBACK_ID)
                .fetch(this::feedback);
    }

    @Override
    public List<GapRecord> findGaps(UUID workspaceId, UUID questionRevisionId) {
        return database.selectFrom(TAXONOMY_GAP_CASE)
                .where(TAXONOMY_GAP_CASE.WORKSPACE_ID.eq(workspaceId))
                .and(TAXONOMY_GAP_CASE.QUESTION_REVISION_ID.eq(questionRevisionId))
                .orderBy(TAXONOMY_GAP_CASE.CREATED_AT, TAXONOMY_GAP_CASE.GAP_CASE_ID)
                .fetch(this::gap);
    }

    private RunRecord run(com.teachbase.jooq.tables.records.TaggingRunRecord record) {
        return new RunRecord(
                record.getTaggingRunId(), record.getWorkspaceId(), record.getExternalRunKey(),
                record.getTaxonomyVersionId(), record.getModelProvider(), record.getModelName(),
                record.getModelVersion(), record.getPromptProfileVersion(), record.getCandidatePackageKey(),
                record.getCandidatePackageVersion(), record.getCandidatePackageHash(), record.getProducerVersion(),
                record.getRuntimeVersion(), node(record.getParametersJson()), record.getParametersHash(),
                record.getRunHash(), record.getStatus(), record.getStartedAt(), record.getCompletedAt());
    }

    private SnapshotRecord snapshot(com.teachbase.jooq.tables.records.QuestionTagSnapshotRecord record) {
        return new SnapshotRecord(
                record.getSnapshotId(), record.getWorkspaceId(), record.getQuestionId(),
                record.getQuestionRevisionId(), record.getTaxonomyKey(), record.getTaxonomyVersionId(),
                record.getSnapshotKind(), record.getLabelSetHash(), record.getSnapshotHash(),
                record.getTaggingRunId(), node(record.getModelOutputContextJson()),
                record.getCreatedBy(), record.getCreatedAt());
    }

    private FeedbackRecord feedback(com.teachbase.jooq.tables.records.QuestionTagFeedbackRecord record) {
        return new FeedbackRecord(
                record.getFeedbackId(), record.getWorkspaceId(), record.getQuestionId(),
                record.getQuestionRevisionId(), record.getTaxonomyKey(), record.getTaxonomyVersionId(),
                record.getBeforeSnapshotId(), record.getAfterSnapshotId(), record.getOutcome(),
                list(record.getReasonCodesJson(), new TypeReference<List<String>>() {}), record.getNote(),
                record.getReviewerId(), record.getSubmittedAt(), record.getClientMutationId(),
                record.getRequestHash(), record.getExpectedStateVersion(),
                list(record.getDerivedOperationsJson(), new TypeReference<List<DerivedOperation>>() {}));
    }

    private GapRecord gap(com.teachbase.jooq.tables.records.TaxonomyGapCaseRecord record) {
        return new GapRecord(
                record.getGapCaseId(), record.getFeedbackId(), record.getExpectedLabelText(),
                record.getTeacherExplanation(), record.getStatus(), record.getCreatedBy(), record.getCreatedAt());
    }

    private JSON json(Object value) {
        try {
            return JSON.valueOf(mapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("tag_feedback_json_not_serializable", exception);
        }
    }

    private JsonNode node(JSON value) {
        try {
            return mapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("tag_feedback_json_corrupt", exception);
        }
    }

    private <T> T list(JSON value, TypeReference<T> type) {
        try {
            return mapper.readValue(value.data(), type);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("tag_feedback_json_corrupt", exception);
        }
    }
}
