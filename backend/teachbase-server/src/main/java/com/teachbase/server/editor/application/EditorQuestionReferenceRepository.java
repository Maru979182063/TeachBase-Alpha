package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import java.util.List;
import java.util.UUID;

/** Relational usage index for question references already embedded in editor JSON. */
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
