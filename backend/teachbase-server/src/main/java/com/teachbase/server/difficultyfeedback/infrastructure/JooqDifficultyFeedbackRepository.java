package com.teachbase.server.difficultyfeedback.infrastructure;

import static com.teachbase.jooq.tables.DifficultyAssessmentRun.DIFFICULTY_ASSESSMENT_RUN;
import static com.teachbase.jooq.tables.DifficultyRubricGapCase.DIFFICULTY_RUBRIC_GAP_CASE;
import static com.teachbase.jooq.tables.DifficultyRubricVersion.DIFFICULTY_RUBRIC_VERSION;
import static com.teachbase.jooq.tables.QuestionDifficultyFeedback.QUESTION_DIFFICULTY_FEEDBACK;
import static com.teachbase.jooq.tables.QuestionDifficultySnapshot.QUESTION_DIFFICULTY_SNAPSHOT;
import static com.teachbase.jooq.tables.QuestionDifficultyState.QUESTION_DIFFICULTY_STATE;
import static com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackRepository.*;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.difficultyfeedback.api.DifficultyFeedbackContracts.DifficultyOperation;
import com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackRepository;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/** 中文维护说明：PostgreSQL 唯一键负责幂等，state_version 条件更新负责并发裁决。 */
@Repository
class JooqDifficultyFeedbackRepository implements DifficultyFeedbackRepository {

    private final DSLContext database;
    private final ObjectMapper mapper;

    JooqDifficultyFeedbackRepository(DSLContext database, ObjectMapper mapper) {
        this.database = database;
        this.mapper = mapper;
    }

