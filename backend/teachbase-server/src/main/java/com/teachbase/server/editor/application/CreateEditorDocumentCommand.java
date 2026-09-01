package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Validated controller-to-application command for editor aggregate creation.
 */
public record CreateEditorDocumentCommand(
        UUID workspaceId,
        UUID actorUserId,
        String documentKind,
        String title,
        int schemaVersion,
        JsonNode masterDoc,
        JsonNode versionOverrides) {
}
