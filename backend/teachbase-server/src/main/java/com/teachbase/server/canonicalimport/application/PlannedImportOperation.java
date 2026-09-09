package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

/** 中文维护说明：Validate 阶段冻结的 DAG operation，执行期不得重新猜测依赖。 */
public record PlannedImportOperation(
        String operationKey,
        String operationType,
        int sequenceNo,
        List<String> dependencies,
        JsonNode payload,
        String payloadHash) {
}
