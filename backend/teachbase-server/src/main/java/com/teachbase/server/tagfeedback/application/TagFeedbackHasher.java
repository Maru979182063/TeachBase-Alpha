package com.teachbase.server.tagfeedback.application;

import static com.teachbase.server.tagfeedback.api.TagFeedbackContracts.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 中文维护说明：两个 hash 使用不同 canonical payload；标签集合 hash 不得混入运行和置信度上下文。
 */
@Component
public class TagFeedbackHasher {

    private final ObjectMapper mapper;

    public TagFeedbackHasher(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    public String labelSetHash(
            UUID taxonomyVersionId, UUID primaryNodeId, List<UUID> secondaryNodeIds) {
        ObjectNode value = mapper.createObjectNode();
        value.put("taxonomyVersionId", taxonomyVersionId.toString());
        if (primaryNodeId == null) {
            value.putNull("primaryNodeId");
        } else {
            value.put("primaryNodeId", primaryNodeId.toString());
        }
        ArrayNode secondary = value.putArray("secondaryNodeIds");
        secondaryNodeIds.stream()
                .distinct()
                .sorted(Comparator.comparing(UUID::toString))
                .forEach(id -> secondary.add(id.toString()));
        return hash(value);
    }

    public String snapshotHash(
            String snapshotKind,
            String labelSetHash,
            UUID taggingRunId,
            UUID createdBy,
            JsonNode modelOutputContext,
            List<SnapshotItemValue> items) {
        ObjectNode value = mapper.createObjectNode();
        value.put("snapshotKind", snapshotKind);
        value.put("labelSetHash", labelSetHash);
        if (taggingRunId == null) {
            value.putNull("taggingRunId");
        } else {
            value.put("taggingRunId", taggingRunId.toString());
        }
        value.put("createdBy", createdBy.toString());
        value.set("modelOutputContext", canonical(modelOutputContext));
        ArrayNode frozenItems = value.putArray("items");
        items.stream()
                .sorted(Comparator.comparing(SnapshotItemValue::relationType)
                        .thenComparing(item -> item.taxonomyNodeId().toString()))
                .forEach(item -> {
                    ObjectNode child = frozenItems.addObject();
                    child.put("taxonomyNodeId", item.taxonomyNodeId().toString());
                    child.put("relationType", item.relationType());
                    child.put("positionIndex", item.positionIndex());
                    if (item.confidence() == null) {
                        child.putNull("confidence");
                    } else {
                        child.put("confidence", decimal(item.confidence()));
                    }
                    if (item.candidateRank() == null) {
                        child.putNull("candidateRank");
                    } else {
                        child.put("candidateRank", item.candidateRank());
                    }
                });
        return hash(value);
    }

    public HashedRun hashRun(RegisterTaggingRunRequest request) {
        ObjectNode value = mapper.createObjectNode();
        value.put("workspaceId", request.workspaceId().toString());
        value.put("externalRunKey", request.externalRunKey());
        value.put("taxonomyVersionId", request.taxonomyVersionId().toString());
        value.put("modelProvider", request.modelProvider());
        value.put("modelName", request.modelName());
        value.put("modelVersion", request.modelVersion());
        value.put("promptProfileVersion", request.promptProfileVersion());
        value.put("candidatePackageKey", request.candidatePackageKey());
        value.put("candidatePackageVersion", request.candidatePackageVersion());
        value.put("candidatePackageHash", request.candidatePackageHash());
        value.put("producerVersion", request.producerVersion());
        value.put("runtimeVersion", request.runtimeVersion());
        JsonNode canonicalParameters = canonical(request.parameters());
        value.set("parameters", canonicalParameters);
        value.put("status", request.status());
        value.put("startedAt", request.startedAt().toInstant().toString());
        if (request.completedAt() == null) {
            value.putNull("completedAt");
        } else {
            value.put("completedAt", request.completedAt().toInstant().toString());
        }
        if (request.canonicalImportRequestId() == null) {
            value.putNull("canonicalImportRequestId");
        } else {
            value.put("canonicalImportRequestId", request.canonicalImportRequestId().toString());
        }
        return new HashedRun(hash(canonicalParameters), hash(value), canonicalParameters);
    }

    public String feedbackRequestHash(
            UUID questionRevisionId, SubmitTagFeedbackRequest request) {
        ObjectNode value = mapper.createObjectNode();
        value.put("questionRevisionId", questionRevisionId.toString());
        value.put("workspaceId", request.workspaceId().toString());
        value.put("actorUserId", request.actorUserId().toString());
        value.put("taxonomyKey", request.taxonomyKey());
        value.put("taxonomyVersionId", request.taxonomyVersionId().toString());
        value.put("beforeSnapshotId", request.beforeSnapshotId().toString());
        value.put("expectedStateVersion", request.expectedStateVersion());
        value.put("clientMutationId", request.clientMutationId());
        if (request.finalPrimaryNodeId() == null) {
            value.putNull("finalPrimaryNodeId");
        } else {
            value.put("finalPrimaryNodeId", request.finalPrimaryNodeId().toString());
        }
        ArrayNode secondary = value.putArray("finalSecondaryNodeIds");
        request.finalSecondaryNodeIds().stream()
                .distinct()
                .sorted(Comparator.comparing(UUID::toString))
                .forEach(id -> secondary.add(id.toString()));
        ArrayNode reasons = value.putArray("reasonCodes");
        request.reasonCodes().stream().distinct().sorted().forEach(reasons::add);
        value.put("note", request.note() == null ? "" : request.note());
        if (request.taxonomyGap() == null) {
            value.putNull("taxonomyGap");
        } else {
            ObjectNode gap = value.putObject("taxonomyGap");
            gap.put("expectedLabelText", request.taxonomyGap().expectedLabelText());
            gap.put("explanation", request.taxonomyGap().explanation());
        }
        return hash(value);
    }

    public JsonNode canonical(JsonNode node) {
        if (node == null || node.isNull()) {
            return mapper.nullNode();
        }
        if (node.isNumber()) {
            return mapper.getNodeFactory().numberNode(node.decimalValue().stripTrailingZeros());
        }
        if (node.isValueNode()) {
            return node.deepCopy();
        }
        if (node.isArray()) {
            ArrayNode result = mapper.createArrayNode();
            node.forEach(item -> result.add(canonical(item)));
            return result;
        }
        ObjectNode result = mapper.createObjectNode();
        node.properties().stream()
                .sorted(java.util.Map.Entry.comparingByKey())
                .forEach(entry -> result.set(entry.getKey(), canonical(entry.getValue())));
        return result;
    }

    private String decimal(BigDecimal value) {
        BigDecimal normalized = value.stripTrailingZeros();
        return normalized.signum() == 0 ? "0" : normalized.toPlainString();
    }

    private String hash(JsonNode node) {
        try {
            byte[] bytes = mapper.writeValueAsString(canonical(node)).getBytes(StandardCharsets.UTF_8);
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException | com.fasterxml.jackson.core.JsonProcessingException exception) {
            throw new IllegalStateException("无法计算标签反馈 SHA-256", exception);
        }
    }

    public record SnapshotItemValue(
            UUID taxonomyNodeId,
            String relationType,
            int positionIndex,
            BigDecimal confidence,
            Integer candidateRank) {
    }

    public record HashedRun(String parametersHash, String runHash, JsonNode canonicalParameters) {
    }
}
