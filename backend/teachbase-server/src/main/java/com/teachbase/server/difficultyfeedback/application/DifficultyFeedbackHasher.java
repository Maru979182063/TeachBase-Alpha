package com.teachbase.server.difficultyfeedback.application;

import static com.teachbase.server.difficultyfeedback.api.DifficultyFeedbackContracts.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import org.springframework.stereotype.Component;

/** 中文维护说明：所有幂等与快照 hash 都先经过同一 canonical JSON 规则。 */
@Component
public class DifficultyFeedbackHasher {

    private final ObjectMapper mapper;

    public DifficultyFeedbackHasher(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    public HashedRubric hashRubric(RegisterRubricRequest request) {
        ObjectNode value = mapper.createObjectNode();
        value.put("workspaceId", request.workspaceId().toString());
        value.put("rubricKey", request.rubricKey());
        value.put("versionCode", request.versionCode());
        value.put("subject", request.subject());
        value.put("stage", request.stage());
        if (request.grade() == null || request.grade().isBlank()) value.putNull("grade");
        else value.put("grade", request.grade().trim());
        value.put("scaleMin", 1);
        value.put("scaleMax", 5);
        JsonNode definitions = canonical(request.definitions());
        value.set("definitions", definitions);
        value.put("status", request.status());
        return new HashedRubric(hash(value), definitions);
    }

    public HashedRun hashRun(RegisterAssessmentRunRequest request, String rubricKey) {
        ObjectNode value = mapper.createObjectNode();
        value.put("workspaceId", request.workspaceId().toString());
        value.put("externalRunKey", request.externalRunKey());
        value.put("rubricVersionId", request.rubricVersionId().toString());
        value.put("rubricKey", rubricKey);
        value.put("modelProvider", request.modelProvider());
        value.put("modelName", request.modelName());
        value.put("modelVersion", request.modelVersion());
        value.put("promptProfileVersion", request.promptProfileVersion());
        value.put("evidencePackageKey", request.evidencePackageKey());
        value.put("evidencePackageVersion", request.evidencePackageVersion());
        value.put("evidencePackageHash", request.evidencePackageHash());
        value.put("producerVersion", request.producerVersion());
        value.put("runtimeVersion", request.runtimeVersion());
        JsonNode parameters = canonical(request.parameters());
        value.set("parameters", parameters);
        value.put("status", request.status());
        value.put("startedAt", request.startedAt().toInstant().toString());
        value.put("completedAt", request.completedAt().toInstant().toString());
        return new HashedRun(hash(parameters), hash(value), parameters);
    }

    public String contextHash(JsonNode context) {
        return hash(context);
    }

    public String snapshotHash(
            String kind,
            java.util.UUID rubricVersionId,
            String contextKey,
            String contextHash,
            Integer difficultyValue,
            java.math.BigDecimal confidence,
            java.util.UUID runId,
            java.util.UUID actorId,
            JsonNode modelContext) {
        ObjectNode value = mapper.createObjectNode();
        value.put("snapshotKind", kind);
        value.put("rubricVersionId", rubricVersionId.toString());
        value.put("contextKey", contextKey);
        value.put("contextHash", contextHash);
        if (difficultyValue == null) value.putNull("difficultyValue");
        else value.put("difficultyValue", difficultyValue);
        if (confidence == null) value.putNull("confidence");
        else value.put("confidence", confidence.stripTrailingZeros().toPlainString());
        if (runId == null) value.putNull("assessmentRunId");
        else value.put("assessmentRunId", runId.toString());
        value.put("createdBy", actorId.toString());
        value.set("modelOutputContext", canonical(modelContext));
        return hash(value);
    }

    public String feedbackRequestHash(
            java.util.UUID questionRevisionId, SubmitDifficultyFeedbackRequest request) {
        ObjectNode value = mapper.createObjectNode();
        value.put("questionRevisionId", questionRevisionId.toString());
        value.put("workspaceId", request.workspaceId().toString());
        value.put("actorUserId", request.actorUserId().toString());
        value.put("rubricKey", request.rubricKey());
        value.put("rubricVersionId", request.rubricVersionId().toString());
        value.put("contextKey", request.contextKey());
        value.put("beforeSnapshotId", request.beforeSnapshotId().toString());
        value.put("expectedStateVersion", request.expectedStateVersion());
        value.put("clientMutationId", request.clientMutationId());
        if (request.finalDifficultyValue() == null) value.putNull("finalDifficultyValue");
        else value.put("finalDifficultyValue", request.finalDifficultyValue());
        ArrayNode reasons = value.putArray("reasonCodes");
        request.reasonCodes().stream().distinct().sorted().forEach(reasons::add);
        value.put("note", request.note() == null ? "" : request.note());
        if (request.rubricGap() == null) value.putNull("rubricGap");
        else {
            ObjectNode gap = value.putObject("rubricGap");
            gap.put("expectedDifficultyText", request.rubricGap().expectedDifficultyText());
            gap.put("explanation", request.rubricGap().explanation());
        }
        return hash(value);
    }

    public JsonNode canonical(JsonNode node) {
        if (node == null || node.isNull()) return mapper.nullNode();
        if (node.isNumber()) return mapper.getNodeFactory().numberNode(node.decimalValue().stripTrailingZeros());
        if (node.isValueNode()) return node.deepCopy();
        if (node.isArray()) {
            ArrayNode result = mapper.createArrayNode();
            node.forEach(item -> result.add(canonical(item)));
            return result;
        }
        ObjectNode result = mapper.createObjectNode();
        node.properties().stream().sorted(Comparator.comparing(java.util.Map.Entry::getKey))
                .forEach(entry -> result.set(entry.getKey(), canonical(entry.getValue())));
        return result;
    }

    private String hash(JsonNode value) {
        try {
            byte[] bytes = mapper.writeValueAsString(canonical(value)).getBytes(StandardCharsets.UTF_8);
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException | com.fasterxml.jackson.core.JsonProcessingException exception) {
            throw new IllegalStateException("无法计算难度反馈 SHA-256", exception);
        }
    }

    public record HashedRubric(String rubricHash, JsonNode definitions) {
    }

    public record HashedRun(String parametersHash, String runHash, JsonNode parameters) {
    }
}
