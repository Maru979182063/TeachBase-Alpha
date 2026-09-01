package com.teachbase.server.editor.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.springframework.stereotype.Component;

@Component
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 * Validates and canonicalizes the frontend-owned Tiptap document contract.
 * Canonical ordering is part of hashing, making equivalent JSON produce the same
 * content identity regardless of object field insertion order.
 */
public class EditorContentValidator {

    private static final int MAX_DOCUMENT_NODES = 20_000;
    private static final int MAX_DOCUMENT_DEPTH = 64;
    private static final int MAX_MIND_MAP_NODES = 1_000;
    private static final int MAX_MIND_MAP_DEPTH = 32;
    private final ObjectMapper objectMapper;

    public EditorContentValidator(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public ValidatedEditorContent validate(int schemaVersion, JsonNode masterDoc, JsonNode versionOverrides) {
        if (schemaVersion != 1) {
            throw new EditorContentValidationException("unsupported_editor_schema_version");
        }
        validateDocument(masterDoc);
        if (versionOverrides == null || !versionOverrides.isArray() || versionOverrides.size() != 3) {
            throw new EditorContentValidationException("version_overrides_must_have_three_entries");
        }
        for (JsonNode override : versionOverrides) {
            if (!override.isNull()) validateDocument(override);
        }

        JsonNode canonicalMaster = canonicalize(masterDoc);
        JsonNode canonicalOverrides = canonicalize(versionOverrides);
        try {
            String masterJson = objectMapper.writeValueAsString(canonicalMaster);
            String overridesJson = objectMapper.writeValueAsString(canonicalOverrides);
            ObjectNode envelope = objectMapper.createObjectNode();
            envelope.put("editorModel", "master-overrides-v1");
            envelope.put("schemaVersion", schemaVersion);
            envelope.set("masterDoc", canonicalMaster);
            envelope.set("versionOverrides", canonicalOverrides);
            String canonicalEnvelope = objectMapper.writeValueAsString(canonicalize(envelope));
            return new ValidatedEditorContent(
                    schemaVersion,
                    canonicalMaster,
                    canonicalOverrides,
                    masterJson,
                    overridesJson,
                    sha256(canonicalEnvelope));
        } catch (JsonProcessingException exception) {
            throw new EditorContentValidationException("editor_content_not_serializable");
        }
    }

    private void validateDocument(JsonNode document) {
        if (document == null || !document.isObject() || !"doc".equals(document.path("type").asText())) {
            throw new EditorContentValidationException("editor_document_root_must_be_tiptap_doc");
        }
        int[] nodeCount = {0};
        validateNode(document, 0, nodeCount);
    }

    private void validateNode(JsonNode node, int depth, int[] nodeCount) {
        if (!node.isObject() || node.path("type").asText().isBlank()) {
            throw new EditorContentValidationException("editor_node_type_required");
        }
        // 这些上限用于保护服务和下游渲染器，避免恶意输入或意外递归文档耗尽资源。
        if (depth > MAX_DOCUMENT_DEPTH || ++nodeCount[0] > MAX_DOCUMENT_NODES) {
            throw new EditorContentValidationException("editor_document_complexity_limit_exceeded");
        }
        String type = node.path("type").asText();
        JsonNode attrs = node.path("attrs");
        if (type.equals("inlineMath") || type.equals("blockMath") || type.equals("formula")) {
            String latex = attrs.path("latex").asText().trim();
            if (latex.isBlank() || latex.length() > 16_000 || latex.indexOf('\0') >= 0) {
                throw new EditorContentValidationException("formula_latex_invalid");
            }
        }
        if (type.equals("mindMap")) validateMindMap(attrs);
        if (type.equals("image")) validateImageSource(attrs.path("src").asText());
        if (type.equals("knowledgeReference")) validateKnowledgeBlankRanges(attrs.get("studentBlankRanges"));
        validateMarks(node.path("marks"));
        if (attrs.isObject()) {
            attrs.fields().forEachRemaining(entry -> {
                if (entry.getKey().endsWith("Markdown") && entry.getValue().isTextual()) {
                    validateMarkdown(entry.getValue().asText());
                }
            });
        }
        JsonNode content = node.path("content");
        if (!content.isMissingNode() && !content.isArray()) {
            throw new EditorContentValidationException("editor_node_content_must_be_array");
        }
        if (content.isArray()) {
            for (JsonNode child : content) validateNode(child, depth + 1, nodeCount);
        }
    }

    private void validateMarks(JsonNode marks) {
        if (marks.isMissingNode()) return;
        if (!marks.isArray()) throw new EditorContentValidationException("editor_marks_must_be_array");
        for (JsonNode mark : marks) {
            if (!"studentBlank".equals(mark.path("type").asText())) continue;
            String id = mark.path("attrs").path("id").asText().trim();
            if (id.isBlank() || id.length() > 128) {
                throw new EditorContentValidationException("student_blank_id_invalid");
            }
        }
    }

    private void validateKnowledgeBlankRanges(JsonNode value) {
        if (value == null || value.isNull() || value.isMissingNode()) return;
        JsonNode parsed = value;
        if (value.isTextual()) {
            try {
                parsed = objectMapper.readTree(value.asText());
            } catch (JsonProcessingException exception) {
                throw new EditorContentValidationException("knowledge_blank_ranges_invalid");
            }
        }
        if (!parsed.isArray()) throw new EditorContentValidationException("knowledge_blank_ranges_invalid");
        Set<String> ids = new HashSet<>();
        for (JsonNode range : parsed) {
            String id = range.path("id").asText().trim();
            int region = range.path("region").asInt(-1);
            int start = range.path("start").asInt(-1);
            int end = range.path("end").asInt(-1);
            if (id.isBlank() || !ids.add(id) || region < 0 || start < 0 || end <= start || !range.path("answer").isTextual()) {
                throw new EditorContentValidationException("knowledge_blank_ranges_invalid");
            }
        }
    }

    private void validateMindMap(JsonNode attrs) {
        JsonNode nodes = attrs.path("nodes");
        if (!nodes.isArray() || nodes.isEmpty()) {
            throw new EditorContentValidationException("mind_map_nodes_required");
        }
        Set<String> ids = new HashSet<>();
        int[] count = {0};
        for (JsonNode node : nodes) validateMindMapNode(node, 0, count, ids);
        Set<String> blankIds = parseStringSet(attrs.get("studentBlankNodeIds"), "mind_map_blank_ids_invalid");
        if (!ids.containsAll(blankIds)) {
            throw new EditorContentValidationException("mind_map_blank_node_missing");
        }
        String rootId = nodes.get(0).path("id").asText();
        if (blankIds.contains(rootId)) {
            throw new EditorContentValidationException("mind_map_root_cannot_be_blank");
        }
    }

    private void validateMindMapNode(JsonNode node, int depth, int[] count, Set<String> ids) {
        if (!node.isObject() || depth > MAX_MIND_MAP_DEPTH || ++count[0] > MAX_MIND_MAP_NODES) {
            throw new EditorContentValidationException("mind_map_complexity_limit_exceeded");
        }
        String id = node.path("id").asText().trim();
        String text = node.path("text").asText().trim();
        if (id.isBlank() || !ids.add(id)) throw new EditorContentValidationException("mind_map_node_id_invalid");
        if (text.isBlank() || text.length() > 2_000) throw new EditorContentValidationException("mind_map_node_text_invalid");
        JsonNode children = node.path("children");
        if (!children.isArray()) throw new EditorContentValidationException("mind_map_children_must_be_array");
        for (JsonNode child : children) validateMindMapNode(child, depth + 1, count, ids);
    }

    private Set<String> parseStringSet(JsonNode value, String errorCode) {
        if (value == null || value.isNull() || value.isMissingNode()) return Set.of();
        JsonNode parsed = value;
        if (value.isTextual()) {
            try {
                parsed = objectMapper.readTree(value.asText());
            } catch (JsonProcessingException exception) {
                throw new EditorContentValidationException(errorCode);
            }
        }
        if (!parsed.isArray()) throw new EditorContentValidationException(errorCode);
        Set<String> result = new HashSet<>();
        for (JsonNode item : parsed) {
            if (!item.isTextual() || item.asText().isBlank() || !result.add(item.asText())) {
                throw new EditorContentValidationException(errorCode);
            }
        }
        return result;
    }

    private void validateImageSource(String source) {
        if (source.isBlank()) throw new EditorContentValidationException("image_source_required");
        String lower = source.toLowerCase();
        if (lower.startsWith("data:") || source.contains("\\") || source.matches("^[A-Za-z]:[\\/].*$")) {
            throw new EditorContentValidationException("image_source_must_reference_registered_asset");
        }
    }

    private void validateMarkdown(String markdown) {
        if (markdown.length() > 2_000_000 || markdown.indexOf('\0') >= 0) {
            throw new EditorContentValidationException("markdown_source_invalid");
        }
    }

    private JsonNode canonicalize(JsonNode node) {
        // 数组顺序代表编辑器语义，必须保留；对象键顺序没有业务语义，
        // 因此统一排序，以获得跨进程稳定的内容哈希。
        if (node.isObject()) {
            ObjectNode result = objectMapper.createObjectNode();
            Map<String, JsonNode> fields = new TreeMap<>();
            Iterator<Map.Entry<String, JsonNode>> iterator = node.fields();
            iterator.forEachRemaining(entry -> fields.put(entry.getKey(), entry.getValue()));
            fields.forEach((key, value) -> result.set(key, canonicalize(value)));
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = objectMapper.createArrayNode();
            node.forEach(item -> result.add(canonicalize(item)));
            return result;
        }
        return node.deepCopy();
    }

    private String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("sha256_unavailable", exception);
        }
    }
}
