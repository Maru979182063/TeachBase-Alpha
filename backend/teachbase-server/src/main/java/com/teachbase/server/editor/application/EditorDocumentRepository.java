package com.teachbase.server.editor.application;

import java.util.Optional;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，定义持久化端口，调用方只依赖业务所需的最小能力。
 *
 * 英文术语对照：Persistence port preserving immutable revisions and optimistic draft updates.
 */
public interface EditorDocumentRepository {

    EditorDraft create(CreateEditorDocumentCommand command, ValidatedEditorContent content);

    EditorDraft update(UpdateEditorDraftCommand command, ValidatedEditorContent content);

    Optional<EditorDraft> findDraft(UUID editorDocumentId, UUID workspaceId);

    EditorSnapshot createSnapshot(CreateEditorSnapshotCommand command, ValidatedEditorContent projectedContent);
}
