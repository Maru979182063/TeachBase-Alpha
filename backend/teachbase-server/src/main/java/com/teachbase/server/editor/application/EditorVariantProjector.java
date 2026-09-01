package com.teachbase.server.editor.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

@Component
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 * Projects the canonical editor document into one teaching variant without mutating
 * source JSON. Independent packs bypass layer filtering; synchronized handouts use
 * explicit overrides first and target-layer projection as the fallback.
 */
public class EditorVariantProjector {

    private final ObjectMapper objectMapper;

    public EditorVariantProjector(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public JsonNode project(EditorDraft draft, String variantKey) {
        if (draft.documentKind().equals("independent_question_pack")) {
            return draft.masterDoc().deepCopy();
        }
        int index = variantIndex(variantKey);
        JsonNode override = draft.versionOverrides().get(index);
        if (override != null && !override.isNull()) return override.deepCopy();
        JsonNode projected = projectNode(draft.masterDoc(), variantLabel(variantKey));
        if (projected == null) throw new EditorContentValidationException("variant_projection_empty");
        return projected;
    }

    private JsonNode projectNode(JsonNode source, String variantLabel) {
        if (!source.isObject()) return source.deepCopy();
        ObjectNode node = source.deepCopy();
        if ("questionReference".equals(node.path("type").asText())) {
            // 父引用与每个被选中的子题可以属于不同展示层。
            // 必须一起过滤，避免空的组合题泄漏到最终生成的讲义中。
            ObjectNode attrs = node.withObject("/attrs");
            if (!targetLayers(attrs.path("targetLayers").asText()).contains(variantLabel)) return null;
            if ("children".equals(attrs.path("questionUsageMode").asText())) {
                JsonNode selectedSource = parseJsonAttribute(attrs.get("selectedChildIds"), objectMapper.createArrayNode());
                JsonNode configs = parseJsonAttribute(attrs.get("childConfigs"), objectMapper.createObjectNode());
                ArrayNode selected = objectMapper.createArrayNode();
                for (JsonNode childId : selectedSource) {
                    String id = childId.asText();
                    String childLayers = configs.path(id).path("targetLayers")
                            .asText(attrs.path("targetLayers").asText());
                    if (targetLayers(childLayers).contains(variantLabel)) selected.add(id);
                }
                if (selected.isEmpty()) return null;
                if (attrs.path("selectedChildIds").isTextual()) {
                    try {
                        attrs.put("selectedChildIds", objectMapper.writeValueAsString(selected));
                    } catch (JsonProcessingException exception) {
                        throw new IllegalStateException("variant_projection_not_serializable", exception);
                    }
                } else {
                    attrs.set("selectedChildIds", selected);
                }
            }
        }
        JsonNode content = node.get("content");
        if (content != null && content.isArray()) {
            ArrayNode projectedChildren = objectMapper.createArrayNode();
            for (JsonNode child : content) {
                JsonNode projectedChild = projectNode(child, variantLabel);
                if (projectedChild != null) projectedChildren.add(projectedChild);
            }
            node.set("content", projectedChildren);
        }
        return node;
    }

    private JsonNode parseJsonAttribute(JsonNode value, JsonNode fallback) {
        if (value == null || value.isNull() || value.isMissingNode()) return fallback;
        if (!value.isTextual()) return value;
        try {
            return objectMapper.readTree(value.asText());
        } catch (JsonProcessingException exception) {
            throw new EditorContentValidationException("editor_reference_attribute_invalid");
        }
    }

    private List<String> targetLayers(String value) {
        String source = value == null || value.isBlank() ? "基础版,进阶版,常规版" : value;
        List<String> result = new ArrayList<>();
        for (String item : source.split(",")) {
            if (!item.trim().isBlank()) result.add(item.trim());
        }
        return result;
    }

    private int variantIndex(String key) {
        return switch (key) {
            case "basic" -> 0;
            case "advanced" -> 1;
            case "common" -> 2;
            default -> throw new EditorContentValidationException("unsupported_editor_variant");
        };
    }

    private String variantLabel(String key) {
        return switch (key) {
            case "basic" -> "基础版";
            case "advanced" -> "进阶版";
            case "common" -> "常规版";
            default -> throw new EditorContentValidationException("unsupported_editor_variant");
        };
    }
}
