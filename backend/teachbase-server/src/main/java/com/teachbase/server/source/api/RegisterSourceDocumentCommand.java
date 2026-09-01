package com.teachbase.server.source.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于题源证据模块的对外稳定合同层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Idempotent source-document registration keyed by a durable external source key.
 */
public record RegisterSourceDocumentCommand(
        UUID workspaceId,
        UUID actorUserId,
        UUID fileVersionId,
        String externalSourceKey,
        String sourceType,
        String subject,
        String stage,
        String grade,
        String title,
        JsonNode metadata) {
}
