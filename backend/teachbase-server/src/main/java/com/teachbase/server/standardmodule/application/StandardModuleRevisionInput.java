package com.teachbase.server.standardmodule.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** 中文维护说明：完成规范化和哈希计算后的仓储输入。 */
public record StandardModuleRevisionInput(
        UUID workspaceId,
        UUID actorUserId,
        String moduleKey,
        String moduleType,
        String title,
        String subject,
        String stage,
        String grade,
        int schemaVersion,
        JsonNode content,
        String contentHash) {
}
