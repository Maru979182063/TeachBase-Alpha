package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Canonical mutable editor state; publication still requires an immutable revision.
 */
public record EditorDraft(
        UUID editorDocumentId,
        UUID workspaceId,
        String documentKind,
        String title,
        UUID baseRevisionId,
        long baseRevisionNo,
        long draftVersion,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides,
        String contentHash,
        boolean idempotentReplay) {
}
