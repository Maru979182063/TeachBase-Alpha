package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/** Fully parsed package whose byte digest, bindings, references, and counts passed validation. */
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
