package com.teachbase.server.handout.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

/** 中文维护说明：完成结构校验与内容哈希计算后的 edition 仓储命令。 */
public record ResolvedHandoutEdition(
        String editionKey,
        String editionRole,
        String canonicalTeacherEditionKey,
        int schemaVersion,
        JsonNode projectionRules,
        JsonNode delta,
        String contentHash,
        List<ResolvedHandoutOccurrence> occurrences) {
}
