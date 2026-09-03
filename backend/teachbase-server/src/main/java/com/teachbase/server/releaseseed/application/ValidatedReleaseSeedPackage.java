package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Fully parsed package whose byte digest, bindings, references, and counts passed validation.
 */
public record ValidatedReleaseSeedPackage(
        Path root,
        JsonNode manifest,
        JsonNode validationReport,
        JsonNode reviewReport,
        List<JsonNode> questions,
        List<JsonNode> rejectedQuestions,
        List<JsonNode> relations,
        List<JsonNode> sourceDocuments,
        List<JsonNode> sourceRegions,
        Map<String, JsonNode> sourceDocumentsByKey,
        Map<String, JsonNode> sourceRegionsByKey,
        String packageContentHash) {

    public String batchId() {
        return manifest.path("batchId").asText();
    }

    public String releaseVersion() {
        return manifest.path("releaseVersion").asText();
    }
}
