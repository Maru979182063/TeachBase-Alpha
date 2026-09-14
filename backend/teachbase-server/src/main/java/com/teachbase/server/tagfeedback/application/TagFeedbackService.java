package com.teachbase.server.tagfeedback.application;

import static com.teachbase.server.tagfeedback.api.TagFeedbackContracts.*;
import static com.teachbase.server.tagfeedback.application.TagFeedbackHasher.SnapshotItemValue;
import static com.teachbase.server.tagfeedback.application.TagFeedbackRepository.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.audit.api.AuditCommand;
import com.teachbase.server.audit.api.AuditTrail;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import com.teachbase.server.taxonomy.api.TaxonomySnapshotDescriptor;
import com.teachbase.server.taxonomy.api.TaxonomySnapshotDirectory;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：01A 的事务总入口；标签变化只能推进 question_tag_state，绝不调用题目 revision 或 Review writer。
 */
@Service
public class TagFeedbackService {

    private static final Set<String> WRITE_ROLES = Set.of("owner", "admin", "editor", "reviewer");

    private final TagFeedbackRepository repository;
    private final TagFeedbackHasher hasher;
    private final TagFeedbackDiff diff;
    private final WorkspaceDirectory workspaces;
    private final QuestionRevisionDirectory questions;
    private final TaxonomySnapshotDirectory taxonomies;
    private final AuditTrail audit;
    private final ObjectMapper mapper;

    public TagFeedbackService(
            TagFeedbackRepository repository,
            TagFeedbackHasher hasher,
            TagFeedbackDiff diff,
            WorkspaceDirectory workspaces,
            QuestionRevisionDirectory questions,
            TaxonomySnapshotDirectory taxonomies,
            AuditTrail audit,
            ObjectMapper mapper) {
        this.repository = repository;
        this.hasher = hasher;
        this.diff = diff;
        this.workspaces = workspaces;
        this.questions = questions;
        this.taxonomies = taxonomies;
        this.audit = audit;
        this.mapper = mapper;
    }

