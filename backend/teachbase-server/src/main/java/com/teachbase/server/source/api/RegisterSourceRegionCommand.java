package com.teachbase.server.source.api;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，封装跨层调用参数，不能用它绕过对应应用服务的校验。
 *
 * 英文术语对照：Idempotent addressable-region registration within a source document.
 */
public record RegisterSourceRegionCommand(
        UUID workspaceId,
        UUID actorUserId,
        UUID sourceDocumentId,
        String externalRegionKey,
        String regionType,
        Integer pageNo,
        Integer orderIndex,
        JsonNode boundingBox,
        String extractedText,
        JsonNode sourceReference) {
}
