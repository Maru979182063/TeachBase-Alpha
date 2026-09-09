package com.teachbase.server.handout.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.teachbase.server.handout.api.HandoutOccurrenceSourceInput;
import java.util.List;
import java.util.UUID;

/** 中文维护说明：资产 revision 已解析成稳定根 ID 后的 occurrence 仓储命令。 */
public record ResolvedHandoutOccurrence(
        String occurrenceKey,
        String parentOccurrenceKey,
        int positionIndex,
        String kind,
        UUID questionId,
        UUID questionRevisionId,
        UUID standardModuleId,
        UUID standardModuleRevisionId,
        JsonNode localContent,
        JsonNode attributes,
        List<HandoutOccurrenceSourceInput> sources) {
}