    @Transactional
    public TaggingRunResponse registerRun(RegisterTaggingRunRequest request) {
        validateHash(request.candidatePackageHash(), "TAG_FEEDBACK_CANDIDATE_PACKAGE_HASH_INVALID");
        if (!Set.of("completed", "failed").contains(request.status())) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_FROZEN_RUN_STATUS_REQUIRED");
        }
        if (request.completedAt() == null || request.completedAt().isBefore(request.startedAt())) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_RUN_TIME_INVALID");
        }
        requireWritableMember(request.workspaceId(), request.actorUserId());
        TaxonomySnapshotDescriptor taxonomy = taxonomy(
                request.workspaceId(), request.taxonomyVersionId(), List.of());
        authorizeTeachingScope(
                request.workspaceId(), request.actorUserId(), taxonomy.subject(), taxonomy.stage());

        var hashes = hasher.hashRun(request);
        OffsetDateTime now = OffsetDateTime.now();
        var stored = repository.insertOrReplayRun(new NewRun(
                UUID.randomUUID(), request.workspaceId(), request.externalRunKey(),
                request.taxonomyVersionId(), request.modelProvider(), request.modelName(),
                request.modelVersion(), request.promptProfileVersion(), request.candidatePackageKey(),
                request.candidatePackageVersion(), request.candidatePackageHash(), request.producerVersion(),
                request.runtimeVersion(), hashes.canonicalParameters(), hashes.parametersHash(),
                hashes.runHash(), request.status(), request.startedAt(), request.completedAt(),
                request.canonicalImportRequestId(), request.actorUserId(), now));
        if (!stored.run().runHash().equals(hashes.runHash())) {
            throw new TagFeedbackConflictException("TAG_FEEDBACK_RUN_PAYLOAD_CONFLICT");
        }
        if (!stored.replayed()) {
            recordAudit(request.workspaceId(), request.actorUserId(), "tagging_run_registered",
                    "tagging_run", stored.run().taggingRunId(), Map.of(
                            "externalRunKey", stored.run().externalRunKey(),
                            "runHash", stored.run().runHash()));
        }
        return new TaggingRunResponse(
                stored.run().taggingRunId(), stored.replayed(), stored.run().runHash(),
                stored.run().parametersHash(), stored.run().status());
    }

    @Transactional
    public RegisterSuggestionResponse registerSuggestion(
            UUID taggingRunId, RegisterSuggestionRequest request) {
        requireWritableMember(request.workspaceId(), request.actorUserId());
        RunRecord run = repository.findRun(request.workspaceId(), taggingRunId)
                .orElseThrow(() -> new TagFeedbackNotFoundException("TAG_FEEDBACK_RUN_NOT_FOUND"));
        QuestionRevisionDescriptor question = question(
                request.workspaceId(), request.questionRevisionId());
        List<TagItemInput> secondary = normalizeSuggestionItems(request.secondary());
        validateSuggestionItem(request.primary());
        List<UUID> nodeIds = new ArrayList<>();
        nodeIds.add(request.primary().taxonomyNodeId());
        secondary.forEach(item -> nodeIds.add(item.taxonomyNodeId()));
        requireDistinct(nodeIds);
        TaxonomySnapshotDescriptor taxonomy = taxonomy(
                request.workspaceId(), run.taxonomyVersionId(), nodeIds);
        authorizeTeachingScope(
                request.workspaceId(), request.actorUserId(), question.subject(), question.stage());
        requireTaxonomyMatch(taxonomy, request.taxonomyKey(), question);
        if (!taxonomy.status().equals("active")) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_TAXONOMY_NOT_ACTIVE");
        }
        if (!request.modelOutputContext().isObject()) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_MODEL_CONTEXT_OBJECT_REQUIRED");
        }

        List<SnapshotItemValue> itemValues = suggestionValues(request.primary(), secondary);
        List<UUID> secondaryIds = secondary.stream().map(TagItemInput::taxonomyNodeId).toList();
        String labelSetHash = hasher.labelSetHash(
                taxonomy.taxonomyVersionId(), request.primary().taxonomyNodeId(), secondaryIds);
        String snapshotHash = hasher.snapshotHash(
                "SYSTEM_SUGGESTION", labelSetHash, run.taggingRunId(), request.actorUserId(),
                request.modelOutputContext(), itemValues);
        OffsetDateTime now = OffsetDateTime.now();
        UUID candidateSnapshotId = UUID.randomUUID();
        var stored = repository.insertOrReplaySnapshot(
                new NewSnapshot(
                        candidateSnapshotId, request.workspaceId(), question.questionId(),
                        question.questionRevisionId(), request.taxonomyKey(), taxonomy.taxonomyVersionId(),
                        "SYSTEM_SUGGESTION", labelSetHash, snapshotHash, run.taggingRunId(),
                        hasher.canonical(request.modelOutputContext()), request.actorUserId(), now),
                itemRecords(candidateSnapshotId, request.workspaceId(), taxonomy.taxonomyVersionId(), itemValues));
        StateRecord state = repository.insertOrFindPendingState(new NewState(
                UUID.randomUUID(), request.workspaceId(), question.questionId(), question.questionRevisionId(),
                request.taxonomyKey(), taxonomy.taxonomyVersionId(), stored.snapshot().snapshotId(),
                request.actorUserId(), now));
        if (!state.taxonomyVersionId().equals(taxonomy.taxonomyVersionId())) {
            throw new TagFeedbackConflictException(
                    "TAG_FEEDBACK_TAXONOMY_VERSION_CONFLICT",
                    state.stateVersion(), state.currentSnapshotId(), state.status());
        }
        if (!stored.replayed()) {
            recordAudit(request.workspaceId(), request.actorUserId(), "tag_suggestion_registered",
                    "question_tag_snapshot", stored.snapshot().snapshotId(), Map.of(
                            "questionRevisionId", question.questionRevisionId(),
                            "taggingRunId", run.taggingRunId(),
                            "snapshotHash", snapshotHash));
        }
        return new RegisterSuggestionResponse(
                stored.snapshot().snapshotId(), state.stateId(), state.stateVersion(), state.status(),
                stored.snapshot().labelSetHash(), stored.snapshot().snapshotHash(), stored.replayed());
    }

    @Transactional(readOnly = true)
    public TagReviewContextResponse reviewContext(
            UUID questionRevisionId, UUID workspaceId, UUID actorUserId, String taxonomyKey) {
        requireWritableMember(workspaceId, actorUserId);
        QuestionRevisionDescriptor question = question(workspaceId, questionRevisionId);
        authorizeTeachingScope(workspaceId, actorUserId, question.subject(), question.stage());
        StateRecord state = repository.findState(workspaceId, questionRevisionId, taxonomyKey)
                .orElseThrow(() -> new TagFeedbackNotFoundException("TAG_FEEDBACK_STATE_NOT_FOUND"));
        SnapshotRecord current = repository.findSnapshot(workspaceId, state.currentSnapshotId()).orElseThrow();
        SnapshotRecord system = repository.findSnapshots(workspaceId, questionRevisionId, taxonomyKey).stream()
                .filter(value -> value.snapshotKind().equals("SYSTEM_SUGGESTION"))
                .max(Comparator.comparing(SnapshotRecord::createdAt)
                        .thenComparing(value -> value.snapshotId().toString()))
                .orElseThrow(() -> new TagFeedbackNotFoundException("TAG_FEEDBACK_SUGGESTION_NOT_FOUND"));
        RunRecord run = repository.findRun(workspaceId, system.taggingRunId()).orElseThrow();
        return new TagReviewContextResponse(
                questionRevisionId, taxonomyKey, state.taxonomyVersionId(), state.stateVersion(), state.status(),
                snapshotView(system), snapshotView(current), runView(run), questionSummary(question));
    }

    @Transactional
    public SubmitTagFeedbackResponse submit(
            UUID questionRevisionId, SubmitTagFeedbackRequest request) {
        if (request.expectedStateVersion() < 0) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_STATE_VERSION_INVALID");
        }
        requireWritableMember(request.workspaceId(), request.actorUserId());
        QuestionRevisionDescriptor question = question(request.workspaceId(), questionRevisionId);
        authorizeTeachingScope(
                request.workspaceId(), request.actorUserId(), question.subject(), question.stage());
        String requestHash = hasher.feedbackRequestHash(questionRevisionId, request);
        repository.lockMutation(request.workspaceId(), request.clientMutationId());
        var replay = repository.findFeedbackByMutation(request.workspaceId(), request.clientMutationId());
        if (replay.isPresent()) {
            if (!replay.get().requestHash().equals(requestHash)) {
                throw new TagFeedbackConflictException(
                        "TAG_FEEDBACK_IDEMPOTENCY_PAYLOAD_CONFLICT");
            }
            return replayResponse(replay.get());
        }

        StateRecord state = repository.findState(
                        request.workspaceId(), questionRevisionId, request.taxonomyKey())
                .orElseThrow(() -> new TagFeedbackNotFoundException("TAG_FEEDBACK_STATE_NOT_FOUND"));
        if (!state.taxonomyVersionId().equals(request.taxonomyVersionId())) {
            throw stateConflict("TAG_FEEDBACK_TAXONOMY_VERSION_CONFLICT", state);
        }
        if (!state.currentSnapshotId().equals(request.beforeSnapshotId())) {
            throw stateConflict("TAG_FEEDBACK_BEFORE_SNAPSHOT_CONFLICT", state);
        }
        if (state.stateVersion() != request.expectedStateVersion()) {
            throw stateConflict("TAG_FEEDBACK_STATE_VERSION_CONFLICT", state);
        }

        boolean gap = request.taxonomyGap() != null;
        if (gap && request.finalPrimaryNodeId() != null) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_GAP_PRIMARY_FORBIDDEN");
        }
        if (!gap && request.finalPrimaryNodeId() == null) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_PRIMARY_REQUIRED");
        }
        List<UUID> secondaryIds = List.copyOf(request.finalSecondaryNodeIds());
        if (new LinkedHashSet<>(secondaryIds).size() != secondaryIds.size()
                || (request.finalPrimaryNodeId() != null
                    && secondaryIds.contains(request.finalPrimaryNodeId()))) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_LABEL_SET_DUPLICATE");
        }
        List<UUID> nodeIds = new ArrayList<>(secondaryIds);
        if (request.finalPrimaryNodeId() != null) {
            nodeIds.add(request.finalPrimaryNodeId());
        }
        TaxonomySnapshotDescriptor taxonomy = taxonomy(
                request.workspaceId(), request.taxonomyVersionId(), nodeIds);
        requireTaxonomyMatch(taxonomy, request.taxonomyKey(), question);

        SnapshotRecord beforeSnapshot = repository.findSnapshot(
                        request.workspaceId(), request.beforeSnapshotId())
                .filter(value -> value.questionRevisionId().equals(questionRevisionId))
                .orElseThrow(() -> new TagFeedbackNotFoundException("TAG_FEEDBACK_SNAPSHOT_NOT_FOUND"));
        TagFeedbackDiff.LabelSet before = labelSet(beforeSnapshot.snapshotId());
        TagFeedbackDiff.LabelSet after = new TagFeedbackDiff.LabelSet(
                request.finalPrimaryNodeId(), new LinkedHashSet<>(secondaryIds));
        List<DerivedOperation> operations = diff.derive(before, after);
        String labelSetHash = hasher.labelSetHash(
                request.taxonomyVersionId(), request.finalPrimaryNodeId(), secondaryIds);
        List<SnapshotItemValue> itemValues = humanValues(request.finalPrimaryNodeId(), secondaryIds);
        JsonNode emptyContext = mapper.createObjectNode();
        String snapshotHash = hasher.snapshotHash(
                "HUMAN_FINAL", labelSetHash, null, request.actorUserId(), emptyContext, itemValues);
        OffsetDateTime now = OffsetDateTime.now();
        UUID candidateSnapshotId = UUID.randomUUID();
        var storedSnapshot = repository.insertOrReplaySnapshot(
                new NewSnapshot(
                        candidateSnapshotId, request.workspaceId(), question.questionId(), questionRevisionId,
                        request.taxonomyKey(), request.taxonomyVersionId(), "HUMAN_FINAL", labelSetHash,
                        snapshotHash, null, emptyContext, request.actorUserId(), now),
                itemRecords(candidateSnapshotId, request.workspaceId(), request.taxonomyVersionId(), itemValues));

        String outcome = gap ? "taxonomy_gap"
                : before.equals(after) ? "confirmed" : "corrected";
        String status = gap ? "taxonomy_gap" : "reviewed";
        UUID feedbackId = UUID.randomUUID();
        List<String> reasonCodes = request.reasonCodes().stream().distinct().sorted().toList();
        repository.insertFeedback(new NewFeedback(
                feedbackId, request.workspaceId(), question.questionId(), questionRevisionId,
                request.taxonomyKey(), request.taxonomyVersionId(), request.beforeSnapshotId(),
                storedSnapshot.snapshot().snapshotId(), outcome, reasonCodes,
                request.note() == null ? "" : request.note(), request.actorUserId(), now,
                request.clientMutationId(), requestHash, request.expectedStateVersion(), operations));
        boolean updated = repository.compareAndSetState(
                request.workspaceId(), questionRevisionId, request.taxonomyKey(),
                request.expectedStateVersion(), request.taxonomyVersionId(),
                storedSnapshot.snapshot().snapshotId(), feedbackId, status, request.actorUserId(), now);
        if (!updated) {
            StateRecord latest = repository.findState(
                    request.workspaceId(), questionRevisionId, request.taxonomyKey()).orElseThrow();
            throw stateConflict("TAG_FEEDBACK_STATE_VERSION_CONFLICT", latest);
        }

        UUID gapCaseId = null;
        if (gap) {
            gapCaseId = repository.insertGap(new NewGap(
                    UUID.randomUUID(), request.workspaceId(), question.questionId(), questionRevisionId,
                    feedbackId, request.taxonomyVersionId(), request.beforeSnapshotId(),
                    request.taxonomyGap().expectedLabelText(), request.taxonomyGap().explanation(),
                    request.actorUserId(), now));
        }
        Map<String, Object> payload = new HashMap<>();
        payload.put("questionRevisionId", questionRevisionId);
        payload.put("beforeSnapshotId", request.beforeSnapshotId());
        payload.put("afterSnapshotId", storedSnapshot.snapshot().snapshotId());
        payload.put("outcome", outcome);
        payload.put("stateVersion", request.expectedStateVersion() + 1);
        if (gapCaseId != null) payload.put("taxonomyGapCaseId", gapCaseId);
        recordAudit(request.workspaceId(), request.actorUserId(), "question_tag_feedback_submitted",
                "question_tag_feedback", feedbackId, payload);
        return new SubmitTagFeedbackResponse(
                feedbackId, false, request.expectedStateVersion() + 1, status,
                storedSnapshot.snapshot().snapshotId(), operations, gapCaseId);
    }

    @Transactional(readOnly = true)
    public TagFeedbackHistoryResponse history(
            UUID questionRevisionId, UUID workspaceId, UUID actorUserId, String taxonomyKey) {
        requireWritableMember(workspaceId, actorUserId);
        QuestionRevisionDescriptor question = question(workspaceId, questionRevisionId);
        authorizeTeachingScope(workspaceId, actorUserId, question.subject(), question.stage());
        List<SnapshotView> snapshots = repository.findSnapshots(workspaceId, questionRevisionId, taxonomyKey)
                .stream().map(this::snapshotView).toList();
        List<FeedbackView> feedback = repository.findFeedback(workspaceId, questionRevisionId, taxonomyKey)
                .stream().map(this::feedbackView).toList();
        List<TaxonomyGapView> gaps = repository.findGaps(workspaceId, questionRevisionId)
                .stream().map(this::gapView).toList();
        return new TagFeedbackHistoryResponse(questionRevisionId, taxonomyKey, snapshots, feedback, gaps);
    }

    private QuestionRevisionDescriptor question(UUID workspaceId, UUID questionRevisionId) {
        List<QuestionRevisionDescriptor> found = questions.findAll(workspaceId, List.of(questionRevisionId));
        if (found.size() != 1) {
            throw new TagFeedbackNotFoundException("TAG_FEEDBACK_QUESTION_REVISION_NOT_FOUND");
        }
        return found.getFirst();
    }

    private TaxonomySnapshotDescriptor taxonomy(
            UUID workspaceId, UUID taxonomyVersionId, List<UUID> nodeIds) {
        return taxonomies.describe(workspaceId, taxonomyVersionId, nodeIds)
                .orElseThrow(() -> new TagFeedbackNotFoundException("TAG_FEEDBACK_TAXONOMY_NOT_FOUND"));
    }

    private void requireWritableMember(UUID workspaceId, UUID actorUserId) {
        String role = workspaces.activeMemberRole(workspaceId, actorUserId)
                .orElseThrow(TagFeedbackAccessException::new);
        if (!WRITE_ROLES.contains(role)) {
            throw new TagFeedbackAccessException();
        }
    }

    private void authorizeTeachingScope(
            UUID workspaceId, UUID actorUserId, String subject, String stage) {
        if (!workspaces.hasTeachingScope(workspaceId, actorUserId, subject, stage)) {
            throw new TagFeedbackAccessException();
        }
    }

    private void requireTaxonomyMatch(
            TaxonomySnapshotDescriptor taxonomy,
            String taxonomyKey,
            QuestionRevisionDescriptor question) {
        if (!taxonomy.taxonomyKey().equals(taxonomyKey)
                || !taxonomy.subject().equals(question.subject())
                || !taxonomy.stage().equals(question.stage())) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_TAXONOMY_CONTEXT_MISMATCH");
        }
    }

    private List<TagItemInput> normalizeSuggestionItems(List<TagItemInput> values) {
        values.forEach(this::validateSuggestionItem);
        return List.copyOf(values);
    }

    private void validateSuggestionItem(TagItemInput item) {
        BigDecimal confidence = item.confidence();
        if (confidence != null
                && (confidence.compareTo(BigDecimal.ZERO) < 0
                    || confidence.compareTo(BigDecimal.ONE) > 0)) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_CONFIDENCE_INVALID");
        }
        if (item.candidateRank() != null && item.candidateRank() <= 0) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_CANDIDATE_RANK_INVALID");
        }
    }

    private void requireDistinct(List<UUID> nodeIds) {
        if (new LinkedHashSet<>(nodeIds).size() != nodeIds.size()) {
            throw new TagFeedbackValidationException("TAG_FEEDBACK_LABEL_SET_DUPLICATE");
        }
    }

    private List<SnapshotItemValue> suggestionValues(
            TagItemInput primary, List<TagItemInput> secondary) {
        List<SnapshotItemValue> values = new ArrayList<>();
        values.add(new SnapshotItemValue(
                primary.taxonomyNodeId(), "primary", 0, primary.confidence(), primary.candidateRank()));
        for (int index = 0; index < secondary.size(); index++) {
            TagItemInput item = secondary.get(index);
            values.add(new SnapshotItemValue(
                    item.taxonomyNodeId(), "secondary", index,
                    item.confidence(), item.candidateRank()));
        }
        return List.copyOf(values);
    }

    private List<SnapshotItemValue> humanValues(UUID primary, List<UUID> secondary) {
        List<SnapshotItemValue> values = new ArrayList<>();
        if (primary != null) {
            values.add(new SnapshotItemValue(primary, "primary", 0, null, null));
        }
        for (int index = 0; index < secondary.size(); index++) {
            values.add(new SnapshotItemValue(secondary.get(index), "secondary", index, null, null));
        }
        return List.copyOf(values);
    }

    private List<SnapshotItemRecord> itemRecords(
            UUID snapshotId,
            UUID workspaceId,
            UUID taxonomyVersionId,
            List<SnapshotItemValue> values) {
        return values.stream().map(value -> new SnapshotItemRecord(
                UUID.randomUUID(), snapshotId, workspaceId, taxonomyVersionId,
                value.taxonomyNodeId(), value.relationType(), value.positionIndex(),
                value.confidence(), value.candidateRank())).toList();
    }

    private TagFeedbackDiff.LabelSet labelSet(UUID snapshotId) {
        UUID primary = null;
        Set<UUID> secondary = new LinkedHashSet<>();
        for (SnapshotItemRecord item : repository.findSnapshotItems(snapshotId)) {
            if (item.relationType().equals("primary")) primary = item.taxonomyNodeId();
            else secondary.add(item.taxonomyNodeId());
        }
        return new TagFeedbackDiff.LabelSet(primary, secondary);
    }

    private SubmitTagFeedbackResponse replayResponse(FeedbackRecord feedback) {
        UUID gapCaseId = repository.findGapByFeedback(feedback.feedbackId())
                .map(GapRecord::gapCaseId).orElse(null);
        String status = feedback.outcome().equals("taxonomy_gap") ? "taxonomy_gap" : "reviewed";
        return new SubmitTagFeedbackResponse(
                feedback.feedbackId(), true, feedback.expectedStateVersion() + 1, status,
                feedback.afterSnapshotId(), feedback.derivedOperations(), gapCaseId);
    }

    private TagFeedbackConflictException stateConflict(String code, StateRecord state) {
        return new TagFeedbackConflictException(
                code, state.stateVersion(), state.currentSnapshotId(), state.status());
    }

    private SnapshotView snapshotView(SnapshotRecord snapshot) {
        List<TagItemView> items = repository.findSnapshotItems(snapshot.snapshotId()).stream()
                .map(item -> new TagItemView(
                        item.taxonomyNodeId(), item.relationType(), item.positionIndex(),
                        item.confidence(), item.candidateRank()))
                .toList();
        return new SnapshotView(
                snapshot.snapshotId(), snapshot.snapshotKind(), snapshot.taxonomyVersionId(),
                snapshot.taggingRunId(), snapshot.labelSetHash(), snapshot.snapshotHash(),
                snapshot.modelOutputContext(), snapshot.createdBy(), snapshot.createdAt(), items);
    }

    private RunView runView(RunRecord run) {
        return new RunView(
                run.taggingRunId(), run.externalRunKey(), run.modelProvider(), run.modelName(),
                run.modelVersion(), run.promptProfileVersion(), run.candidatePackageKey(),
                run.candidatePackageVersion(), run.candidatePackageHash(), run.producerVersion(),
                run.runtimeVersion(), run.parameters(), run.status(), run.startedAt(), run.completedAt());
    }

    private QuestionSourceSummary questionSummary(QuestionRevisionDescriptor question) {
        return new QuestionSourceSummary(
                question.questionId(), question.questionRevisionId(), question.subject(), question.stage(),
                question.title(), question.stemMarkdown(), question.provenance());
    }

    private FeedbackView feedbackView(FeedbackRecord feedback) {
        return new FeedbackView(
                feedback.feedbackId(), feedback.beforeSnapshotId(), feedback.afterSnapshotId(),
                feedback.outcome(), feedback.reasonCodes(), feedback.note(), feedback.reviewerId(),
                feedback.submittedAt(), feedback.derivedOperations());
    }

    private TaxonomyGapView gapView(GapRecord gap) {
        return new TaxonomyGapView(
                gap.gapCaseId(), gap.feedbackId(), gap.expectedLabelText(), gap.teacherExplanation(),
                gap.status(), gap.createdBy(), gap.createdAt());
    }

    private void validateHash(String value, String code) {
        if (value == null || !value.matches("[0-9a-f]{64}")) {
            throw new TagFeedbackValidationException(code);
        }
    }

    private void recordAudit(
            UUID workspaceId,
            UUID actorUserId,
            String eventType,
            String aggregateType,
            UUID aggregateId,
            Map<String, Object> payload) {
        audit.record(new AuditCommand(
                workspaceId, actorUserId, eventType, aggregateType, aggregateId, payload));
    }
}
