package com.teachbase.server.editor.application;

import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 中文维护说明：编辑器变体的业务身份始终是英文 key；中文名称只用于展示和读取历史数据。
 * 新内容必须持久化 key，旧的“常用版/常规版”仅在兼容解析时映射到 common。
 */
public final class EditorVariantContract {

    public static final String BASIC = "basic";
    public static final String ADVANCED = "advanced";
    public static final String COMMON = "common";

    // master-overrides-v1 已经按此顺序落库，不能通过名称修复改变数组位置。
    private static final List<String> OVERRIDE_ORDER = List.of(BASIC, ADVANCED, COMMON);
    private static final Map<String, String> DISPLAY_NAMES = Map.of(
            BASIC, "基础版",
            ADVANCED, "进阶版",
            COMMON, "常用版");
    private static final Map<String, String> READ_ALIASES = Map.of(
            BASIC, BASIC,
            ADVANCED, ADVANCED,
            COMMON, COMMON,
            "基础版", BASIC,
            "进阶版", ADVANCED,
            "常用版", COMMON,
            "常规版", COMMON);

    private EditorVariantContract() {
    }

    public static boolean isKey(String value) {
        return OVERRIDE_ORDER.contains(value);
    }

    public static int overrideIndex(String key) {
        int index = OVERRIDE_ORDER.indexOf(key);
        if (index < 0) throw new EditorContentValidationException("unsupported_editor_variant");
        return index;
    }

    public static String displayName(String key) {
        String displayName = DISPLAY_NAMES.get(key);
        if (displayName == null) throw new EditorContentValidationException("unsupported_editor_variant");
        return displayName;
    }

    public static Set<String> targetLayerKeys(String value) {
        String source = value == null || value.isBlank() ? String.join(",", OVERRIDE_ORDER) : value;
        Set<String> result = new LinkedHashSet<>();
        for (String item : source.split(",")) {
            String token = item.trim();
            if (token.isBlank()) continue;
            String key = READ_ALIASES.get(token);
            if (key == null) throw new EditorContentValidationException("question_target_layers_invalid");
            result.add(key);
        }
        if (result.isEmpty()) throw new EditorContentValidationException("question_target_layers_invalid");
        return Collections.unmodifiableSet(result);
    }

    public static String canonicalTargetLayers(String value) {
        return String.join(",", targetLayerKeys(value));
    }
}
