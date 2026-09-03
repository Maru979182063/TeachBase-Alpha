package com.teachbase.server.editor.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.editor.application.EditorDraft;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的对外稳定合同层，定义稳定传输合同；字段变更需要同时评估前端、测试和历史数据兼容性。
 *
 * 英文术语对照：Current working draft and the immutable revision it was based on, if any.
 */
public record EditorDraftResponse(
        UUID editorDocumentId,
        UUID workspaceId,
        String documentKind,
        String title,
        UUID baseRevisionId,
        long baseRevisionNo,
        long draftVersion,
        String editorModel,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides,
        String contentHash,
        boolean idempotentReplay) {

    static EditorDraftResponse from(EditorDraft draft) {
        return new EditorDraftResponse(
                draft.editorDocumentId(), draft.workspaceId(), draft.documentKind(), draft.title(),
                draft.baseRevisionId(), draft.baseRevisionNo(), draft.draftVersion(), "master-overrides-v1",
                draft.schemaVersion(), draft.masterDoc(), draft.versionOverrides(), draft.contentHash(),
                draft.idempotentReplay());
    }
}
