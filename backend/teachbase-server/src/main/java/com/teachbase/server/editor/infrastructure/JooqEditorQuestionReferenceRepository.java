package com.teachbase.server.editor.infrastructure;

import static com.teachbase.jooq.tables.EditorQuestionReference.EDITOR_QUESTION_REFERENCE;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.editor.application.EditorQuestionReferenceRepository;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import org.jooq.DSLContext;
import org.jooq.JSON;
import org.springframework.stereotype.Repository;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的数据库或外部工具适配层，负责落实持久化合同；并发正确性最终由事务、锁和数据库约束共同保证。
 *
 * 英文术语对照：Persists the relational usage index corresponding to embedded editor references.
 */
@Repository
class JooqEditorQuestionReferenceRepository implements EditorQuestionReferenceRepository {

    private final DSLContext database;
    private final ObjectMapper objectMapper;

    JooqEditorQuestionReferenceRepository(DSLContext database, ObjectMapper objectMapper) {
        this.database = database;
        this.objectMapper = objectMapper;
    }

    @Override
    public void index(
            UUID editorRevisionId,
            UUID editorDocumentId,
            UUID workspaceId,
            UUID actorUserId,
            int insertionIndex,
            List<QuestionRevisionDescriptor> questions,
            JsonNode targetLayers) {
        OffsetDateTime now = OffsetDateTime.now();
        for (int index = 0; index < questions.size(); index++) {
            QuestionRevisionDescriptor question = questions.get(index);
            database.insertInto(EDITOR_QUESTION_REFERENCE)
                    .set(EDITOR_QUESTION_REFERENCE.EDITOR_QUESTION_REFERENCE_ID, UUID.randomUUID())
                    .set(EDITOR_QUESTION_REFERENCE.EDITOR_REVISION_ID, editorRevisionId)
                    .set(EDITOR_QUESTION_REFERENCE.EDITOR_DOCUMENT_ID, editorDocumentId)
                    .set(EDITOR_QUESTION_REFERENCE.WORKSPACE_ID, workspaceId)
                    .set(EDITOR_QUESTION_REFERENCE.QUESTION_ID, question.questionId())
                    .set(EDITOR_QUESTION_REFERENCE.QUESTION_REVISION_ID, question.questionRevisionId())
                    .set(EDITOR_QUESTION_REFERENCE.PLACEMENT_KEY, UUID.randomUUID())
                    .set(EDITOR_QUESTION_REFERENCE.POSITION_INDEX, insertionIndex + index)
                    .set(EDITOR_QUESTION_REFERENCE.TARGET_LAYERS_JSON, json(targetLayers))
                    .set(EDITOR_QUESTION_REFERENCE.CREATED_BY, actorUserId)
                    .set(EDITOR_QUESTION_REFERENCE.CREATED_AT, now)
                    .execute();
        }
    }

    private JSON json(JsonNode value) {
        try {
            return JSON.valueOf(objectMapper.writeValueAsString(value));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("editor_question_reference_not_serializable", exception);
        }
    }
}
