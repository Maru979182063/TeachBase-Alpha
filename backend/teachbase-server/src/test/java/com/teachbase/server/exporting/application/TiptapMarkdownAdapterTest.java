package com.teachbase.server.exporting.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

class TiptapMarkdownAdapterTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final TiptapMarkdownAdapter adapter = new TiptapMarkdownAdapter(objectMapper);

    @Test
    void rendersStudentBlanksLatexMindMapAndHydratedQuestion() throws Exception {
        var frozen = objectMapper.readTree("""
                {
                  "schemaVersion": 1,
                  "audience": "student",
                  "projectedDoc": {
                    "type": "doc",
                    "content": [
                      {"type":"paragraph","content":[
                        {"type":"text","text":"答案","marks":[{"type":"studentBlank","attrs":{"id":"b1"}}]},
                        {"type":"inlineMath","attrs":{"latex":"\\\\frac{x}{2}"}}
                      ]},
                      {"type":"mindMap","attrs":{
                        "title":"关系",
                        "nodes":[{"id":"root","text":"根","children":[{"id":"child","text":"分支","children":[]}]}],
                        "studentBlankNodeIds":["child"]
                      }},
                      {"type":"questionReference","attrs":{
                        "questionId":"q1","studentMarkdown":"原题：求 $x$。"
                      }}
                    ]
                  }
                }
                """);

        var source = adapter.adapt(frozen);

        assertThat(source.schemaVersion()).isEqualTo(1);
        assertThat(source.adapterVersion()).isEqualTo("tiptap-pandoc-v1");
        assertThat(source.markdown()).contains("____$\\frac{x}{2}$", "- 根", "  - ____", "原题：求 $x$。");
        assertThat(source.markdown()).doesNotContain("分支");
    }

    @Test
    void failsClosedWhenQuestionReferenceIsNotHydrated() throws Exception {
        var frozen = objectMapper.readTree("""
                {
                  "schemaVersion":1,
                  "audience":"teacher",
                  "projectedDoc":{"type":"doc","content":[
                    {"type":"questionReference","attrs":{"questionId":"q-missing"}}
                  ]}
                }
                """);

        assertThatThrownBy(() -> adapter.adapt(frozen))
                .isInstanceOf(RenderSourceException.class)
                .hasMessage("question_reference_not_hydrated:q-missing");
    }
}
