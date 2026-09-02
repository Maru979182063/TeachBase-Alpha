package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的业务规则与事务编排层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Idempotent compare-and-set command for mutable working-draft autosave.
 */
public record UpdateEditorDraftCommand(
        UUID editorDocumentId,
        UUID workspaceId,
        UUID actorUserId,
        long expectedDraftVersion,
        String clientMutationId,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides) {
}
