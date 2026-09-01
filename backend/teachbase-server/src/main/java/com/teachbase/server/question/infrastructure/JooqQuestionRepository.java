package com.teachbase.server.question.infrastructure;

import static com.teachbase.jooq.tables.EditorQuestionReference.EDITOR_QUESTION_REFERENCE;
import static com.teachbase.jooq.tables.Question.QUESTION;
import static com.teachbase.jooq.tables.QuestionImportObservation.QUESTION_IMPORT_OBSERVATION;
import static com.teachbase.jooq.tables.QuestionCollectionItem.QUESTION_COLLECTION_ITEM;
import static com.teachbase.jooq.tables.QuestionCollectionSnapshotItem.QUESTION_COLLECTION_SNAPSHOT_ITEM;
import static com.teachbase.jooq.tables.QuestionRelation.QUESTION_RELATION;
import static com.teachbase.jooq.tables.QuestionRevision.QUESTION_REVISION;
import static com.teachbase.jooq.tables.QuestionSourceLink.QUESTION_SOURCE_LINK;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.question.api.QuestionImportResult;
import com.teachbase.server.question.api.QuestionIngestionLinker;
import com.teachbase.server.question.api.QuestionRelationCommand;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import com.teachbase.server.question.api.QuestionReviewGateway;
import com.teachbase.server.question.api.QuestionReviewStateException;
import com.teachbase.server.question.api.QuestionReviewTarget;
import com.teachbase.server.question.api.QuestionSearchItem;
import com.teachbase.server.question.api.QuestionSourceEvidenceCommand;
import com.teachbase.server.question.application.NormalizedQuestionRevision;
import com.teachbase.server.question.application.QuestionRepository;
import com.teachbase.server.question.application.QuestionSearchCursor;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.jooq.Condition;
import org.jooq.DSLContext;
import org.jooq.Field;
import org.jooq.JSON;
import org.jooq.impl.DSL;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：PostgreSQL implementation of idempotent imports, indexed search, and revision lookup.
 */
