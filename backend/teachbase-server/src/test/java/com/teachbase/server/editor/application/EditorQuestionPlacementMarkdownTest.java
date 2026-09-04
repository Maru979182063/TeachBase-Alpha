package com.teachbase.server.editor.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EditorQuestionPlacementMarkdownTest {
    @Test
    void preservesDocxOptionsSubquestionLabelsAndTeacherOnlyFields() throws Exception {
        var json = new ObjectMapper();
        var content = json.readTree("""
                {"subquestions":[{"label":"（1）","markdown":"（1）求交集。"}],
                 "teaching_note_md":"仅教师可见的提示"}
                """);
        var question = new QuestionRevisionDescriptor(UUID.randomUUID(), UUID.randomUUID(), 1, "approved",
                "数学", "", "", "composite", "", "", "求集合：",
                json.readTree("""
                    [{"label":"A","markdown":"$\\\\textcircled{1}$"},
                     {"label":"B","text":"旧格式选项"},{"label":"C","content":"兼容内容"}]
                    """), "答案只给教师", "推导只给教师", content, json.createObjectNode(), "a".repeat(64));
        String student = EditorQuestionPlacementService.markdown(question, false, false, false);
        String teacher = EditorQuestionPlacementService.markdown(question, true, true, true);
        assertThat(student).contains("A. $\\textcircled{1}$", "B. 旧格式选项", "C. 兼容内容", "（1）求交集。");
        assertThat(student).doesNotContain("答案只给教师", "推导只给教师", "仅教师可见的提示", "（1）（1）");
        assertThat(teacher).contains("答案只给教师", "推导只给教师", "仅教师可见的提示");
    }
}
