package com.teachbase.server.editor.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

class EditorContentValidatorTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final EditorContentValidator validator = new EditorContentValidator(objectMapper);

    @Test
    void acceptsFormulaMindMapAndStudentBlanks() throws Exception {
        JsonNode document = objectMapper.readTree("""
                {
                  "type": "doc",
                  "content": [
                    {"type":"paragraph","content":[
                      {"type":"text","text":"速度","marks":[{"type":"studentBlank","attrs":{"id":"blank-1"}}]},
                      {"type":"inlineMath","attrs":{"latex":"\\\\frac{\\\\text{速度}}{\\\\text{时间}}","mathml":""}}
                    ]},
                    {"type":"mindMap","attrs":{
                      "title":"中心主题",
                      "nodes":[{"id":"root","text":"中心主题","children":[{"id":"child-1","text":"分支","children":[]}]}],
                      "studentBlankNodeIds":"[\\"child-1\\"]"
                    }}
                  ]
                }
                """);
        JsonNode overrides = objectMapper.readTree("[null,null,null]");

        var result = validator.validate(1, document, overrides);

        assertThat(result.contentHash()).matches("[0-9a-f]{64}");
        assertThat(result.masterDoc().path("type").asText()).isEqualTo("doc");
    }

    @Test
    void canonicalHashDoesNotDependOnObjectFieldOrder() throws Exception {
        JsonNode first = objectMapper.readTree("{\"type\":\"doc\",\"content\":[]}");
        JsonNode second = objectMapper.readTree("{\"content\":[],\"type\":\"doc\"}");
        JsonNode overrides = objectMapper.readTree("[null,null,null]");

        assertThat(validator.validate(1, first, overrides).contentHash())
                .isEqualTo(validator.validate(1, second, overrides).contentHash());
    }

    @Test
    void rejectsBase64ImagesAndBlankMindMapRoot() throws Exception {
        JsonNode image = objectMapper.readTree("""
                {"type":"doc","content":[{"type":"image","attrs":{"src":"data:image/png;base64,AAAA"}}]}
                """);
        JsonNode mindMap = objectMapper.readTree("""
                {"type":"doc","content":[{"type":"mindMap","attrs":{
                  "nodes":[{"id":"root","text":"中心","children":[]}],
                  "studentBlankNodeIds":["root"]
                }}]}
                """);
        JsonNode overrides = objectMapper.readTree("[null,null,null]");

        assertThatThrownBy(() -> validator.validate(1, image, overrides))
                .isInstanceOf(EditorContentValidationException.class)
                .hasMessage("image_source_must_reference_registered_asset");
        assertThatThrownBy(() -> validator.validate(1, mindMap, overrides))
                .isInstanceOf(EditorContentValidationException.class)
                .hasMessage("mind_map_root_cannot_be_blank");
    }
}