@Repository
class JooqQuestionRepository implements
        QuestionRepository,
        QuestionRevisionDirectory,
        QuestionReviewGateway,
        QuestionIngestionLinker {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqQuestionRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public QuestionImportResult importRevision(NormalizedQuestionRevision input) {
        UUID candidateId = UUID.randomUUID();
        OffsetDateTime now = OffsetDateTime.now();
        int inserted = database.insertInto(QUESTION)
                .set(QUESTION.QUESTION_ID, candidateId)
                .set(QUESTION.WORKSPACE_ID, input.workspaceId())
                .set(QUESTION.EXTERNAL_KEY, input.externalKey())
                .set(QUESTION.SOURCE_SYSTEM, input.sourceSystem())
                .set(QUESTION.SOURCE_KEY, input.sourceKey())
                .set(QUESTION.STATUS, "active")
                .set(QUESTION.CURRENT_REVISION_NO, 0L)
                .set(QUESTION.CREATED_BY, input.actorUserId())
                .set(QUESTION.UPDATED_BY, input.actorUserId())
                .set(QUESTION.CREATED_AT, now)
                .set(QUESTION.UPDATED_AT, now)
                .onConflict(QUESTION.WORKSPACE_ID, QUESTION.SOURCE_SYSTEM, QUESTION.SOURCE_KEY)
                .doNothing()
                .execute();

        // 即使两个导入端同时发现同一个来源键，冲突安全插入也会先建立可加锁记录，
        // 后续修订创建由该记录串行化，避免重复题目身份。
        var question = database.select(QUESTION.QUESTION_ID, QUESTION.CURRENT_REVISION_NO)
                .from(QUESTION)
                .where(QUESTION.WORKSPACE_ID.eq(input.workspaceId()))
                .and(QUESTION.SOURCE_SYSTEM.eq(input.sourceSystem()))
                .and(QUESTION.SOURCE_KEY.eq(input.sourceKey()))
                .forUpdate()
                .fetchOne();
        if (question == null) throw new IllegalStateException("question_import_identity_missing");
        UUID questionId = question.get(QUESTION.QUESTION_ID);

        var existing = database.select(
                        QUESTION_REVISION.QUESTION_REVISION_ID,
                        QUESTION_REVISION.REVISION_NO,
                        QUESTION_REVISION.REVIEW_STATUS)
                .from(QUESTION_REVISION)
                .where(QUESTION_REVISION.QUESTION_ID.eq(questionId))
                .and(QUESTION_REVISION.CONTENT_HASH.eq(input.contentHash()))
                .fetchOne();
        if (existing != null) {
            observeImport(input, questionId, existing.get(QUESTION_REVISION.QUESTION_REVISION_ID), now);
            return new QuestionImportResult(
                    questionId,
                    existing.get(QUESTION_REVISION.QUESTION_REVISION_ID),
                    existing.get(QUESTION_REVISION.REVISION_NO),
                    existing.get(QUESTION_REVISION.REVIEW_STATUS),
                    inserted == 1,
                    false);
        }

        long revisionNo = question.get(QUESTION.CURRENT_REVISION_NO) + 1;
        UUID revisionId = UUID.randomUUID();
        database.insertInto(QUESTION_REVISION)
                .set(QUESTION_REVISION.QUESTION_REVISION_ID, revisionId)
                .set(QUESTION_REVISION.QUESTION_ID, questionId)
                .set(QUESTION_REVISION.WORKSPACE_ID, input.workspaceId())
                .set(QUESTION_REVISION.REVISION_NO, revisionNo)
                .set(QUESTION_REVISION.REVIEW_STATUS, input.reviewStatus())
                .set(QUESTION_REVISION.SUBJECT, input.subject())
                .set(QUESTION_REVISION.STAGE, input.stage())
                .set(QUESTION_REVISION.GRADE, input.grade())
                .set(QUESTION_REVISION.QUESTION_TYPE, input.questionType())
                .set(QUESTION_REVISION.TITLE, input.title())
                .set(QUESTION_REVISION.LESSON, input.lesson())
                .set(QUESTION_REVISION.PRIMARY_KNOWLEDGE_TAG, input.primaryKnowledgeTag())
                .set(QUESTION_REVISION.SECONDARY_KNOWLEDGE_TAGS_JSON, json(input.secondaryKnowledgeTags()))
                .set(QUESTION_REVISION.DIFFICULTY_STARS,
                        input.difficultyStars() == null ? null : input.difficultyStars().shortValue())
                .set(QUESTION_REVISION.MATERIAL_MARKDOWN, input.materialMarkdown())
                .set(QUESTION_REVISION.STEM_MARKDOWN, input.stemMarkdown())
                .set(QUESTION_REVISION.OPTIONS_JSON, json(input.options()))
                .set(QUESTION_REVISION.ANSWER_MARKDOWN, input.answerMarkdown())
                .set(QUESTION_REVISION.ANALYSIS_MARKDOWN, input.analysisMarkdown())
                .set(QUESTION_REVISION.CONTENT_JSON, json(input.content()))
                .set(QUESTION_REVISION.PROVENANCE_JSON, json(input.provenance()))
                .set(QUESTION_REVISION.CONTENT_HASH, input.contentHash())
                .set(QUESTION_REVISION.SOURCE_PAYLOAD_HASH, input.sourcePayloadHash())
                .set(QUESTION_REVISION.IMPORT_ENVELOPE_HASH, input.importEnvelopeHash())
                .set(QUESTION_REVISION.CREATED_BY, input.actorUserId())
                .set(QUESTION_REVISION.CREATED_AT, now)
                .execute();

        var update = database.update(QUESTION)
                .set(QUESTION.CURRENT_REVISION_NO, revisionNo)
                .set(QUESTION.EXTERNAL_KEY, input.externalKey())
                .set(QUESTION.UPDATED_BY, input.actorUserId())
                .set(QUESTION.UPDATED_AT, now);
        update.where(QUESTION.QUESTION_ID.eq(questionId)).execute();
        observeImport(input, questionId, revisionId, now);
        return new QuestionImportResult(questionId, revisionId, revisionNo, input.reviewStatus(), inserted == 1, true);
    }

    private void observeImport(
            NormalizedQuestionRevision input,
            UUID questionId,
            UUID questionRevisionId,
            OffsetDateTime observedAt) {
        database.insertInto(QUESTION_IMPORT_OBSERVATION)
                .set(QUESTION_IMPORT_OBSERVATION.QUESTION_IMPORT_OBSERVATION_ID, UUID.randomUUID())
                .set(QUESTION_IMPORT_OBSERVATION.QUESTION_ID, questionId)
                .set(QUESTION_IMPORT_OBSERVATION.QUESTION_REVISION_ID, questionRevisionId)
                .set(QUESTION_IMPORT_OBSERVATION.WORKSPACE_ID, input.workspaceId())
                .set(QUESTION_IMPORT_OBSERVATION.SOURCE_PAYLOAD_HASH, input.sourcePayloadHash())
                .set(QUESTION_IMPORT_OBSERVATION.IMPORT_ENVELOPE_HASH, input.importEnvelopeHash())
                .set(QUESTION_IMPORT_OBSERVATION.PROVENANCE_JSON, json(input.provenance()))
                .set(QUESTION_IMPORT_OBSERVATION.OBSERVED_BY, input.actorUserId())
                .set(QUESTION_IMPORT_OBSERVATION.OBSERVED_AT, observedAt)
                .onConflict(
                        QUESTION_IMPORT_OBSERVATION.QUESTION_REVISION_ID,
                        QUESTION_IMPORT_OBSERVATION.IMPORT_ENVELOPE_HASH)
                .doNothing()
                .execute();
    }

    @Override
    public List<QuestionSearchItem> search(
            UUID workspaceId,
            String reviewStatus,
            String query,
            String subject,
            String stage,
            String grade,
            String questionType,
            Integer difficultyStars,
            QuestionSearchCursor cursor,
            int fetchLimit) {
        Condition filter = QUESTION.WORKSPACE_ID.eq(workspaceId)
                .and(QUESTION.STATUS.eq("active"))
                .and(QUESTION_REVISION.REVIEW_STATUS.eq(reviewStatus));
        if (!subject.isBlank()) filter = filter.and(QUESTION_REVISION.SUBJECT.eq(subject));
        if (!stage.isBlank()) filter = filter.and(QUESTION_REVISION.STAGE.eq(stage));
        if (!grade.isBlank()) filter = filter.and(QUESTION_REVISION.GRADE.eq(grade));
        if (!questionType.isBlank()) filter = filter.and(QUESTION_REVISION.QUESTION_TYPE.eq(questionType));
        if (difficultyStars != null) {
            filter = filter.and(QUESTION_REVISION.DIFFICULTY_STARS.eq(difficultyStars.shortValue()));
        }
        if (!query.isBlank()) filter = filter.and(searchText().containsIgnoreCase(query));
        if (cursor != null) {
            filter = filter.and(QUESTION_REVISION.CREATED_AT.lt(cursor.revisionCreatedAt())
                    .or(QUESTION_REVISION.CREATED_AT.eq(cursor.revisionCreatedAt())
                            .and(QUESTION.QUESTION_ID.gt(cursor.questionId()))));
        }

        // 已发布检索始终沿用明确的生产修订指针，即使存在更新的待审核修订也不改变结果。
        // 审核队列只查看当前修订，防止已被替代的导入尝试重新进入待办。
        Condition revisionJoin = QUESTION_REVISION.WORKSPACE_ID.eq(QUESTION.WORKSPACE_ID);
        if (reviewStatus.equals("approved")) {
            revisionJoin = revisionJoin.and(QUESTION_REVISION.QUESTION_REVISION_ID.eq(QUESTION.APPROVED_REVISION_ID));
        } else {
            revisionJoin = revisionJoin
                    .and(QUESTION_REVISION.QUESTION_ID.eq(QUESTION.QUESTION_ID))
                    .and(QUESTION_REVISION.REVISION_NO.eq(QUESTION.CURRENT_REVISION_NO));
        }

        Condition referenced = DSL.exists(DSL.selectOne().from(EDITOR_QUESTION_REFERENCE)
                        .where(EDITOR_QUESTION_REFERENCE.WORKSPACE_ID.eq(workspaceId))
                        .and(EDITOR_QUESTION_REFERENCE.QUESTION_ID.eq(QUESTION.QUESTION_ID)))
                .or(DSL.exists(DSL.selectOne().from(QUESTION_COLLECTION_ITEM)
                        .where(QUESTION_COLLECTION_ITEM.WORKSPACE_ID.eq(workspaceId))
                        .and(QUESTION_COLLECTION_ITEM.QUESTION_ID.eq(QUESTION.QUESTION_ID))))
                .or(DSL.exists(DSL.selectOne().from(QUESTION_COLLECTION_SNAPSHOT_ITEM)
                        .where(QUESTION_COLLECTION_SNAPSHOT_ITEM.WORKSPACE_ID.eq(workspaceId))
                        .and(QUESTION_COLLECTION_SNAPSHOT_ITEM.QUESTION_ID.eq(QUESTION.QUESTION_ID))));
        Field<Boolean> referencedField = DSL.when(referenced, true).otherwise(false).as("referenced");

        return database.select(
                        QUESTION.QUESTION_ID,
                        QUESTION_REVISION.QUESTION_REVISION_ID,
                        QUESTION.EXTERNAL_KEY,
                        QUESTION_REVISION.REVIEW_STATUS,
                        QUESTION_REVISION.SUBJECT,
                        QUESTION_REVISION.STAGE,
                        QUESTION_REVISION.GRADE,
                        QUESTION_REVISION.QUESTION_TYPE,
                        QUESTION_REVISION.TITLE,
                        QUESTION_REVISION.PRIMARY_KNOWLEDGE_TAG,
                        QUESTION_REVISION.DIFFICULTY_STARS,
                        QUESTION_REVISION.STEM_MARKDOWN,
                        QUESTION_REVISION.PROVENANCE_JSON,
                        QUESTION_REVISION.APPROVED_AT,
                        QUESTION_REVISION.CREATED_AT,
                        referencedField)
                .from(QUESTION)
                .join(QUESTION_REVISION)
                .on(revisionJoin)
                .where(filter)
                .orderBy(QUESTION_REVISION.CREATED_AT.desc(), QUESTION.QUESTION_ID.asc())
                .limit(fetchLimit)
                .fetch(record -> new QuestionSearchItem(
                        record.get(QUESTION.QUESTION_ID),
                        record.get(QUESTION_REVISION.QUESTION_REVISION_ID),
                        record.get(QUESTION.EXTERNAL_KEY),
                        record.get(QUESTION_REVISION.REVIEW_STATUS),
                        record.get(QUESTION_REVISION.SUBJECT),
                        record.get(QUESTION_REVISION.STAGE),
                        record.get(QUESTION_REVISION.GRADE),
                        record.get(QUESTION_REVISION.QUESTION_TYPE),
                        record.get(QUESTION_REVISION.TITLE),
                        record.get(QUESTION_REVISION.PRIMARY_KNOWLEDGE_TAG),
                        record.get(QUESTION_REVISION.DIFFICULTY_STARS) == null
                                ? null : record.get(QUESTION_REVISION.DIFFICULTY_STARS).intValue(),
                        record.get(QUESTION_REVISION.STEM_MARKDOWN),
                        parse(record.get(QUESTION_REVISION.PROVENANCE_JSON)),
                        record.get(QUESTION_REVISION.REVIEW_STATUS).equals("approved"),
                        Boolean.TRUE.equals(record.get(referencedField)),
                        record.get(QUESTION_REVISION.APPROVED_AT),
                        record.get(QUESTION_REVISION.CREATED_AT)));
    }

    @Override
    public List<QuestionRevisionDescriptor> findAll(UUID workspaceId, List<UUID> revisionIds) {
        if (revisionIds == null || revisionIds.isEmpty()) return List.of();
        var byId = database.selectFrom(QUESTION_REVISION)
                .where(QUESTION_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_REVISION.QUESTION_REVISION_ID.in(revisionIds))
                .fetchMap(QUESTION_REVISION.QUESTION_REVISION_ID);
        var ordered = new ArrayList<QuestionRevisionDescriptor>(revisionIds.size());
        for (UUID id : revisionIds) {
            var record = byId.get(id);
            if (record == null) continue;
            ordered.add(new QuestionRevisionDescriptor(
                    record.getQuestionId(), record.getQuestionRevisionId(), record.getRevisionNo(),
                    record.getReviewStatus(), record.getSubject(), record.getStage(), record.getGrade(),
                    record.getQuestionType(), record.getTitle(), record.getMaterialMarkdown(), record.getStemMarkdown(),
                    parse(record.getOptionsJson()), record.getAnswerMarkdown(), record.getAnalysisMarkdown(),
                    parse(record.getContentJson()), parse(record.getProvenanceJson()), record.getContentHash()));
        }
        return List.copyOf(ordered);
    }

    @Override
    public Optional<QuestionReviewTarget> findTarget(UUID workspaceId, UUID questionRevisionId) {
        return database.select(
                        QUESTION_REVISION.QUESTION_ID,
                        QUESTION_REVISION.QUESTION_REVISION_ID,
                        QUESTION_REVISION.REVIEW_STATUS,
                        QUESTION_REVISION.CONTENT_HASH)
                .from(QUESTION_REVISION)
                .where(QUESTION_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_REVISION.QUESTION_REVISION_ID.eq(questionRevisionId))
                .fetchOptional(record -> new QuestionReviewTarget(
                        record.get(QUESTION_REVISION.QUESTION_ID),
                        record.get(QUESTION_REVISION.QUESTION_REVISION_ID),
                        record.get(QUESTION_REVISION.REVIEW_STATUS),
                        record.get(QUESTION_REVISION.CONTENT_HASH)));
    }

    @Override
    public void applyDecision(
            UUID workspaceId,
            UUID actorUserId,
            UUID questionRevisionId,
            String expectedContentHash,
            String decision) {
        var revision = database.select(
                        QUESTION_REVISION.QUESTION_ID,
                        QUESTION_REVISION.REVIEW_STATUS,
                        QUESTION_REVISION.CONTENT_HASH)
                .from(QUESTION_REVISION)
                .where(QUESTION_REVISION.WORKSPACE_ID.eq(workspaceId))
                .and(QUESTION_REVISION.QUESTION_REVISION_ID.eq(questionRevisionId))
                .forUpdate()
                .fetchOne();
        if (revision == null) throw new QuestionReviewStateException("review_question_revision_not_found");
        if (!revision.get(QUESTION_REVISION.CONTENT_HASH).equals(expectedContentHash)) {
            throw new QuestionReviewStateException("review_question_content_changed");
        }
        if (!java.util.Set.of("unreviewed", "pending_review")
                .contains(revision.get(QUESTION_REVISION.REVIEW_STATUS))) {
            throw new QuestionReviewStateException("review_question_already_decided");
        }

        OffsetDateTime now = OffsetDateTime.now();
        database.update(QUESTION_REVISION)
                .set(QUESTION_REVISION.REVIEW_STATUS, decision)
                .set(QUESTION_REVISION.APPROVED_AT, decision.equals("approved") ? now : null)
                .where(QUESTION_REVISION.QUESTION_REVISION_ID.eq(questionRevisionId))
                .execute();
        var questionUpdate = database.update(QUESTION)
                .set(QUESTION.UPDATED_BY, actorUserId)
                .set(QUESTION.UPDATED_AT, now);
        if (decision.equals("approved")) {
            questionUpdate.set(QUESTION.APPROVED_REVISION_ID, questionRevisionId);
        }
        questionUpdate.where(QUESTION.QUESTION_ID.eq(revision.get(QUESTION_REVISION.QUESTION_ID)))
                .and(QUESTION.WORKSPACE_ID.eq(workspaceId))
                .execute();
    }

    @Override
    public void linkSource(QuestionSourceEvidenceCommand command) {
        database.insertInto(QUESTION_SOURCE_LINK)
                .set(QUESTION_SOURCE_LINK.QUESTION_SOURCE_LINK_ID, UUID.randomUUID())
                .set(QUESTION_SOURCE_LINK.QUESTION_ID, command.questionId())
                .set(QUESTION_SOURCE_LINK.QUESTION_REVISION_ID, command.questionRevisionId())
                .set(QUESTION_SOURCE_LINK.WORKSPACE_ID, command.workspaceId())
                .set(QUESTION_SOURCE_LINK.SOURCE_DOCUMENT_ID, command.sourceDocumentId())
                .set(QUESTION_SOURCE_LINK.SOURCE_REGION_ID, command.sourceRegionId())
                .set(QUESTION_SOURCE_LINK.SOURCE_LABEL, command.sourceLabel())
                .set(QUESTION_SOURCE_LINK.SOURCE_PAGE_START, command.sourcePageStart())
                .set(QUESTION_SOURCE_LINK.SOURCE_PAGE_END, command.sourcePageEnd())
                .set(QUESTION_SOURCE_LINK.SOURCE_REF_JSON, json(command.sourceReference()))
                .onConflict(QUESTION_SOURCE_LINK.QUESTION_REVISION_ID)
                .doNothing()
                .execute();
    }

    @Override
    public void linkRelation(QuestionRelationCommand command) {
        database.insertInto(QUESTION_RELATION)
                .set(QUESTION_RELATION.PARENT_QUESTION_ID, command.parentQuestionId())
                .set(QUESTION_RELATION.CHILD_QUESTION_ID, command.childQuestionId())
                .set(QUESTION_RELATION.WORKSPACE_ID, command.workspaceId())
                .set(QUESTION_RELATION.RELATION_TYPE, command.relationType())
                .set(QUESTION_RELATION.SORT_ORDER, command.sortOrder())
                .onConflict(
                        QUESTION_RELATION.PARENT_QUESTION_ID,
                        QUESTION_RELATION.CHILD_QUESTION_ID,
                        QUESTION_RELATION.RELATION_TYPE)
                .doNothing()
                .execute();
    }

    private Field<String> searchText() {
        // 此表达式必须与 V004 的 trigram 索引保持一致。绑定值只承载查询文本，
        // 绝不能参与 SQL 结构拼接。
        return DSL.lower(DSL.concat(
                DSL.coalesce(QUESTION_REVISION.TITLE, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.SUBJECT, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.STAGE, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.GRADE, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.QUESTION_TYPE, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.LESSON, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.PRIMARY_KNOWLEDGE_TAG, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.MATERIAL_MARKDOWN, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.STEM_MARKDOWN, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.ANSWER_MARKDOWN, ""), DSL.inline(" "),
                DSL.coalesce(QUESTION_REVISION.ANALYSIS_MARKDOWN, "")));
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("question_json_not_serializable", exception);
        }
    }

    private JsonNode parse(JSON value) {
        try {
            return objectMapper.readTree(value.data());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored_question_json_invalid", exception);
        }
    }
}
