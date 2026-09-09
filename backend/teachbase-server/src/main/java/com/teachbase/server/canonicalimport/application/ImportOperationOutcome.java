package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.UUID;

/** 中文维护说明：一个领域 operation 成功后写入 ledger 的稳定目标与结果。 */
public record ImportOperationOutcome(
        UUID targetId,
        UUID targetRevisionId,
        String targetHash,
        JsonNode result) {
}
