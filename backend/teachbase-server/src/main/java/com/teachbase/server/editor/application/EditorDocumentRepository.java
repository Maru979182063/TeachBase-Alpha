package com.teachbase.server.editor.application;

import java.util.Optional;
import java.util.UUID;

/** Persistence port preserving immutable revisions and optimistic draft updates. */
public interface EditorDocumentRepository {

    EditorDraft create(CreateEditorDocumentCommand command, ValidatedEditorContent content);

    EditorDraft update(UpdateEditorDraftCommand command, ValidatedEditorContent content);

    Optional<EditorDraft> findDraft(UUID editorDocumentId, UUID workspaceId);

    EditorSnapshot createSnapshot(CreateEditorSnapshotCommand command, ValidatedEditorContent projectedContent);
}
