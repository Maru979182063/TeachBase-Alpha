package com.teachbase.server.canonicalimport.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.teachbase.server.question.api.QuestionImportItem;

/** 中文维护说明：将 G5 question 节点映射到既有 Question 领域合同，不复制哈希规则。 */
final class CanonicalImportPayloadMapper {

    private CanonicalImportPayloadMapper() {
    }

    static QuestionImportItem question(JsonNode value) {
        return new QuestionImportItem(
                text(value, "questionKey"), text(value, "sourceSystem"), text(value, "sourceKey"),
                optional(value, "reviewStatus", "pending_review"), text(value, "subject"),
                optional(value, "stage", ""), optional(value, "grade", ""), text(value, "questionType"),
                optional(value, "title", ""), optional(value, "lesson", ""),
                optional(value, "primaryKnowledgeTag", ""),
                node(value, "secondaryKnowledgeTags", JsonNodeFactory.instance.arrayNode()),
                value.path("difficultyStars").isIntegralNumber() ? value.path("difficultyStars").asInt() : null,
                optional(value, "materialMarkdown", ""), text(value, "stemMarkdown"),
                node(value, "options", JsonNodeFactory.instance.arrayNode()),
                optional(value, "answerMarkdown", ""), optional(value, "analysisMarkdown", ""),
                node(value, "content", JsonNodeFactory.instance.objectNode()),
                node(value, "provenance", JsonNodeFactory.instance.objectNode()),
                optional(value, "contentHash", ""), optional(value, "sourcePayloadHash", ""),
                optional(value, "importEnvelopeHash", ""));
    }

    static String text(JsonNode value, String field) {
        String result = value.path(field).asText("").trim();
        if (result.isEmpty()) throw new CanonicalImportValidationException("canonical_import_field_required:" + field);
        return result;
    }

    static String optional(JsonNode value, String field, String fallback) {
        return value.path(field).isTextual() ? value.path(field).asText().trim() : fallback;
    }

    static JsonNode node(JsonNode value, String field, JsonNode fallback) {
        JsonNode result = value.get(field);
        return result == null || result.isNull() ? fallback : result;
    }
}
