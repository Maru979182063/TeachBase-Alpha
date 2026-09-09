package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

/** 中文维护说明：规范 package、服务端 hash 与显式 DAG 的不可变 validation 结果。 */
public record CanonicalImportPlan(
        String contractVersion,
        String producer,
        String packageKey,
        String packageHash,
        JsonNode canonicalPackage,
        List<PlannedImportOperation> operations) {
}
