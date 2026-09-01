package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import java.util.List;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的业务规则与事务编排层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Relational usage index for question references already embedded in editor JSON.
 */
public interface EditorQuestionReferenceRepository {

    void index(
            UUID editorRevisionId,
            UUID editorDocumentId,
            UUID workspaceId,
            UUID actorUserId,
            int insertionIndex,
            List<QuestionRevisionDescriptor> questions,
            JsonNode targetLayers);
}
