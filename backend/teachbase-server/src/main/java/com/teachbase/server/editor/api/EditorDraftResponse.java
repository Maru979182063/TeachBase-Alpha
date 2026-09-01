package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.editor.application.EditorDraft;
import java.util.UUID;

/** Current immutable revision behind the mutable editor draft pointer. */
public record EditorDraftResponse(
        UUID editorDocumentId,
        UUID workspaceId,
        String documentKind,
        String title,
        UUID editorRevisionId,
        long revisionNo,
        String editorModel,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides,
        String contentHash) {

    static EditorDraftResponse from(EditorDraft draft) {
        return new EditorDraftResponse(
                draft.editorDocumentId(), draft.workspaceId(), draft.documentKind(), draft.title(),
                draft.editorRevisionId(), draft.revisionNo(), "master-overrides-v1", draft.schemaVersion(),
                draft.masterDoc(), draft.versionOverrides(), draft.contentHash());
    }
}
