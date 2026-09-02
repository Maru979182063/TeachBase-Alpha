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
    void projectsCanonicalKeysAndBothLegacyCommonLabels() throws Exception {
        JsonNode master = objectMapper.readTree("""
                {"type":"doc","content":[
                  {"type":"questionReference","attrs":{"questionId":"basic","targetLayers":"basic"}},
                  {"type":"questionReference","attrs":{"questionId":"common-key","targetLayers":"common"}},
                  {"type":"questionReference","attrs":{"questionId":"common-standard-label","targetLayers":"常用版"}},
                  {"type":"questionReference","attrs":{"questionId":"common-legacy-label","targetLayers":"常规版"}},
                  {"type":"questionReference","attrs":{"questionId":"all","targetLayers":"basic,advanced,common"}}
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
        assertThat(questionIds(common)).containsExactly(
                "common-key", "common-standard-label", "common-legacy-label", "all");
    }

    private java.util.List<String> questionIds(JsonNode document) {
        java.util.List<String> result = new java.util.ArrayList<>();
        document.path("content").forEach(node -> result.add(node.path("attrs").path("questionId").asText()));
        return result;
    }
}
