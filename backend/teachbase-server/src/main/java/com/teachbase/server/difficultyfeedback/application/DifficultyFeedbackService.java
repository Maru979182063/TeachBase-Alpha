package com.teachbase.server.difficultyfeedback.application;

import static com.teachbase.server.difficultyfeedback.api.DifficultyFeedbackContracts.*;
import static com.teachbase.server.difficultyfeedback.application.DifficultyFeedbackRepository.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：难度变化只推进 question_difficulty_state，不创建题目 revision，也不调用 Review writer。
 */
@Service
public class DifficultyFeedbackService {

    private static final Set<String> WRITE_ROLES = Set.of("owner", "admin", "editor", "reviewer");

    private final DifficultyFeedbackRepository repository;
    private final DifficultyFeedbackHasher hasher;
    private final WorkspaceDirectory workspaces;
    private final QuestionRevisionDirectory questions;
    private final AuditTrail audit;
    private final ObjectMapper mapper;

    public DifficultyFeedbackService(
            DifficultyFeedbackRepository repository,
            DifficultyFeedbackHasher hasher,
            WorkspaceDirectory workspaces,
            QuestionRevisionDirectory questions,
            AuditTrail audit,
            ObjectMapper mapper) {
        this.repository = repository;
        this.hasher = hasher;
        this.workspaces = workspaces;
        this.questions = questions;
        this.audit = audit;
        this.mapper = mapper;
    }

