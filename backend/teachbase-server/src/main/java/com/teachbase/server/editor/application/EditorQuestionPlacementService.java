package com.teachbase.server.editor.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.editor.api.PlaceQuestionReferencesRequest;
import com.teachbase.server.editor.api.QuestionPlacementItem;
import com.teachbase.server.question.api.QuestionRevisionDescriptor;
import com.teachbase.server.question.api.QuestionRevisionDirectory;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 中文维护说明：本文件属于在线编辑文档模块的业务规则与事务编排层，负责业务校验和用例编排，不应泄漏数据库记录或传输层对象。
 * 中文维护说明：一次乐观锁草稿更新可落位多道检索题；每个引用节点保存已展开 Markdown，
 * 因而 snapshot 不需要读取可变题目状态。
 */
@Service
public class EditorQuestionPlacementService {

    private final EditorDocumentService documents;
    private final QuestionRevisionDirectory revisions;
    private final ObjectMapper objectMapper;

    public EditorQuestionPlacementService(
            EditorDocumentService documents,
            QuestionRevisionDirectory revisions,
            ObjectMapper objectMapper) {
        this.documents = documents;
        this.revisions = revisions;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public EditorDraft place(UUID documentId, PlaceQuestionReferencesRequest request) {
        if (request.expectedDraftVersion() < 1) {
            throw new EditorContentValidationException("expected_draft_version_must_be_positive");
        }
        List<String> layers = normalizeLayers(request.targetLayers());
        List<UUID> revisionIds = request.questions().stream().map(QuestionPlacementItem::questionRevisionId).toList();
        if (revisionIds.size() != new HashSet<>(revisionIds).size()) {
            throw new EditorContentValidationException("duplicate_question_revision_placement");
        }
        List<QuestionRevisionDescriptor> resolved = revisions.findAll(request.workspaceId(), revisionIds);
        if (resolved.size() != revisionIds.size()) {
            throw new EditorContentValidationException("question_revision_not_found");
        }
        if (resolved.stream().anyMatch(question -> !question.reviewStatus().equals("approved"))) {
            throw new EditorContentValidationException("question_revision_not_approved");
        }

        EditorDraft current = documents.get(documentId, request.workspaceId(), request.actorUserId());
        if (current.draftVersion() != request.expectedDraftVersion()) {
            throw new EditorRevisionConflictException(current.draftVersion());
        }
        ObjectNode master = current.masterDoc().deepCopy();
        ArrayNode content = master.withArray("content");
        int insertionIndex = request.insertionIndex();
        if (insertionIndex < 0 || insertionIndex > content.size()) {
            throw new EditorContentValidationException("question_insertion_index_invalid");
        }
        ArrayNode updated = objectMapper.createArrayNode();
        for (int index = 0; index < insertionIndex; index++) updated.add(content.get(index));
        for (int index = 0; index < resolved.size(); index++) {
            updated.add(referenceNode(resolved.get(index), request.questions().get(index), layers));
        }
        for (int index = insertionIndex; index < content.size(); index++) updated.add(content.get(index));
        master.set("content", updated);

        EditorDraft saved = documents.update(new UpdateEditorDraftCommand(
                documentId, request.workspaceId(), request.actorUserId(), request.expectedDraftVersion(),
                request.clientMutationId(), current.schemaVersion(), master, current.versionOverrides()));
        // 正式引用索引绑定 immutable revision；autosave 阶段只把精确题目 revision
        // 写入 working draft，待 preview confirmation 冻结 revision 时再建立索引。
        return saved;
    }

    private ObjectNode referenceNode(
            QuestionRevisionDescriptor question, QuestionPlacementItem settings, List<String> layers) {
        String mode = settings.displayMode().trim();
        if (!Set.of("full", "stem_only", "compact").contains(mode)) {
            throw new EditorContentValidationException("question_display_mode_invalid");
        }
        ObjectNode node = objectMapper.createObjectNode();
        node.put("type", "questionReference");
        ObjectNode attrs = node.putObject("attrs");
        attrs.put("questionId", question.questionId().toString());
        attrs.put("questionRevisionId", question.questionRevisionId().toString());
        attrs.put("displayMode", mode);
        attrs.put("showAnswer", settings.showAnswer());
        attrs.put("showAnalysis", settings.showAnalysis());
        attrs.put("targetLayers", String.join(",", layers));
        attrs.put("studentMarkdown", markdown(question, false, false, false));
        attrs.put("teacherMarkdown", markdown(
                question, true, settings.showAnswer(), settings.showAnalysis()));
        return node;
    }

    private String markdown(
            QuestionRevisionDescriptor question, boolean teacher, boolean showAnswer, boolean showAnalysis) {
        List<String> sections = new ArrayList<>();
        if (!question.materialMarkdown().isBlank()) sections.add(question.materialMarkdown());
        sections.add(question.stemMarkdown());
        if (question.options().isArray() && !question.options().isEmpty()) {
            List<String> options = new ArrayList<>();
            int index = 0;
            for (JsonNode option : question.options()) {
                String label = Character.toString('A' + index++);
                if (option.isObject()) {
                    label = option.path("label").asText(label);
                    String text = option.path("text").asText(option.path("content").asText());
                    options.add(label + ". " + text);
                } else {
                    options.add(label + ". " + option.asText());
                }
            }
            sections.add(String.join("\n", options));
        }
        if (teacher && showAnswer && !question.answerMarkdown().isBlank()) {
            sections.add("**答案**\n\n" + question.answerMarkdown());
        }
        if (teacher && showAnalysis && !question.analysisMarkdown().isBlank()) {
            sections.add("**解析**\n\n" + question.analysisMarkdown());
        }
        return String.join("\n\n", sections).strip();
    }

    private List<String> normalizeLayers(List<String> requested) {
        var result = requested.stream().map(String::trim).distinct().toList();
        if (result.isEmpty() || result.stream().anyMatch(layer -> !EditorVariantContract.isKey(layer))) {
            throw new EditorContentValidationException("question_target_layers_invalid");
        }
        return result;
    }
}