    @Override
    public StoredRubric insertOrReplayRubric(NewRubric value) {
        int inserted = database.insertInto(DIFFICULTY_RUBRIC_VERSION)
                .set(DIFFICULTY_RUBRIC_VERSION.RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(DIFFICULTY_RUBRIC_VERSION.WORKSPACE_ID, value.workspaceId())
                .set(DIFFICULTY_RUBRIC_VERSION.RUBRIC_KEY, value.rubricKey())
                .set(DIFFICULTY_RUBRIC_VERSION.VERSION_CODE, value.versionCode())
                .set(DIFFICULTY_RUBRIC_VERSION.SUBJECT, value.subject())
                .set(DIFFICULTY_RUBRIC_VERSION.STAGE, value.stage())
                .set(DIFFICULTY_RUBRIC_VERSION.GRADE, value.grade())
                .set(DIFFICULTY_RUBRIC_VERSION.SCALE_MIN, (short) 1)
                .set(DIFFICULTY_RUBRIC_VERSION.SCALE_MAX, (short) 5)
                .set(DIFFICULTY_RUBRIC_VERSION.DEFINITIONS_JSON, json(value.definitions()))
                .set(DIFFICULTY_RUBRIC_VERSION.RUBRIC_HASH, value.rubricHash())
                .set(DIFFICULTY_RUBRIC_VERSION.STATUS, value.status())
                .set(DIFFICULTY_RUBRIC_VERSION.CREATED_BY, value.createdBy())
                .set(DIFFICULTY_RUBRIC_VERSION.CREATED_AT, value.createdAt())
                .onConflict(DIFFICULTY_RUBRIC_VERSION.WORKSPACE_ID,
                        DIFFICULTY_RUBRIC_VERSION.RUBRIC_KEY,
                        DIFFICULTY_RUBRIC_VERSION.VERSION_CODE)
                .doNothing().execute();
        RubricRecord stored = database.selectFrom(DIFFICULTY_RUBRIC_VERSION)
                .where(DIFFICULTY_RUBRIC_VERSION.WORKSPACE_ID.eq(value.workspaceId()))
                .and(DIFFICULTY_RUBRIC_VERSION.RUBRIC_KEY.eq(value.rubricKey()))
                .and(DIFFICULTY_RUBRIC_VERSION.VERSION_CODE.eq(value.versionCode()))
                .fetchOne(this::rubric);
        return new StoredRubric(stored, inserted == 0);
    }

    @Override
    public Optional<RubricRecord> findRubric(UUID workspaceId, UUID rubricVersionId) {
        return database.selectFrom(DIFFICULTY_RUBRIC_VERSION)
                .where(DIFFICULTY_RUBRIC_VERSION.WORKSPACE_ID.eq(workspaceId))
                .and(DIFFICULTY_RUBRIC_VERSION.RUBRIC_VERSION_ID.eq(rubricVersionId))
                .fetchOptional(this::rubric);
    }

    @Override
    public StoredRun insertOrReplayRun(NewRun value) {
        int inserted = database.insertInto(DIFFICULTY_ASSESSMENT_RUN)
                .set(DIFFICULTY_ASSESSMENT_RUN.ASSESSMENT_RUN_ID, value.runId())
                .set(DIFFICULTY_ASSESSMENT_RUN.WORKSPACE_ID, value.workspaceId())
                .set(DIFFICULTY_ASSESSMENT_RUN.EXTERNAL_RUN_KEY, value.externalRunKey())
                .set(DIFFICULTY_ASSESSMENT_RUN.RUBRIC_KEY, value.rubricKey())
                .set(DIFFICULTY_ASSESSMENT_RUN.RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(DIFFICULTY_ASSESSMENT_RUN.MODEL_PROVIDER, value.modelProvider())
                .set(DIFFICULTY_ASSESSMENT_RUN.MODEL_NAME, value.modelName())
                .set(DIFFICULTY_ASSESSMENT_RUN.MODEL_VERSION, value.modelVersion())
                .set(DIFFICULTY_ASSESSMENT_RUN.PROMPT_PROFILE_VERSION, value.promptProfileVersion())
                .set(DIFFICULTY_ASSESSMENT_RUN.EVIDENCE_PACKAGE_KEY, value.evidencePackageKey())
                .set(DIFFICULTY_ASSESSMENT_RUN.EVIDENCE_PACKAGE_VERSION, value.evidencePackageVersion())
                .set(DIFFICULTY_ASSESSMENT_RUN.EVIDENCE_PACKAGE_HASH, value.evidencePackageHash())
                .set(DIFFICULTY_ASSESSMENT_RUN.PRODUCER_VERSION, value.producerVersion())
                .set(DIFFICULTY_ASSESSMENT_RUN.RUNTIME_VERSION, value.runtimeVersion())
                .set(DIFFICULTY_ASSESSMENT_RUN.PARAMETERS_JSON, json(value.parameters()))
                .set(DIFFICULTY_ASSESSMENT_RUN.PARAMETERS_HASH, value.parametersHash())
                .set(DIFFICULTY_ASSESSMENT_RUN.RUN_HASH, value.runHash())
                .set(DIFFICULTY_ASSESSMENT_RUN.STATUS, value.status())
                .set(DIFFICULTY_ASSESSMENT_RUN.STARTED_AT, value.startedAt())
                .set(DIFFICULTY_ASSESSMENT_RUN.COMPLETED_AT, value.completedAt())
                .set(DIFFICULTY_ASSESSMENT_RUN.CREATED_BY, value.createdBy())
                .set(DIFFICULTY_ASSESSMENT_RUN.CREATED_AT, value.createdAt())
                .onConflict(DIFFICULTY_ASSESSMENT_RUN.WORKSPACE_ID,
                        DIFFICULTY_ASSESSMENT_RUN.EXTERNAL_RUN_KEY)
                .doNothing().execute();
        RunRecord stored = database.selectFrom(DIFFICULTY_ASSESSMENT_RUN)
                .where(DIFFICULTY_ASSESSMENT_RUN.WORKSPACE_ID.eq(value.workspaceId()))
                .and(DIFFICULTY_ASSESSMENT_RUN.EXTERNAL_RUN_KEY.eq(value.externalRunKey()))
                .fetchOne(this::run);
        return new StoredRun(stored, inserted == 0);
    }

    @Override
    public Optional<RunRecord> findRun(UUID workspaceId, UUID runId) {
        return database.selectFrom(DIFFICULTY_ASSESSMENT_RUN)
                .where(DIFFICULTY_ASSESSMENT_RUN.WORKSPACE_ID.eq(workspaceId))
                .and(DIFFICULTY_ASSESSMENT_RUN.ASSESSMENT_RUN_ID.eq(runId))
                .fetchOptional(this::run);
    }

    @Override
    public StoredSnapshot insertOrReplaySnapshot(NewSnapshot value) {
        int inserted = database.insertInto(QUESTION_DIFFICULTY_SNAPSHOT)
                .set(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_ID, value.snapshotId())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.WORKSPACE_ID, value.workspaceId())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.QUESTION_ID, value.questionId())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.QUESTION_REVISION_ID, value.questionRevisionId())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.RUBRIC_KEY, value.rubricKey())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_KEY, value.contextKey())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_JSON, json(value.context()))
                .set(QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_HASH, value.contextHash())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_KIND, value.snapshotKind())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.DIFFICULTY_VALUE,
                        value.difficultyValue() == null ? null : value.difficultyValue().shortValue())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.CONFIDENCE, value.confidence())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.ASSESSMENT_RUN_ID, value.runId())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.MODEL_OUTPUT_CONTEXT_JSON, json(value.modelContext()))
                .set(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_HASH, value.snapshotHash())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.CREATED_BY, value.createdBy())
                .set(QUESTION_DIFFICULTY_SNAPSHOT.CREATED_AT, value.createdAt())
                .onConflict(QUESTION_DIFFICULTY_SNAPSHOT.WORKSPACE_ID,
                        QUESTION_DIFFICULTY_SNAPSHOT.QUESTION_REVISION_ID,
                        QUESTION_DIFFICULTY_SNAPSHOT.RUBRIC_VERSION_ID,
                        QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_KEY,
                        QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_KIND,
                        QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_HASH)
                .doNothing().execute();
        SnapshotRecord stored = inserted == 1
                ? findSnapshot(value.workspaceId(), value.snapshotId()).orElseThrow()
                : database.selectFrom(QUESTION_DIFFICULTY_SNAPSHOT)
                        .where(QUESTION_DIFFICULTY_SNAPSHOT.WORKSPACE_ID.eq(value.workspaceId()))
                        .and(QUESTION_DIFFICULTY_SNAPSHOT.QUESTION_REVISION_ID.eq(value.questionRevisionId()))
                        .and(QUESTION_DIFFICULTY_SNAPSHOT.RUBRIC_VERSION_ID.eq(value.rubricVersionId()))
                        .and(QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_KEY.eq(value.contextKey()))
                        .and(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_KIND.eq(value.snapshotKind()))
                        .and(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_HASH.eq(value.snapshotHash()))
                        .fetchOne(this::snapshot);
        return new StoredSnapshot(stored, inserted == 0);
    }

    @Override
    public Optional<SnapshotRecord> findSnapshot(UUID workspaceId, UUID snapshotId) {
        return database.selectFrom(QUESTION_DIFFICULTY_SNAPSHOT)
                .where(QUESTION_DIFFICULTY_SNAPSHOT.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_ID.eq(snapshotId))
                .fetchOptional(this::snapshot);
    }

    @Override
    public List<SnapshotRecord> findSnapshots(
            UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey) {
        return database.selectFrom(QUESTION_DIFFICULTY_SNAPSHOT)
                .where(QUESTION_DIFFICULTY_SNAPSHOT.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_DIFFICULTY_SNAPSHOT.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_DIFFICULTY_SNAPSHOT.RUBRIC_KEY.eq(rubricKey))
                .and(QUESTION_DIFFICULTY_SNAPSHOT.CONTEXT_KEY.eq(contextKey))
                .orderBy(QUESTION_DIFFICULTY_SNAPSHOT.CREATED_AT, QUESTION_DIFFICULTY_SNAPSHOT.SNAPSHOT_ID)
                .fetch(this::snapshot);
    }

    @Override
    public StateRecord insertOrFindPendingState(NewState value) {
        database.insertInto(QUESTION_DIFFICULTY_STATE)
                .set(QUESTION_DIFFICULTY_STATE.STATE_ID, value.stateId())
                .set(QUESTION_DIFFICULTY_STATE.WORKSPACE_ID, value.workspaceId())
                .set(QUESTION_DIFFICULTY_STATE.QUESTION_ID, value.questionId())
                .set(QUESTION_DIFFICULTY_STATE.QUESTION_REVISION_ID, value.questionRevisionId())
                .set(QUESTION_DIFFICULTY_STATE.RUBRIC_KEY, value.rubricKey())
                .set(QUESTION_DIFFICULTY_STATE.RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(QUESTION_DIFFICULTY_STATE.CONTEXT_KEY, value.contextKey())
                .set(QUESTION_DIFFICULTY_STATE.CURRENT_SNAPSHOT_ID, value.currentSnapshotId())
                .set(QUESTION_DIFFICULTY_STATE.STATE_VERSION, 0L)
                .set(QUESTION_DIFFICULTY_STATE.STATUS, "pending")
                .set(QUESTION_DIFFICULTY_STATE.UPDATED_BY, value.updatedBy())
                .set(QUESTION_DIFFICULTY_STATE.UPDATED_AT, value.updatedAt())
                .onConflict(QUESTION_DIFFICULTY_STATE.WORKSPACE_ID,
                        QUESTION_DIFFICULTY_STATE.QUESTION_REVISION_ID,
                        QUESTION_DIFFICULTY_STATE.RUBRIC_KEY,
                        QUESTION_DIFFICULTY_STATE.CONTEXT_KEY)
                .doNothing().execute();
        return findState(value.workspaceId(), value.questionRevisionId(), value.rubricKey(), value.contextKey())
                .orElseThrow();
    }

    @Override
    public Optional<StateRecord> findState(
            UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey) {
        return database.selectFrom(QUESTION_DIFFICULTY_STATE)
                .where(QUESTION_DIFFICULTY_STATE.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_DIFFICULTY_STATE.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_DIFFICULTY_STATE.RUBRIC_KEY.eq(rubricKey))
                .and(QUESTION_DIFFICULTY_STATE.CONTEXT_KEY.eq(contextKey))
                .fetchOptional(this::state);
    }

    @Override
    public void lockMutation(UUID workspaceId, String clientMutationId) {
        database.execute("select pg_advisory_xact_lock(hashtextextended(?, 0))",
                workspaceId + ":difficulty:" + clientMutationId);
    }

    @Override
    public Optional<FeedbackRecord> findFeedbackByMutation(UUID workspaceId, String clientMutationId) {
        return database.selectFrom(QUESTION_DIFFICULTY_FEEDBACK)
                .where(QUESTION_DIFFICULTY_FEEDBACK.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_DIFFICULTY_FEEDBACK.CLIENT_MUTATION_ID.eq(clientMutationId))
                .fetchOptional(this::feedback);
    }

    @Override
    public void insertFeedback(NewFeedback value) {
        database.insertInto(QUESTION_DIFFICULTY_FEEDBACK)
                .set(QUESTION_DIFFICULTY_FEEDBACK.FEEDBACK_ID, value.feedbackId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.WORKSPACE_ID, value.workspaceId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.QUESTION_ID, value.questionId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.QUESTION_REVISION_ID, value.questionRevisionId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.RUBRIC_KEY, value.rubricKey())
                .set(QUESTION_DIFFICULTY_FEEDBACK.RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.CONTEXT_KEY, value.contextKey())
                .set(QUESTION_DIFFICULTY_FEEDBACK.BEFORE_SNAPSHOT_ID, value.beforeSnapshotId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.AFTER_SNAPSHOT_ID, value.afterSnapshotId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.OUTCOME, value.outcome())
                .set(QUESTION_DIFFICULTY_FEEDBACK.REASON_CODES_JSON, json(value.reasonCodes()))
                .set(QUESTION_DIFFICULTY_FEEDBACK.NOTE, value.note())
                .set(QUESTION_DIFFICULTY_FEEDBACK.REVIEWER_ID, value.reviewerId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.SUBMITTED_AT, value.submittedAt())
                .set(QUESTION_DIFFICULTY_FEEDBACK.CLIENT_MUTATION_ID, value.clientMutationId())
                .set(QUESTION_DIFFICULTY_FEEDBACK.REQUEST_HASH, value.requestHash())
                .set(QUESTION_DIFFICULTY_FEEDBACK.EXPECTED_STATE_VERSION, value.expectedStateVersion())
                .set(QUESTION_DIFFICULTY_FEEDBACK.DERIVED_OPERATIONS_JSON, json(value.operations()))
                .execute();
    }

    @Override
    public boolean compareAndSetState(NewStateUpdate value) {
        return database.update(QUESTION_DIFFICULTY_STATE)
                .set(QUESTION_DIFFICULTY_STATE.RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(QUESTION_DIFFICULTY_STATE.CURRENT_SNAPSHOT_ID, value.currentSnapshotId())
                .set(QUESTION_DIFFICULTY_STATE.CURRENT_FEEDBACK_ID, value.currentFeedbackId())
                .set(QUESTION_DIFFICULTY_STATE.STATE_VERSION, value.expectedVersion() + 1)
                .set(QUESTION_DIFFICULTY_STATE.STATUS, value.status())
                .set(QUESTION_DIFFICULTY_STATE.UPDATED_BY, value.updatedBy())
                .set(QUESTION_DIFFICULTY_STATE.UPDATED_AT, value.updatedAt())
                .where(QUESTION_DIFFICULTY_STATE.WORKSPACE_ID.eq(value.workspaceId()))
                .and(QUESTION_DIFFICULTY_STATE.QUESTION_REVISION_ID.eq(value.questionRevisionId()))
                .and(QUESTION_DIFFICULTY_STATE.RUBRIC_KEY.eq(value.rubricKey()))
                .and(QUESTION_DIFFICULTY_STATE.CONTEXT_KEY.eq(value.contextKey()))
                .and(QUESTION_DIFFICULTY_STATE.STATE_VERSION.eq(value.expectedVersion()))
                .execute() == 1;
    }

    @Override
    public UUID insertGap(NewGap value) {
        database.insertInto(DIFFICULTY_RUBRIC_GAP_CASE)
                .set(DIFFICULTY_RUBRIC_GAP_CASE.GAP_CASE_ID, value.gapCaseId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.WORKSPACE_ID, value.workspaceId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.QUESTION_ID, value.questionId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.QUESTION_REVISION_ID, value.questionRevisionId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.FEEDBACK_ID, value.feedbackId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.RUBRIC_KEY, value.rubricKey())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.REPORTED_RUBRIC_VERSION_ID, value.rubricVersionId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.CONTEXT_KEY, value.contextKey())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.BEFORE_SNAPSHOT_ID, value.beforeSnapshotId())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.EXPECTED_DIFFICULTY_TEXT, value.expectedDifficultyText())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.TEACHER_EXPLANATION, value.explanation())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.STATUS, "open")
                .set(DIFFICULTY_RUBRIC_GAP_CASE.CREATED_BY, value.createdBy())
                .set(DIFFICULTY_RUBRIC_GAP_CASE.CREATED_AT, value.createdAt())
                .execute();
        return value.gapCaseId();
    }

    @Override
    public Optional<GapRecord> findGapByFeedback(UUID feedbackId) {
        return database.selectFrom(DIFFICULTY_RUBRIC_GAP_CASE)
                .where(DIFFICULTY_RUBRIC_GAP_CASE.FEEDBACK_ID.eq(feedbackId))
                .fetchOptional(this::gap);
    }

    @Override
    public List<FeedbackRecord> findFeedback(
            UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey) {
        return database.selectFrom(QUESTION_DIFFICULTY_FEEDBACK)
                .where(QUESTION_DIFFICULTY_FEEDBACK.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_DIFFICULTY_FEEDBACK.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(QUESTION_DIFFICULTY_FEEDBACK.RUBRIC_KEY.eq(rubricKey))
                .and(QUESTION_DIFFICULTY_FEEDBACK.CONTEXT_KEY.eq(contextKey))
                .orderBy(QUESTION_DIFFICULTY_FEEDBACK.SUBMITTED_AT, QUESTION_DIFFICULTY_FEEDBACK.FEEDBACK_ID)
                .fetch(this::feedback);
    }

    @Override
    public List<GapRecord> findGaps(
            UUID workspaceId, UUID questionRevisionId, String rubricKey, String contextKey) {
        return database.selectFrom(DIFFICULTY_RUBRIC_GAP_CASE)
                .where(DIFFICULTY_RUBRIC_GAP_CASE.WORKSPACE_ID.eq(workspaceId))
                .and(DIFFICULTY_RUBRIC_GAP_CASE.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(DIFFICULTY_RUBRIC_GAP_CASE.RUBRIC_KEY.eq(rubricKey))
                .and(DIFFICULTY_RUBRIC_GAP_CASE.CONTEXT_KEY.eq(contextKey))
                .orderBy(DIFFICULTY_RUBRIC_GAP_CASE.CREATED_AT, DIFFICULTY_RUBRIC_GAP_CASE.GAP_CASE_ID)
                .fetch(this::gap);
    }

    private RubricRecord rubric(com.teachbase.jooq.tables.records.DifficultyRubricVersionRecord record) {
        return new RubricRecord(record.getRubricVersionId(), record.getWorkspaceId(), record.getRubricKey(),
                record.getVersionCode(), record.getSubject(), record.getStage(), record.getGrade(),
                node(record.getDefinitionsJson()), record.getRubricHash(), record.getStatus(),
                record.getCreatedBy(), record.getCreatedAt());
    }

    private RunRecord run(com.teachbase.jooq.tables.records.DifficultyAssessmentRunRecord record) {
        return new RunRecord(record.getAssessmentRunId(), record.getWorkspaceId(), record.getExternalRunKey(),
                record.getRubricKey(), record.getRubricVersionId(), record.getModelProvider(), record.getModelName(),
                record.getModelVersion(), record.getPromptProfileVersion(), record.getEvidencePackageKey(),
                record.getEvidencePackageVersion(), record.getEvidencePackageHash(), record.getProducerVersion(),
                record.getRuntimeVersion(), node(record.getParametersJson()), record.getParametersHash(),
                record.getRunHash(), record.getStatus(), record.getStartedAt(), record.getCompletedAt());
    }

    private SnapshotRecord snapshot(com.teachbase.jooq.tables.records.QuestionDifficultySnapshotRecord record) {
        return new SnapshotRecord(record.getSnapshotId(), record.getWorkspaceId(), record.getQuestionId(),
                record.getQuestionRevisionId(), record.getRubricKey(), record.getRubricVersionId(),
                record.getContextKey(), node(record.getContextJson()), record.getContextHash(),
                record.getSnapshotKind(), record.getDifficultyValue() == null ? null : record.getDifficultyValue().intValue(),
                record.getConfidence(), record.getAssessmentRunId(), node(record.getModelOutputContextJson()),
                record.getSnapshotHash(), record.getCreatedBy(), record.getCreatedAt());
    }

    private StateRecord state(com.teachbase.jooq.tables.records.QuestionDifficultyStateRecord record) {
        return new StateRecord(record.getStateId(), record.getWorkspaceId(), record.getQuestionId(),
                record.getQuestionRevisionId(), record.getRubricKey(), record.getRubricVersionId(),
                record.getContextKey(), record.getCurrentSnapshotId(), record.getCurrentFeedbackId(),
                record.getStateVersion(), record.getStatus(), record.getUpdatedBy(), record.getUpdatedAt());
    }

    private FeedbackRecord feedback(com.teachbase.jooq.tables.records.QuestionDifficultyFeedbackRecord record) {
        return new FeedbackRecord(record.getFeedbackId(), record.getWorkspaceId(), record.getQuestionId(),
                record.getQuestionRevisionId(), record.getRubricKey(), record.getRubricVersionId(),
                record.getContextKey(), record.getBeforeSnapshotId(), record.getAfterSnapshotId(),
                record.getOutcome(), list(record.getReasonCodesJson(), new TypeReference<List<String>>() {}),
                record.getNote(), record.getReviewerId(), record.getSubmittedAt(), record.getClientMutationId(),
                record.getRequestHash(), record.getExpectedStateVersion(),
                list(record.getDerivedOperationsJson(), new TypeReference<List<DifficultyOperation>>() {}));
    }

    private GapRecord gap(com.teachbase.jooq.tables.records.DifficultyRubricGapCaseRecord record) {
        return new GapRecord(record.getGapCaseId(), record.getFeedbackId(), record.getExpectedDifficultyText(),
                record.getTeacherExplanation(), record.getStatus(), record.getCreatedBy(), record.getCreatedAt());
    }

    private JSON json(Object value) {
        try {
            return JSON.valueOf(mapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("difficulty_feedback_json_not_serializable", exception);
        }
    }

    private JsonNode node(JSON value) {
        try {
            return mapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("difficulty_feedback_json_corrupt", exception);
        }
    }

    private <T> T list(JSON value, TypeReference<T> type) {
        try {
            return mapper.readValue(value.data(), type);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("difficulty_feedback_json_corrupt", exception);
        }
    }
}