    @Transactional
    public RegisterRubricResponse registerRubric(RegisterRubricRequest request) {
        requireWritableMember(request.workspaceId(), request.actorUserId());
        authorizeTeachingScope(request.workspaceId(), request.actorUserId(), request.subject(), request.stage());
        if (!request.definitions().isObject() || request.definitions().size() != 5) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_RUBRIC_FIVE_DEFINITIONS_REQUIRED");
        }
        for (int value = 1; value <= 5; value++) {
            JsonNode definition = request.definitions().path(String.valueOf(value));
            if (!definition.isTextual() || definition.asText().isBlank()) {
                throw new DifficultyFeedbackValidationException("DIFFICULTY_RUBRIC_FIVE_DEFINITIONS_REQUIRED");
            }
        }
        if (!Set.of("active", "retired").contains(request.status())) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_RUBRIC_STATUS_INVALID");
        }
        var hashes = hasher.hashRubric(request);
        var stored = repository.insertOrReplayRubric(new NewRubric(
                UUID.randomUUID(), request.workspaceId(), request.rubricKey(), request.versionCode(),
                request.subject(), request.stage(), clean(request.grade()), hashes.definitions(),
                hashes.rubricHash(), request.status(), request.actorUserId(), OffsetDateTime.now()));
        if (!stored.rubric().rubricHash().equals(hashes.rubricHash())) {
            throw new DifficultyFeedbackConflictException("DIFFICULTY_RUBRIC_PAYLOAD_CONFLICT");
        }
        if (!stored.replayed()) {
            recordAudit(request.workspaceId(), request.actorUserId(), "difficulty_rubric_registered",
                    "difficulty_rubric_version", stored.rubric().rubricVersionId(),
                    Map.of("rubricKey", request.rubricKey(), "rubricHash", hashes.rubricHash()));
        }
        return new RegisterRubricResponse(stored.rubric().rubricVersionId(), stored.replayed(),
                stored.rubric().rubricHash(), stored.rubric().status());
    }

    @Transactional
    public RegisterAssessmentRunResponse registerRun(RegisterAssessmentRunRequest request) {
        validateHash(request.evidencePackageHash(), "DIFFICULTY_EVIDENCE_HASH_INVALID");
        if (!Set.of("completed", "failed").contains(request.status())
                || request.completedAt().isBefore(request.startedAt())) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_FROZEN_RUN_INVALID");
        }
        if (!request.parameters().isObject()) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_RUN_PARAMETERS_OBJECT_REQUIRED");
        }
        requireWritableMember(request.workspaceId(), request.actorUserId());
        RubricRecord rubric = rubric(request.workspaceId(), request.rubricVersionId());
        authorizeTeachingScope(request.workspaceId(), request.actorUserId(), rubric.subject(), rubric.stage());
        var hashes = hasher.hashRun(request, rubric.rubricKey());
        var stored = repository.insertOrReplayRun(new NewRun(
                UUID.randomUUID(), request.workspaceId(), request.externalRunKey(), rubric.rubricKey(),
                rubric.rubricVersionId(), request.modelProvider(), request.modelName(), request.modelVersion(),
                request.promptProfileVersion(), request.evidencePackageKey(), request.evidencePackageVersion(),
                request.evidencePackageHash(), request.producerVersion(), request.runtimeVersion(),
                hashes.parameters(), hashes.parametersHash(), hashes.runHash(), request.status(),
                request.startedAt(), request.completedAt(), request.actorUserId(), OffsetDateTime.now()));
        if (!stored.run().runHash().equals(hashes.runHash())) {
            throw new DifficultyFeedbackConflictException("DIFFICULTY_RUN_PAYLOAD_CONFLICT");
        }
        if (!stored.replayed()) {
            recordAudit(request.workspaceId(), request.actorUserId(), "difficulty_run_registered",
                    "difficulty_assessment_run", stored.run().runId(),
                    Map.of("externalRunKey", request.externalRunKey(), "runHash", hashes.runHash()));
        }
        return new RegisterAssessmentRunResponse(
                stored.run().runId(), stored.replayed(), stored.run().runHash(), stored.run().parametersHash());
    }

    @Transactional
    public RegisterDifficultySuggestionResponse registerSuggestion(
            UUID runId, RegisterDifficultySuggestionRequest request) {
        requireWritableMember(request.workspaceId(), request.actorUserId());
        RunRecord run = repository.findRun(request.workspaceId(), runId)
                .orElseThrow(() -> new DifficultyFeedbackNotFoundException("DIFFICULTY_RUN_NOT_FOUND"));
        if (!run.status().equals("completed")) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_COMPLETED_RUN_REQUIRED");
        }
        RubricRecord rubric = rubric(request.workspaceId(), run.rubricVersionId());
        QuestionRevisionDescriptor question = question(request.workspaceId(), request.questionRevisionId());
        requireRubricContext(rubric, question);
        authorizeTeachingScope(request.workspaceId(), request.actorUserId(), question.subject(), question.stage());
        if (!rubric.status().equals("active")) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_RUBRIC_NOT_ACTIVE");
        }
        if (!request.context().isObject() || !request.modelOutputContext().isObject()) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_CONTEXT_OBJECT_REQUIRED");
        }
        requireEvaluationContext(request.context(), question);
        if (request.confidence().compareTo(BigDecimal.ZERO) < 0
                || request.confidence().compareTo(BigDecimal.ONE) > 0) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_CONFIDENCE_INVALID");
        }
        JsonNode context = hasher.canonical(request.context());
        JsonNode modelContext = hasher.canonical(request.modelOutputContext());
        String contextHash = hasher.contextHash(context);
        String snapshotHash = hasher.snapshotHash(
                "SYSTEM_SUGGESTION", rubric.rubricVersionId(), request.contextKey(), contextHash,
                request.difficultyValue(), request.confidence(), run.runId(), request.actorUserId(), modelContext);
        OffsetDateTime now = OffsetDateTime.now();
        var stored = repository.insertOrReplaySnapshot(new NewSnapshot(
                UUID.randomUUID(), request.workspaceId(), question.questionId(), question.questionRevisionId(),
                rubric.rubricKey(), rubric.rubricVersionId(), request.contextKey(), context, contextHash,
                "SYSTEM_SUGGESTION", request.difficultyValue(), request.confidence(), run.runId(),
                modelContext, snapshotHash, request.actorUserId(), now));
        StateRecord state = repository.insertOrFindPendingState(new NewState(
                UUID.randomUUID(), request.workspaceId(), question.questionId(), question.questionRevisionId(),
                rubric.rubricKey(), rubric.rubricVersionId(), request.contextKey(),
                stored.snapshot().snapshotId(), request.actorUserId(), now));
        SnapshotRecord established = repository.findSnapshot(
                request.workspaceId(), state.currentSnapshotId()).orElseThrow();
        if (!established.contextHash().equals(contextHash)) {
            throw stateConflict("DIFFICULTY_CONTEXT_KEY_PAYLOAD_CONFLICT", state);
        }
        if (!state.rubricVersionId().equals(rubric.rubricVersionId())) {
            throw stateConflict("DIFFICULTY_RUBRIC_VERSION_CONFLICT", state);
        }
        if (!stored.replayed()) {
            recordAudit(request.workspaceId(), request.actorUserId(), "difficulty_suggestion_registered",
                    "question_difficulty_snapshot", stored.snapshot().snapshotId(),
                    Map.of("questionRevisionId", question.questionRevisionId(), "snapshotHash", snapshotHash));
        }
        return new RegisterDifficultySuggestionResponse(
                stored.snapshot().snapshotId(), state.stateId(), state.stateVersion(), state.status(),
                stored.snapshot().snapshotHash(), stored.replayed());
    }

    @Transactional(readOnly = true)
    public DifficultyReviewContextResponse reviewContext(
            UUID questionRevisionId, UUID workspaceId, UUID actorUserId,
            String rubricKey, String contextKey) {
        requireWritableMember(workspaceId, actorUserId);
        QuestionRevisionDescriptor question = question(workspaceId, questionRevisionId);
        authorizeTeachingScope(workspaceId, actorUserId, question.subject(), question.stage());
        StateRecord state = state(workspaceId, questionRevisionId, rubricKey, contextKey);
        SnapshotRecord current = repository.findSnapshot(workspaceId, state.currentSnapshotId()).orElseThrow();
        SnapshotRecord system = repository.findSnapshots(workspaceId, questionRevisionId, rubricKey, contextKey)
                .stream().filter(value -> value.snapshotKind().equals("SYSTEM_SUGGESTION"))
                .max(Comparator.comparing(SnapshotRecord::createdAt)
                        .thenComparing(value -> value.snapshotId().toString()))
                .orElseThrow(() -> new DifficultyFeedbackNotFoundException("DIFFICULTY_SUGGESTION_NOT_FOUND"));
        RunRecord run = repository.findRun(workspaceId, system.runId()).orElseThrow();
        return new DifficultyReviewContextResponse(
                questionRevisionId, rubricKey, state.rubricVersionId(), contextKey,
                state.stateVersion(), state.status(), snapshotView(system), snapshotView(current),
                runView(run), questionSummary(question));
    }

    @Transactional
    public SubmitDifficultyFeedbackResponse submit(
            UUID questionRevisionId, SubmitDifficultyFeedbackRequest request) {
        if (request.expectedStateVersion() < 0) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_STATE_VERSION_INVALID");
        }
        requireWritableMember(request.workspaceId(), request.actorUserId());
        QuestionRevisionDescriptor question = question(request.workspaceId(), questionRevisionId);
        authorizeTeachingScope(request.workspaceId(), request.actorUserId(), question.subject(), question.stage());
        String requestHash = hasher.feedbackRequestHash(questionRevisionId, request);
        repository.lockMutation(request.workspaceId(), request.clientMutationId());
        var replay = repository.findFeedbackByMutation(request.workspaceId(), request.clientMutationId());
        if (replay.isPresent()) {
            if (!replay.get().requestHash().equals(requestHash)) {
                throw new DifficultyFeedbackConflictException("DIFFICULTY_IDEMPOTENCY_PAYLOAD_CONFLICT");
            }
            return replayResponse(replay.get());
        }
        StateRecord state = state(request.workspaceId(), questionRevisionId,
                request.rubricKey(), request.contextKey());
        if (!state.rubricVersionId().equals(request.rubricVersionId())) {
            throw stateConflict("DIFFICULTY_RUBRIC_VERSION_CONFLICT", state);
        }
        if (!state.currentSnapshotId().equals(request.beforeSnapshotId())) {
            throw stateConflict("DIFFICULTY_BEFORE_SNAPSHOT_CONFLICT", state);
        }
        if (state.stateVersion() != request.expectedStateVersion()) {
            throw stateConflict("DIFFICULTY_STATE_VERSION_CONFLICT", state);
        }
        RubricRecord rubric = rubric(request.workspaceId(), request.rubricVersionId());
        requireRubricContext(rubric, question);
        SnapshotRecord before = repository.findSnapshot(request.workspaceId(), request.beforeSnapshotId())
                .filter(value -> value.questionRevisionId().equals(questionRevisionId))
                .orElseThrow(() -> new DifficultyFeedbackNotFoundException("DIFFICULTY_SNAPSHOT_NOT_FOUND"));
        boolean gap = request.rubricGap() != null;
        if (gap && request.finalDifficultyValue() != null) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_GAP_VALUE_FORBIDDEN");
        }
        if (!gap && request.finalDifficultyValue() == null) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_FINAL_VALUE_REQUIRED");
        }
        Integer finalValue = request.finalDifficultyValue();
        List<DifficultyOperation> operations = gap
                ? List.of(new DifficultyOperation("RUBRIC_GAP_REPORTED", before.difficultyValue(), null))
                : java.util.Objects.equals(before.difficultyValue(), finalValue)
                    ? List.of(new DifficultyOperation("UNCHANGED_CONFIRMED", finalValue, finalValue))
                    : List.of(new DifficultyOperation("DIFFICULTY_CHANGED", before.difficultyValue(), finalValue));
        JsonNode empty = mapper.createObjectNode();
        String snapshotHash = hasher.snapshotHash(
                "HUMAN_FINAL", rubric.rubricVersionId(), request.contextKey(), before.contextHash(),
                finalValue, null, null, request.actorUserId(), empty);
        OffsetDateTime now = OffsetDateTime.now();
        var stored = repository.insertOrReplaySnapshot(new NewSnapshot(
                UUID.randomUUID(), request.workspaceId(), question.questionId(), questionRevisionId,
                rubric.rubricKey(), rubric.rubricVersionId(), request.contextKey(), before.context(),
                before.contextHash(), "HUMAN_FINAL", finalValue, null, null, empty,
                snapshotHash, request.actorUserId(), now));
        String outcome = gap ? "rubric_gap"
                : java.util.Objects.equals(before.difficultyValue(), finalValue) ? "confirmed" : "corrected";
        String status = gap ? "rubric_gap" : "reviewed";
        UUID feedbackId = UUID.randomUUID();
        List<String> reasons = request.reasonCodes().stream().distinct().sorted().toList();
        repository.insertFeedback(new NewFeedback(
                feedbackId, request.workspaceId(), question.questionId(), questionRevisionId,
                rubric.rubricKey(), rubric.rubricVersionId(), request.contextKey(), request.beforeSnapshotId(),
                stored.snapshot().snapshotId(), outcome, reasons, request.note() == null ? "" : request.note(),
                request.actorUserId(), now, request.clientMutationId(), requestHash,
                request.expectedStateVersion(), operations));
        boolean updated = repository.compareAndSetState(new NewStateUpdate(
                request.workspaceId(), questionRevisionId, request.rubricKey(), request.contextKey(),
                request.expectedStateVersion(), rubric.rubricVersionId(), stored.snapshot().snapshotId(),
                feedbackId, status, request.actorUserId(), now));
        if (!updated) {
            throw stateConflict("DIFFICULTY_STATE_VERSION_CONFLICT",
                    state(request.workspaceId(), questionRevisionId, request.rubricKey(), request.contextKey()));
        }
        UUID gapId = null;
        if (gap) {
            gapId = repository.insertGap(new NewGap(
                    UUID.randomUUID(), request.workspaceId(), question.questionId(), questionRevisionId,
                    feedbackId, request.rubricKey(), rubric.rubricVersionId(), request.contextKey(),
                    request.beforeSnapshotId(), request.rubricGap().expectedDifficultyText(),
                    request.rubricGap().explanation(), request.actorUserId(), now));
        }
        Map<String, Object> auditPayload = new HashMap<>();
        auditPayload.put("questionRevisionId", questionRevisionId);
        auditPayload.put("beforeSnapshotId", request.beforeSnapshotId());
        auditPayload.put("afterSnapshotId", stored.snapshot().snapshotId());
        auditPayload.put("outcome", outcome);
        if (gapId != null) auditPayload.put("rubricGapCaseId", gapId);
        recordAudit(request.workspaceId(), request.actorUserId(), "difficulty_feedback_submitted",
                "question_difficulty_feedback", feedbackId, auditPayload);
        return new SubmitDifficultyFeedbackResponse(
                feedbackId, false, request.expectedStateVersion() + 1, status,
                stored.snapshot().snapshotId(), operations, gapId);
    }

    @Transactional(readOnly = true)
    public DifficultyFeedbackHistoryResponse history(
            UUID questionRevisionId, UUID workspaceId, UUID actorUserId,
            String rubricKey, String contextKey) {
        requireWritableMember(workspaceId, actorUserId);
        QuestionRevisionDescriptor question = question(workspaceId, questionRevisionId);
        authorizeTeachingScope(workspaceId, actorUserId, question.subject(), question.stage());
        state(workspaceId, questionRevisionId, rubricKey, contextKey);
        return new DifficultyFeedbackHistoryResponse(
                questionRevisionId, rubricKey, contextKey,
                repository.findSnapshots(workspaceId, questionRevisionId, rubricKey, contextKey)
                        .stream().map(this::snapshotView).toList(),
                repository.findFeedback(workspaceId, questionRevisionId, rubricKey, contextKey)
                        .stream().map(this::feedbackView).toList(),
                repository.findGaps(workspaceId, questionRevisionId, rubricKey, contextKey)
                        .stream().map(this::gapView).toList());
    }

    private QuestionRevisionDescriptor question(UUID workspaceId, UUID revisionId) {
        List<QuestionRevisionDescriptor> found = questions.findAll(workspaceId, List.of(revisionId));
        if (found.size() != 1) {
            throw new DifficultyFeedbackNotFoundException("DIFFICULTY_QUESTION_REVISION_NOT_FOUND");
        }
        return found.getFirst();
    }

    private RubricRecord rubric(UUID workspaceId, UUID rubricVersionId) {
        return repository.findRubric(workspaceId, rubricVersionId)
                .orElseThrow(() -> new DifficultyFeedbackNotFoundException("DIFFICULTY_RUBRIC_NOT_FOUND"));
    }

    private StateRecord state(UUID workspaceId, UUID revisionId, String rubricKey, String contextKey) {
        return repository.findState(workspaceId, revisionId, rubricKey, contextKey)
                .orElseThrow(() -> new DifficultyFeedbackNotFoundException("DIFFICULTY_STATE_NOT_FOUND"));
    }

    private void requireRubricContext(RubricRecord rubric, QuestionRevisionDescriptor question) {
        if (!rubric.subject().equals(question.subject()) || !rubric.stage().equals(question.stage())
                || (rubric.grade() != null && !rubric.grade().equals(question.grade()))) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_RUBRIC_CONTEXT_MISMATCH");
        }
    }

    private void requireEvaluationContext(JsonNode context, QuestionRevisionDescriptor question) {
        if (!context.path("subject").asText("").equals(question.subject())
                || !context.path("stage").asText("").equals(question.stage())
                || !context.path("grade").asText("").equals(question.grade())) {
            throw new DifficultyFeedbackValidationException("DIFFICULTY_EVALUATION_CONTEXT_MISMATCH");
        }
    }

    private void requireWritableMember(UUID workspaceId, UUID actorUserId) {
        String role = workspaces.activeMemberRole(workspaceId, actorUserId)
                .orElseThrow(DifficultyFeedbackAccessException::new);
        if (!WRITE_ROLES.contains(role)) throw new DifficultyFeedbackAccessException();
    }

    private void authorizeTeachingScope(UUID workspaceId, UUID actorId, String subject, String stage) {
        if (!workspaces.hasTeachingScope(workspaceId, actorId, subject, stage)) {
            throw new DifficultyFeedbackAccessException();
        }
    }

    private DifficultyFeedbackConflictException stateConflict(String code, StateRecord state) {
        return new DifficultyFeedbackConflictException(
                code, state.stateVersion(), state.currentSnapshotId(), state.status());
    }

    private SubmitDifficultyFeedbackResponse replayResponse(FeedbackRecord feedback) {
        UUID gapId = repository.findGapByFeedback(feedback.feedbackId())
                .map(GapRecord::gapCaseId).orElse(null);
        String status = feedback.outcome().equals("rubric_gap") ? "rubric_gap" : "reviewed";
        return new SubmitDifficultyFeedbackResponse(
                feedback.feedbackId(), true, feedback.expectedStateVersion() + 1, status,
                feedback.afterSnapshotId(), feedback.operations(), gapId);
    }

    private DifficultySnapshotView snapshotView(SnapshotRecord value) {
        return new DifficultySnapshotView(
                value.snapshotId(), value.snapshotKind(), value.rubricVersionId(), value.contextKey(),
                value.context(), value.difficultyValue(), value.confidence(), value.runId(),
                value.modelContext(), value.snapshotHash(), value.createdBy(), value.createdAt());
    }

    private AssessmentRunView runView(RunRecord value) {
        return new AssessmentRunView(
                value.runId(), value.externalRunKey(), value.modelProvider(), value.modelName(),
                value.modelVersion(), value.promptProfileVersion(), value.evidencePackageKey(),
                value.evidencePackageVersion(), value.evidencePackageHash(), value.parameters(),
                value.startedAt(), value.completedAt());
    }

    private DifficultyQuestionSummary questionSummary(QuestionRevisionDescriptor value) {
        return new DifficultyQuestionSummary(
                value.questionId(), value.questionRevisionId(), value.subject(), value.stage(),
                value.grade(), value.title(), value.stemMarkdown(), value.provenance());
    }

    private DifficultyFeedbackView feedbackView(FeedbackRecord value) {
        return new DifficultyFeedbackView(
                value.feedbackId(), value.beforeSnapshotId(), value.afterSnapshotId(), value.outcome(),
                value.reasonCodes(), value.note(), value.reviewerId(), value.submittedAt(), value.operations());
    }

    private DifficultyGapView gapView(GapRecord value) {
        return new DifficultyGapView(
                value.gapCaseId(), value.feedbackId(), value.expectedDifficultyText(),
                value.explanation(), value.status(), value.createdBy(), value.createdAt());
    }

    private void validateHash(String value, String code) {
        if (value == null || !value.matches("[0-9a-f]{64}")) {
            throw new DifficultyFeedbackValidationException(code);
        }
    }

    private String clean(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private void recordAudit(UUID workspaceId, UUID actorId, String eventType,
                             String aggregateType, UUID aggregateId, Map<String, Object> payload) {
        audit.record(new AuditCommand(workspaceId, actorId, eventType, aggregateType, aggregateId, payload));
    }
}
