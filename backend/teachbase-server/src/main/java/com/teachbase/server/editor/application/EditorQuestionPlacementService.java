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
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Places many searched questions with one optimistic editor update. Hydrated Markdown
 * is saved into each reference node so snapshots never consult mutable question state.
 */
@Service
public class EditorQuestionPlacementService {

    private static final Map<String, String> LAYER_LABELS = Map.of(
            "basic", "基础版", "advanced", "进阶版", "common", "常规版");
    private final EditorDocumentService documents;
    private final QuestionRevisionDirectory revisions;
    private final EditorQuestionReferenceRepository referenceIndex;
    private final ObjectMapper objectMapper;

    public EditorQuestionPlacementService(
            EditorDocumentService documents,
            QuestionRevisionDirectory revisions,
            EditorQuestionReferenceRepository referenceIndex,
            ObjectMapper objectMapper) {
        this.documents = documents;
        this.revisions = revisions;
        this.referenceIndex = referenceIndex;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public EditorDraft place(UUID documentId, PlaceQuestionReferencesRequest request) {
        if (request.expectedRevisionNo() < 1) {
            throw new EditorContentValidationException("expected_revision_must_be_positive");
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
        if (current.revisionNo() != request.expectedRevisionNo()) {
            throw new EditorRevisionConflictException(current.revisionNo());
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
                documentId, request.workspaceId(), request.actorUserId(), request.expectedRevisionNo(),
                current.schemaVersion(), master, current.versionOverrides()));
        ArrayNode layerJson = objectMapper.createArrayNode();
        layers.forEach(layerJson::add);
        referenceIndex.index(
                saved.editorRevisionId(), documentId, request.workspaceId(), request.actorUserId(),
                insertionIndex, resolved, layerJson);
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
        attrs.put("targetLayers", String.join(",", layers.stream().map(LAYER_LABELS::get).toList()));
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
        if (result.isEmpty() || result.stream().anyMatch(layer -> !LAYER_LABELS.containsKey(layer))) {
            throw new EditorContentValidationException("question_target_layers_invalid");
        }
        return result;
    }
}
