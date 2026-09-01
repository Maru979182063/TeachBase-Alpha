package com.teachbase.server.review.infrastructure;

import static com.teachbase.jooq.tables.ReviewCase.REVIEW_CASE;
import static com.teachbase.jooq.tables.ReviewDecision.REVIEW_DECISION;

import com.teachbase.server.review.application.ReviewCaseRecord;
import com.teachbase.server.review.application.ReviewRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：本文件属于人工审核模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：jOOQ adapter that serializes decisions by locking the open review case row.
 */
@Repository
class JooqReviewRepository implements ReviewRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqReviewRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public ReviewCaseRecord open(
            UUID workspaceId,
            UUID questionId,
            UUID questionRevisionId,
            String expectedContentHash,
            UUID assignedTo,
            UUID openedBy) {
        UUID candidateId = UUID.randomUUID();
        database.insertInto(REVIEW_CASE)
                .set(REVIEW_CASE.REVIEW_CASE_ID, candidateId)
                .set(REVIEW_CASE.WORKSPACE_ID, workspaceId)
                .set(REVIEW_CASE.QUESTION_ID, questionId)
                .set(REVIEW_CASE.QUESTION_REVISION_ID, questionRevisionId)
                .set(REVIEW_CASE.EXPECTED_CONTENT_HASH, expectedContentHash)
                .set(REVIEW_CASE.STATUS, "open")
                .set(REVIEW_CASE.ASSIGNED_TO, assignedTo)
                .set(REVIEW_CASE.OPENED_BY, openedBy)
                .onConflictDoNothing()
                .execute();
        return database.selectFrom(REVIEW_CASE)
                .where(REVIEW_CASE.QUESTION_REVISION_ID.eq(questionRevisionId))
                .and(REVIEW_CASE.STATUS.eq("open"))
                .fetchOptional(this::map)
                .orElseThrow(() -> new IllegalStateException("review_case_open_failed"));
    }

    @Override
    public Optional<ReviewCaseRecord> lockOpen(UUID workspaceId, UUID reviewCaseId) {
        return database.selectFrom(REVIEW_CASE)
                .where(REVIEW_CASE.WORKSPACE_ID.eq(workspaceId))
                .and(REVIEW_CASE.REVIEW_CASE_ID.eq(reviewCaseId))
                .and(REVIEW_CASE.STATUS.eq("open"))
                .forUpdate()
                .fetchOptional(this::map);
    }

    @Override
    public ReviewCaseRecord complete(
            ReviewCaseRecord reviewCase,
            UUID actorUserId,
            String decision,
            String note,
            String policyVersion,
            String decisionSource,
            JsonNode evidence,
            OffsetDateTime evidenceOccurredAt) {
        OffsetDateTime now = OffsetDateTime.now();
        database.insertInto(REVIEW_DECISION)
                .set(REVIEW_DECISION.REVIEW_DECISION_ID, UUID.randomUUID())
                .set(REVIEW_DECISION.REVIEW_CASE_ID, reviewCase.reviewCaseId())
                .set(REVIEW_DECISION.WORKSPACE_ID, reviewCase.workspaceId())
                .set(REVIEW_DECISION.DECISION, decision)
                .set(REVIEW_DECISION.NOTE, note)
                .set(REVIEW_DECISION.EXPECTED_CONTENT_HASH, reviewCase.expectedContentHash())
                .set(REVIEW_DECISION.POLICY_VERSION, policyVersion)
                .set(REVIEW_DECISION.DECISION_SOURCE, decisionSource)
                .set(REVIEW_DECISION.EVIDENCE_JSON, json(evidence))
                .set(REVIEW_DECISION.EVIDENCE_OCCURRED_AT, evidenceOccurredAt)
                .set(REVIEW_DECISION.DECIDED_BY, actorUserId)
                .set(REVIEW_DECISION.DECIDED_AT, now)
                .execute();
        int changed = database.update(REVIEW_CASE)
                .set(REVIEW_CASE.STATUS, decision)
                .set(REVIEW_CASE.DECIDED_AT, now)
                .where(REVIEW_CASE.REVIEW_CASE_ID.eq(reviewCase.reviewCaseId()))
                .and(REVIEW_CASE.STATUS.eq("open"))
                .execute();
        if (changed != 1) throw new IllegalStateException("review_case_concurrent_decision");
        return new ReviewCaseRecord(
                reviewCase.reviewCaseId(), reviewCase.workspaceId(), reviewCase.questionId(),
                reviewCase.questionRevisionId(), reviewCase.expectedContentHash(), decision,
                reviewCase.assignedTo(), reviewCase.openedAt(), now);
    }

    private ReviewCaseRecord map(com.teachbase.jooq.tables.records.ReviewCaseRecord record) {
        return new ReviewCaseRecord(
                record.getReviewCaseId(), record.getWorkspaceId(), record.getQuestionId(),
                record.getQuestionRevisionId(), record.getExpectedContentHash(), record.getStatus(),
                record.getAssignedTo(), record.getOpenedAt(), record.getDecidedAt());
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("review_evidence_not_serializable", exception);
        }
    }
}
