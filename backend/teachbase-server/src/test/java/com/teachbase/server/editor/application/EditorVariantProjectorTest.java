package com.teachbase.server.editor.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EditorVariantProjectorTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final EditorVariantProjector projector = new EditorVariantProjector(objectMapper);

    @Test
    void preservesPrototypeVariantOrderAndUsesFullOverride() throws Exception {
        JsonNode master = objectMapper.readTree("""
                {"type":"doc","content":[
                  {"type":"questionReference","attrs":{"questionId":"basic","targetLayers":"基础版"}},
                  {"type":"questionReference","attrs":{"questionId":"common","targetLayers":"常规版"}},
                  {"type":"questionReference","attrs":{"questionId":"all","targetLayers":"基础版,进阶版,常规版"}}
                ]}
                """);
        JsonNode overrides = objectMapper.readTree("""
                [null,{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"advanced override"}]}]},null]
                """);
        EditorDraft draft = new EditorDraft(
                UUID.randomUUID(), UUID.randomUUID(), "synchronized_handout", "test", UUID.randomUUID(),
                1, 1, master, overrides, "a".repeat(64));

        JsonNode basic = projector.project(draft, "basic");
        JsonNode advanced = projector.project(draft, "advanced");
        JsonNode common = projector.project(draft, "common");

        assertThat(questionIds(basic)).containsExactly("basic", "all");
        assertThat(advanced.at("/content/0/content/0/text").asText()).isEqualTo("advanced override");
        assertThat(questionIds(common)).containsExactly("common", "all");
    }

    private java.util.List<String> questionIds(JsonNode document) {
        java.util.List<String> result = new java.util.ArrayList<>();
        document.path("content").forEach(node -> result.add(node.path("attrs").path("questionId").asText()));
        return result;
    }
}
