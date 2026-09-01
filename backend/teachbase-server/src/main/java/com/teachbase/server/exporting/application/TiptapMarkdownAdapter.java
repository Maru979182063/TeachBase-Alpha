package com.teachbase.server.exporting.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.stereotype.Component;

@Component
/**
 * Converts the backend-owned Tiptap subset into deterministic Pandoc Markdown.
 * Unsupported unresolved references fail closed instead of leaking internal IDs or
 * silently dropping teaching content from an export.
 */
public class TiptapMarkdownAdapter {

    static final String ADAPTER_VERSION = "tiptap-pandoc-v1";
    private static final List<String> MARKDOWN_FIELDS = List.of(
            "stemMarkdown", "contentMarkdown", "answerMarkdown", "analysisMarkdown",
            "explanationMarkdown", "teacherMarkdown", "studentMarkdown");
    private final ObjectMapper objectMapper;

    public TiptapMarkdownAdapter(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public RenderSourceDocument adapt(JsonNode frozenContent) {
        if (frozenContent == null || !frozenContent.isObject()) {
            throw new RenderSourceException("render_snapshot_invalid");
        }
        int schemaVersion = frozenContent.path("schemaVersion").asInt(-1);
        if (schemaVersion != 1) throw new RenderSourceException("unsupported_render_source_schema");
        String audience = frozenContent.path("audience").asText();
        if (!audience.equals("teacher") && !audience.equals("student")) {
            throw new RenderSourceException("render_audience_invalid");
        }
        JsonNode document = frozenContent.path("projectedDoc");
        if (!document.isObject() || !"doc".equals(document.path("type").asText())) {
            throw new RenderSourceException("render_projected_doc_missing");
        }
        StringBuilder markdown = new StringBuilder();
        renderChildren(document.path("content"), audience, markdown, 0);
        String normalized = markdown.toString().replaceAll("[ \\t]+\\R", "\n").strip() + "\n";
        return new RenderSourceDocument(schemaVersion, ADAPTER_VERSION, audience, normalized);
    }

    private void renderChildren(JsonNode content, String audience, StringBuilder output, int depth) {
        if (!content.isArray()) return;
        for (JsonNode child : content) renderNode(child, audience, output, depth);
    }

    private void renderNode(JsonNode node, String audience, StringBuilder output, int depth) {
        String type = node.path("type").asText();
        switch (type) {
            case "paragraph" -> {
                renderInlineChildren(node.path("content"), audience, output);
                output.append("\n\n");
            }
            case "heading" -> {
                int level = Math.max(1, Math.min(6, node.path("attrs").path("level").asInt(2)));
                output.append("#".repeat(level)).append(' ');
                renderInlineChildren(node.path("content"), audience, output);
                output.append("\n\n");
            }
            case "text" -> output.append(renderText(node, audience));
            case "hardBreak" -> output.append("  \n");
            case "inlineMath" -> output.append('$').append(formula(node)).append('$');
            case "blockMath", "formula" -> output.append("\n$$\n").append(formula(node)).append("\n$$\n\n");
            case "blockquote" -> {
                StringBuilder nested = new StringBuilder();
                renderChildren(node.path("content"), audience, nested, depth + 1);
                for (String line : nested.toString().strip().split("\\R", -1)) output.append("> ").append(line).append('\n');
                output.append('\n');
            }
            case "bulletList" -> renderList(node.path("content"), audience, output, depth, false);
            case "orderedList" -> renderList(node.path("content"), audience, output, depth, true);
            case "listItem" -> renderListItem(node, audience, output, depth, false, 1);
            case "codeBlock" -> {
                String language = node.path("attrs").path("language").asText();
                output.append("```").append(language.replace("`", "")).append('\n');
                output.append(plainText(node.path("content"))).append("\n```\n\n");
            }
            case "horizontalRule" -> output.append("---\n\n");
            case "image" -> renderImage(node.path("attrs"), output);
            case "mindMap" -> renderMindMap(node.path("attrs"), audience, output);
            case "questionReference", "knowledgeReference" -> renderStructuredReference(type, node, audience, output);
            default -> {
                if (node.path("content").isArray()) renderChildren(node.path("content"), audience, output, depth);
                else renderMarkdownAttrs(node.path("attrs"), audience, output);
            }
        }
    }

    private void renderInlineChildren(JsonNode content, String audience, StringBuilder output) {
        if (!content.isArray()) return;
        for (JsonNode child : content) renderNode(child, audience, output, 0);
    }

    private String renderText(JsonNode node, String audience) {
        String value = escapeMarkdown(node.path("text").asText());
        JsonNode marks = node.path("marks");
        if (!marks.isArray()) return value;
        for (JsonNode mark : marks) {
            String type = mark.path("type").asText();
            if (type.equals("studentBlank") && audience.equals("student")) value = "____";
            else if (type.equals("bold")) value = "**" + value + "**";
            else if (type.equals("italic")) value = "*" + value + "*";
            else if (type.equals("strike")) value = "~~" + value + "~~";
            else if (type.equals("code")) value = "`" + value.replace("`", "\\`") + "`";
            else if (type.equals("link")) {
                String href = mark.path("attrs").path("href").asText();
                if (href.startsWith("https://") || href.startsWith("http://")) value = "[" + value + "](" + href + ")";
            }
        }
        return value;
    }

    private void renderList(JsonNode items, String audience, StringBuilder output, int depth, boolean ordered) {
        if (!items.isArray()) return;
        int number = 1;
        for (JsonNode item : items) renderListItem(item, audience, output, depth, ordered, number++);
        if (depth == 0) output.append('\n');
    }

    private void renderListItem(JsonNode item, String audience, StringBuilder output, int depth, boolean ordered, int number) {
        StringBuilder body = new StringBuilder();
        renderChildren(item.path("content"), audience, body, depth + 1);
        String[] lines = body.toString().strip().split("\\R", -1);
        String prefix = "  ".repeat(Math.max(0, depth)) + (ordered ? number + ". " : "- ");
        output.append(prefix).append(lines.length == 0 ? "" : lines[0]).append('\n');
        String continuation = " ".repeat(prefix.length());
        for (int i = 1; i < lines.length; i++) {
            if (!lines[i].isBlank()) output.append(continuation).append(lines[i]).append('\n');
        }
    }

    private void renderImage(JsonNode attrs, StringBuilder output) {
        String source = attrs.path("src").asText();
        if (source.isBlank() || source.contains("\\") || source.startsWith("/") || source.contains(":")) {
            throw new RenderSourceException("render_image_reference_invalid");
        }
        String alt = attrs.path("alt").asText("image").replace("]", "\\]");
        output.append("![").append(alt).append("](").append(source).append(")\n\n");
    }

    private void renderMindMap(JsonNode attrs, String audience, StringBuilder output) {
        String title = attrs.path("title").asText("思维导图");
        output.append("### ").append(escapeMarkdown(title)).append("\n\n");
        Set<String> blankIds = parseStringSet(attrs.get("studentBlankNodeIds"));
        JsonNode roots = attrs.path("nodes");
        for (JsonNode root : roots) renderMindMapNode(root, audience, blankIds, output, 0);
        output.append('\n');
    }

    private void renderMindMapNode(JsonNode node, String audience, Set<String> blankIds, StringBuilder output, int depth) {
        String id = node.path("id").asText();
        String text = audience.equals("student") && blankIds.contains(id) ? "____" : escapeMarkdown(node.path("text").asText());
        output.append("  ".repeat(depth)).append("- ").append(text).append('\n');
        for (JsonNode child : node.path("children")) renderMindMapNode(child, audience, blankIds, output, depth + 1);
    }

    private void renderStructuredReference(String type, JsonNode node, String audience, StringBuilder output) {
        JsonNode attrs = node.path("attrs");
        String preferred = audience.equals("student") ? "studentMarkdown" : "teacherMarkdown";
        if (attrs.path(preferred).isTextual() && !attrs.path(preferred).asText().isBlank()) {
            output.append(attrs.path(preferred).asText().strip()).append("\n\n");
            return;
        }
        int before = output.length();
        renderMarkdownAttrs(attrs, audience, output);
        if (output.length() == before && node.path("content").isArray()) {
            renderChildren(node.path("content"), audience, output, 0);
        }
        if (output.length() == before) {
            // References must be hydrated while a snapshot is created. Rendering is
            // deliberately too late to consult mutable question or knowledge data.
            String id = attrs.path(type.equals("questionReference") ? "questionId" : "moduleId").asText();
            String referenceType = type.equals("questionReference") ? "question_reference" : "knowledge_reference";
            throw new RenderSourceException(referenceType + "_not_hydrated:" + id);
        }
    }

    private void renderMarkdownAttrs(JsonNode attrs, String audience, StringBuilder output) {
        Set<String> emitted = new HashSet<>();
        String audienceField = audience.equals("student") ? "studentMarkdown" : "teacherMarkdown";
        if (attrs.path(audienceField).isTextual() && !attrs.path(audienceField).asText().isBlank()) {
            output.append(attrs.path(audienceField).asText().strip()).append("\n\n");
            emitted.add(audienceField);
        }
        for (String field : MARKDOWN_FIELDS) {
            if (emitted.contains(field) || field.equals("teacherMarkdown") || field.equals("studentMarkdown")) continue;
            JsonNode value = attrs.get(field);
            if (value != null && value.isTextual() && !value.asText().isBlank()) {
                output.append(value.asText().strip()).append("\n\n");
            }
        }
    }

    private Set<String> parseStringSet(JsonNode value) {
        if (value == null || value.isNull() || value.isMissingNode()) return Set.of();
        JsonNode parsed = value;
        if (value.isTextual()) {
            try {
                parsed = objectMapper.readTree(value.asText());
            } catch (JsonProcessingException exception) {
                throw new RenderSourceException("mind_map_blank_ids_invalid");
            }
        }
        Set<String> result = new HashSet<>();
        if (parsed.isArray()) parsed.forEach(item -> result.add(item.asText()));
        return result;
    }

    private String formula(JsonNode node) {
        String latex = node.path("attrs").path("latex").asText().strip();
        if (latex.isBlank()) throw new RenderSourceException("render_formula_latex_missing");
        return latex;
    }

    private String plainText(JsonNode content) {
        List<String> parts = new ArrayList<>();
        if (content.isArray()) content.forEach(node -> parts.add(node.path("text").asText()));
        return String.join("", parts);
    }

    private String escapeMarkdown(String value) {
        return value.replace("\\", "\\\\")
                .replace("*", "\\*")
                .replace("_", "\\_")
                .replace("[", "\\[")
                .replace("]", "\\]")
                .replace("`", "\\`");
    }
}
