package com.teachbase.server.releaseseed.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.question.api.QuestionImportItem;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：本文件属于首发数据包导入模块的业务规则与事务编排层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Deterministically maps a validated Seed row into the shared question import contract.
 */
@Component
public class ReleaseSeedQuestionMapper {

    private final ObjectMapper objectMapper;

    public ReleaseSeedQuestionMapper(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public QuestionImportItem map(
            ValidatedReleaseSeedPackage seedPackage,
            ReleaseSeedProperties properties,
            JsonNode row,
            int itemIndex) {
        JsonNode original = row.path("original");
        ObjectNode content = objectMapper.createObjectNode();
        content.put("schemaVersion", 1);
        content.set("original", original.deepCopy());
        content.set("sourceLocator", row.path("sourceLocator").deepCopy());

        ObjectNode provenance = objectMapper.createObjectNode();
        provenance.put("releaseSeedBatchId", seedPackage.batchId());
        provenance.put("releaseVersion", seedPackage.releaseVersion());
        provenance.put("packageContentSha256", seedPackage.packageContentHash());
        provenance.put("originalFileSha256", row.path("originalFileSha256").asText());
        provenance.set("sourceLocator", row.path("sourceLocator").deepCopy());
        provenance.set("tagging", row.path("tagging").deepCopy());
        provenance.set("review", row.path("review").deepCopy());
        if (row.path("sourceDocumentKey").isTextual()) {
            provenance.put("sourceDocumentKey", row.path("sourceDocumentKey").asText());
        }
        if (row.path("sourceRegionKey").isTextual()) {
            provenance.put("sourceRegionKey", row.path("sourceRegionKey").asText());
        }

        ObjectNode sourcePayload = objectMapper.createObjectNode();
        sourcePayload.put("sourceSystem", row.path("sourceSystem").asText());
        sourcePayload.put("sourceKey", row.path("sourceKey").asText());
        sourcePayload.put("originalFileSha256", row.path("originalFileSha256").asText());
        sourcePayload.set("sourceLocator", row.path("sourceLocator").deepCopy());
        sourcePayload.set("original", original.deepCopy());

        ObjectNode importEnvelope = objectMapper.createObjectNode();
        importEnvelope.put("packageContentSha256", seedPackage.packageContentHash());
        importEnvelope.put("itemIndex", itemIndex);
        importEnvelope.set("row", row.deepCopy());

        return new QuestionImportItem(
                row.path("externalKey").asText(),
                row.path("sourceSystem").asText(),
                row.path("sourceKey").asText(),
                "pending_review",
                text(row, "subject", properties.defaultSubject()),
                text(row, "stage", properties.defaultStage()),
                text(row, "grade", properties.defaultGrade()),
                text(row, "questionType", properties.defaultQuestionType()),
                text(row, "title", row.path("externalKey").asText()),
                text(row, "lesson", ""),
                row.path("primaryKnowledgeTag").asText(),
                row.path("secondaryKnowledgeTags").deepCopy(),
                row.path("difficultyStars").asInt(),
                original.path("material").isTextual() ? original.path("material").asText() : "",
                original.path("prompt").asText(),
                original.path("options").isArray() ? original.path("options").deepCopy() : objectMapper.createArrayNode(),
                markdown(original.path("answer")),
                original.path("explanation").isTextual() ? original.path("explanation").asText() : "",
                content,
                provenance,
                row.path("contentHash").asText(),
                sha256(canonicalize(sourcePayload)),
                sha256(canonicalize(importEnvelope)));
    }

    private String markdown(JsonNode value) {
        if (value == null || value.isNull() || value.isMissingNode()) return "";
        if (value.isTextual()) return value.asText();
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new ReleaseSeedValidationException("release_seed_answer_not_serializable", exception);
        }
    }

    private JsonNode canonicalize(JsonNode node) {
        if (node.isObject()) {
            ObjectNode result = objectMapper.createObjectNode();
            Map<String, JsonNode> fields = new TreeMap<>();
            Iterator<Map.Entry<String, JsonNode>> iterator = node.fields();
            iterator.forEachRemaining(entry -> fields.put(entry.getKey(), entry.getValue()));
            fields.forEach((key, value) -> result.set(key, canonicalize(value)));
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = objectMapper.createArrayNode();
            node.forEach(value -> result.add(canonicalize(value)));
            return result;
        }
        return node.deepCopy();
    }

    private String sha256(JsonNode value) {
        try {
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(objectMapper.writeValueAsBytes(value)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        } catch (JsonProcessingException exception) {
            throw new ReleaseSeedValidationException("release_seed_hash_payload_invalid", exception);
        }
    }

    private String text(JsonNode node, String field, String fallback) {
        return node.path(field).isTextual() && !node.path(field).asText().isBlank()
                ? node.path(field).asText().strip()
                : fallback == null ? "" : fallback.strip();
    }
}
